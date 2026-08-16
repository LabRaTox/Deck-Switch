"""PipeWire-Steuerung über die CLI-Tools ``wpctl`` und ``pactl``.

Kein direktes PipeWire-Binding — die CLI-Tools sind auf CachyOS Standard,
stabil und im Fehlerfall von Hand nachvollziehbar.

Aufgabenteilung:
* ``wpctl`` für die Default-Geräte (``@DEFAULT_AUDIO_SINK@`` /
  ``@DEFAULT_AUDIO_SOURCE@``) — dafür ist es gebaut.
* ``pactl`` für alles, was ein *benanntes* Gerät betrifft (wpctl kennt nur
  Node-IDs) sowie für Geräteliste, Default-Wechsel und das Umziehen
  laufender Streams.

``pactl subscribe`` läuft dauerhaft in einem Hintergrund-Thread: ändert
jemand die Lautstärke außerhalb der App (Systemeinstellungen, Mixer, andere
Software), kommt sofort ein Neuzeichnen — nicht erst beim nächsten Tick.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
DEFAULT_SOURCE = "@DEFAULT_AUDIO_SOURCE@"

_VOLUME_RE = re.compile(r"Volume:\s*([0-9.]+)(\s*\[MUTED\])?")
_EVENT_RE = re.compile(r"Event '(\w+)' on (\S+) #(\d+)")

#: Wie lange ein gelesener Lautstärkewert als frisch gilt. Verhindert, dass
#: acht Kacheln pro Tick je einen Subprozess starten.
CACHE_TTL_S = 0.25

COMMAND_TIMEOUT_S = 3.0


@dataclass(slots=True)
class VolumeState:
    volume: float = 0.0
    muted: bool = False
    available: bool = False


@dataclass(slots=True)
class SinkInfo:
    index: int
    name: str
    description: str
    is_default: bool = False


class AudioUnavailable(RuntimeError):
    pass


class AudioService:
    def __init__(self) -> None:
        self.has_wpctl = shutil.which("wpctl") is not None
        self.has_pactl = shutil.which("pactl") is not None
        self._cache: dict[str, tuple[float, VolumeState]] = {}
        self._sinks_cache: tuple[float, list[SinkInfo]] | None = None
        self._sources_cache: tuple[float, list[SinkInfo]] | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str, str], None]] = []
        self._subscriber: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def available(self) -> bool:
        return self.has_wpctl or self.has_pactl

    # -- Änderungen von außen ---------------------------------------------

    def add_listener(self, callback: Callable[[str, str], None]) -> None:
        """``callback(event, facility)`` bei jedem relevanten pactl-Event.

        Wird aus dem Watcher-Thread gerufen — der Empfänger muss selbst
        threadsicher weiterreichen.
        """
        self._listeners.append(callback)

    def start_watcher(self) -> None:
        if not self.has_pactl or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._watch, name="pactl-subscribe", daemon=True
        )
        self._thread.start()

    def stop_watcher(self) -> None:
        self._stop.set()
        if self._subscriber is not None:
            self._subscriber.terminate()
            self._subscriber = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _watch(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._subscriber = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                backoff = 1.0
                assert self._subscriber.stdout is not None
                for line in self._subscriber.stdout:
                    if self._stop.is_set():
                        break
                    match = _EVENT_RE.search(line)
                    if match is None:
                        continue
                    event, facility = match.group(1), match.group(2)
                    if facility not in {"sink", "source", "server", "sink-input"}:
                        continue
                    self.invalidate()
                    for listener in list(self._listeners):
                        try:
                            listener(event, facility)
                        except Exception:
                            log.exception("Audio-Listener hat geworfen")
            except FileNotFoundError:
                log.error("pactl nicht gefunden — Audio-Events deaktiviert")
                return
            except Exception as exc:
                log.warning("pactl subscribe abgebrochen: %s", exc)

            if self._stop.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._sinks_cache = None
            self._sources_cache = None

    # -- Lautstärke --------------------------------------------------------

    def get_volume(self, target: str = DEFAULT_SINK) -> VolumeState:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(target)
            if cached is not None and now - cached[0] < CACHE_TTL_S:
                return cached[1]

        state = self._read_volume(target)
        with self._lock:
            self._cache[target] = (now, state)
        return state

    def _read_volume(self, target: str) -> VolumeState:
        if target in (DEFAULT_SINK, DEFAULT_SOURCE) and self.has_wpctl:
            out = self._run(["wpctl", "get-volume", target])
            if out is None:
                return VolumeState()
            match = _VOLUME_RE.search(out)
            if match is None:
                return VolumeState()
            return VolumeState(float(match.group(1)), bool(match.group(2)), True)

        # Benanntes Gerät: aus der JSON-Liste ziehen.
        kind = "sources" if self._is_source(target) else "sinks"
        for entry in self._list_raw(kind):
            if entry.get("name") == target or str(entry.get("index")) == target:
                volumes = entry.get("volume") or {}
                values = [
                    channel.get("value", 0)
                    for channel in volumes.values()
                    if isinstance(channel, dict)
                ]
                level = (max(values) / 65536.0) if values else 0.0
                return VolumeState(level, bool(entry.get("mute")), True)
        return VolumeState()

    def set_volume(self, target: str, value: float) -> None:
        value = max(0.0, min(1.5, value))
        if target in (DEFAULT_SINK, DEFAULT_SOURCE) and self.has_wpctl:
            self._run(["wpctl", "set-volume", "-l", "1.5", target, f"{value:.3f}"])
        else:
            command = "set-source-volume" if self._is_source(target) else "set-sink-volume"
            self._run(["pactl", command, target, f"{round(value * 100)}%"])
        self.invalidate()

    def change_volume(self, target: str, delta_percent: float) -> VolumeState:
        """Relative Änderung — der Weg, den der Lautstärke-Dial nimmt."""
        step = abs(delta_percent)
        sign = "+" if delta_percent >= 0 else "-"
        if target in (DEFAULT_SINK, DEFAULT_SOURCE) and self.has_wpctl:
            self._run(
                ["wpctl", "set-volume", "-l", "1.5", target, f"{step:.0f}%{sign}"]
            )
        else:
            command = "set-source-volume" if self._is_source(target) else "set-sink-volume"
            self._run(["pactl", command, target, f"{sign}{step:.0f}%"])
        self.invalidate()
        return self.get_volume(target)

    def toggle_mute(self, target: str = DEFAULT_SINK) -> bool:
        if target in (DEFAULT_SINK, DEFAULT_SOURCE) and self.has_wpctl:
            self._run(["wpctl", "set-mute", target, "toggle"])
        else:
            command = "set-source-mute" if self._is_source(target) else "set-sink-mute"
            self._run(["pactl", command, target, "toggle"])
        self.invalidate()
        return self.get_volume(target).muted

    def set_mute(self, target: str, muted: bool) -> None:
        flag = "1" if muted else "0"
        if target in (DEFAULT_SINK, DEFAULT_SOURCE) and self.has_wpctl:
            self._run(["wpctl", "set-mute", target, flag])
        else:
            command = "set-source-mute" if self._is_source(target) else "set-sink-mute"
            self._run(["pactl", command, target, flag])
        self.invalidate()

    # -- Geräte ------------------------------------------------------------

    def list_sinks(self, include_monitors: bool = False) -> list[SinkInfo]:
        now = time.monotonic()
        with self._lock:
            if self._sinks_cache and now - self._sinks_cache[0] < 2.0:
                return self._sinks_cache[1]

        default = self.get_default_sink()
        sinks = [
            SinkInfo(
                index=entry.get("index", -1),
                name=entry.get("name", ""),
                description=_clean_description(entry),
                is_default=entry.get("name") == default,
            )
            for entry in self._list_raw("sinks")
            if entry.get("name")
        ]
        if not include_monitors:
            sinks = [s for s in sinks if not s.name.endswith(".monitor")]

        with self._lock:
            self._sinks_cache = (now, sinks)
        return sinks

    def list_sources(self, include_monitors: bool = False) -> list[SinkInfo]:
        now = time.monotonic()
        with self._lock:
            if self._sources_cache and now - self._sources_cache[0] < 2.0:
                return self._sources_cache[1]

        default = self.get_default_source()
        sources = [
            SinkInfo(
                index=entry.get("index", -1),
                name=entry.get("name", ""),
                description=_clean_description(entry),
                is_default=entry.get("name") == default,
            )
            for entry in self._list_raw("sources")
            if entry.get("name")
        ]
        if not include_monitors:
            # Monitore sind Mitschnitte von Ausgängen, keine echten Eingänge.
            sources = [
                s
                for s in sources
                if not s.name.endswith(".monitor")
                and not s.description.lower().startswith(("monitor of", "monitor von"))
            ]

        with self._lock:
            self._sources_cache = (now, sources)
        return sources

    def get_default_sink(self) -> str:
        return (self._run(["pactl", "get-default-sink"]) or "").strip()

    def get_default_source(self) -> str:
        return (self._run(["pactl", "get-default-source"]) or "").strip()

    def switch_output(self, sink_name: str, *, move_streams: bool = True) -> bool:
        """Ausgabegerät wechseln — inklusive laufender Streams.

        Nur ``set-default-sink`` würde ausschließlich *neue* Wiedergabe
        betreffen; Spotify, Browser oder ein laufendes Spiel blieben auf dem
        alten Gerät. Deshalb werden alle aktiven sink-inputs explizit
        mitgezogen.
        """
        if not self.has_pactl:
            raise AudioUnavailable("pactl nicht verfügbar")

        ok = self._run(["pactl", "set-default-sink", sink_name]) is not None
        if ok and move_streams:
            for entry in self._list_raw("sink-inputs"):
                index = entry.get("index")
                if index is None:
                    continue
                self._run(["pactl", "move-sink-input", str(index), sink_name])
        self.invalidate()
        return ok

    def move_stream(self, sink_input_index: int, sink_name: str) -> bool:
        return self._run(
            ["pactl", "move-sink-input", str(sink_input_index), sink_name]
        ) is not None

    def list_streams(self) -> list[dict]:
        result = []
        for entry in self._list_raw("sink-inputs"):
            props = entry.get("properties") or {}
            volumes = entry.get("volume") or {}
            values = [
                channel.get("value", 0)
                for channel in volumes.values()
                if isinstance(channel, dict)
            ]
            result.append(
                {
                    "index": entry.get("index"),
                    "sink": entry.get("sink"),
                    "name": props.get("application.name")
                    or props.get("media.name")
                    or f"Stream {entry.get('index')}",
                    "muted": bool(entry.get("mute")),
                    "volume": (max(values) / 65536.0) if values else 0.0,
                }
            )
        return result

    # -- Einzelne Anwendungs-Streams --------------------------------------

    def set_stream_volume(self, index: int, value: float) -> None:
        value = max(0.0, min(1.5, value))
        self._run(["pactl", "set-sink-input-volume", str(index), f"{round(value * 100)}%"])
        self.invalidate()

    def change_stream_volume(self, index: int, delta_percent: float) -> None:
        sign = "+" if delta_percent >= 0 else "-"
        self._run(
            ["pactl", "set-sink-input-volume", str(index), f"{sign}{abs(delta_percent):.0f}%"]
        )
        self.invalidate()

    def toggle_stream_mute(self, index: int) -> None:
        self._run(["pactl", "set-sink-input-mute", str(index), "toggle"])
        self.invalidate()

    # -- Subprozess-Handhabung --------------------------------------------

    def _list_raw(self, what: str) -> list[dict]:
        out = self._run(["pactl", "-f", "json", "list", what])
        if not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            log.warning("pactl-JSON (%s) nicht lesbar: %s", what, exc)
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _is_source(target: str) -> bool:
        return target == DEFAULT_SOURCE or ".monitor" in target or "alsa_input" in target

    def _run(self, command: list[str]) -> str | None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            log.error("Befehl nicht gefunden: %s", command[0])
            return None
        except subprocess.TimeoutExpired:
            log.warning("Zeitüberschreitung: %s", " ".join(command))
            return None

        if result.returncode != 0:
            # pactl schreibt bei Nicht-ASCII-Properties Warnungen auf stderr,
            # obwohl der Aufruf erfolgreich war — nur echte Fehlercodes melden.
            log.warning(
                "%s fehlgeschlagen (%s): %s",
                " ".join(command),
                result.returncode,
                result.stderr.strip()[:200],
            )
            return None
        return result.stdout


def _clean_description(entry: dict) -> str:
    """Anzeigename eines Geräts.

    PipeWire liefert für manche Knoten wörtlich ``"(null)"`` — und zwar
    sowohl als ``description`` als auch in den Properties. Solche Werte
    müssen überall aussortiert werden, sonst steht „(null)“ im Gerätemenü.
    """

    def usable(value) -> str | None:
        text = str(value).strip() if value else ""
        return text if text and text != "(null)" else None

    props = entry.get("properties") or {}
    return (
        usable(entry.get("description"))
        or usable(props.get("device.description"))
        or usable(props.get("node.description"))
        or usable(props.get("node.nick"))
        or usable(entry.get("name"))
        or "Unbekannt"
    )
