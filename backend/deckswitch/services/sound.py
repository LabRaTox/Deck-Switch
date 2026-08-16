"""Soundboard: Klänge abspielen, gezielt auf ein Ausgabegerät.

Abgespielt wird mit ``pw-play`` aus PipeWire. Das kann als einziges der
üblichen Werkzeuge das Ziel pro Wiedergabe angeben — genau darum geht es
beim Soundboard: Der Jingle soll in den Stream, aber nicht zwingend in die
eigenen Kopfhörer.

Jede laufende Wiedergabe gehört einer Belegung. Damit kann dieselbe Taste
den Klang wieder stoppen, und beim Wechsel der Seite verstummt nichts, was
noch laufen soll.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Was sich abspielen lässt. WAV und FLAC kann pw-play direkt, den Rest über
#: libsndfile; MP3 kann es je nach Aufbau nicht — dann greift der Umweg.
PLAYABLE_SUFFIXES = {".wav", ".flac", ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac"}

#: Zweitweg für Formate, die pw-play nicht kennt.
FALLBACK_PLAYERS = (["mpv", "--no-video", "--really-quiet"], ["ffplay", "-nodisp", "-autoexit"])


class SoundError(RuntimeError):
    """Die Datei ließ sich nicht abspielen."""


@dataclass
class Playback:
    """Eine laufende Wiedergabe."""

    process: subprocess.Popen
    path: str
    owner: str
    loop: bool = False
    #: Wird gesetzt, wenn absichtlich gestoppt wurde — dann startet die
    #: Schleife nicht neu.
    cancelled: bool = False
    thread: threading.Thread | None = field(default=None, repr=False)


class SoundService:
    def __init__(self) -> None:
        self._playing: dict[str, Playback] = {}
        self._lock = threading.Lock()
        #: Wird gerufen, wenn eine Wiedergabe von selbst endet — die Taste
        #: soll dann wieder als „gestoppt" gezeichnet werden.
        self.on_finished = None

    # -- Abspielen ---------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        if shutil.which("pw-play") is None:
            return False, "'pw-play' fehlt (Paket pipewire-audio)"
        return True, ""

    def is_playing(self, owner: str) -> bool:
        with self._lock:
            entry = self._playing.get(owner)
            return entry is not None and entry.process.poll() is None

    def play(
        self,
        path: str,
        *,
        owner: str,
        sink: str = "",
        volume: int = 100,
        loop: bool = False,
    ) -> None:
        """Spielt eine Datei ab. Läuft dieselbe Belegung schon, wird ersetzt."""
        file = Path(path).expanduser()
        if not file.is_file():
            raise SoundError(f"Datei nicht gefunden: {path}")
        if file.suffix.lower() not in PLAYABLE_SUFFIXES:
            raise SoundError(f"Nicht unterstütztes Format: {file.suffix}")

        self.stop(owner)
        process = self._spawn(file, sink=sink, volume=volume)
        entry = Playback(process=process, path=str(file), owner=owner, loop=loop)

        # Ein Wächter-Thread hält die Schleife am Laufen und meldet das Ende.
        # Ohne ihn bliebe ein Zombie stehen und die Taste zeigte „läuft".
        thread = threading.Thread(
            target=self._watch,
            args=(entry, file, sink, volume),
            name=f"sound-{owner}",
            daemon=True,
        )
        entry.thread = thread
        with self._lock:
            self._playing[owner] = entry
        thread.start()

    def toggle(self, path: str, *, owner: str, **kwargs) -> bool:
        """Startet oder stoppt. Liefert ``True``, wenn jetzt etwas läuft."""
        if self.is_playing(owner):
            self.stop(owner)
            return False
        self.play(path, owner=owner, **kwargs)
        return True

    def stop(self, owner: str) -> None:
        with self._lock:
            entry = self._playing.pop(owner, None)
        if entry is None:
            return
        entry.cancelled = True
        _terminate(entry.process)

    def stop_all(self) -> int:
        with self._lock:
            entries = list(self._playing.values())
            self._playing.clear()
        for entry in entries:
            entry.cancelled = True
            _terminate(entry.process)
        return len(entries)

    def close(self) -> None:
        self.stop_all()

    # -- Intern ------------------------------------------------------------

    def _spawn(self, file: Path, *, sink: str, volume: int) -> subprocess.Popen:
        ok, reason = self.available()
        if not ok:
            raise SoundError(reason)

        argv = ["pw-play"]
        if sink:
            argv += ["--target", sink]
        # pw-play erwartet einen Faktor, die GUI zeigt Prozent.
        argv += ["--volume", f"{max(0, min(150, volume)) / 100:.3f}", str(file)]

        try:
            return subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        except OSError as exc:
            raise SoundError(f"pw-play ließ sich nicht starten: {exc}") from exc

    def _watch(self, entry: Playback, file: Path, sink: str, volume: int) -> None:
        while True:
            _, stderr = entry.process.communicate()
            if entry.cancelled:
                return

            if entry.process.returncode not in (0, -15, -9):
                message = (stderr or b"").decode(errors="replace").strip()
                # pw-play kann manche Formate nicht — dann den Zweitweg
                # versuchen, statt die Taste stumm scheitern zu lassen.
                fallback = self._spawn_fallback(file, sink)
                if fallback is not None:
                    entry.process = fallback
                    continue
                log.warning("Wiedergabe von '%s' fehlgeschlagen: %s", file, message)

            if entry.loop and not entry.cancelled:
                try:
                    entry.process = self._spawn(file, sink=sink, volume=volume)
                    continue
                except SoundError:
                    pass
            break

        with self._lock:
            if self._playing.get(entry.owner) is entry:
                self._playing.pop(entry.owner, None)
        callback = self.on_finished
        if callback is not None:
            try:
                callback(entry.owner)
            except Exception:
                log.exception("Rückmeldung nach Wiedergabeende hat geworfen")

    @staticmethod
    def _spawn_fallback(file: Path, sink: str) -> subprocess.Popen | None:
        for argv in FALLBACK_PLAYERS:
            if shutil.which(argv[0]) is None:
                continue
            command = list(argv)
            if argv[0] == "mpv" and sink:
                command.append(f"--audio-device=pipewire/{sink}")
            command.append(str(file))
            try:
                return subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            except OSError:
                continue
        return None


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        process.kill()
    except OSError:
        pass
