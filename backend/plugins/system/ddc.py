"""Monitorhelligkeit über DDC/CI (``ddcutil``).

Der Punkt, um den sich hier alles dreht: **ddcutil ist langsam.** Auf dem
Entwicklungsrechner gemessen brauchte ein einzelnes ``getvcp`` rund 1,8
Sekunden, ``detect`` ebenso. Das ist eine Eigenschaft des I²C-Bus und lässt
sich nicht wegoptimieren.

Für ein Dial, an dem man dreht, ist das unbrauchbar — deshalb:

* Der aktuelle Wert wird **einmal** gelesen und danach hier geführt. Jede
  Drehung ändert nur diesen lokalen Wert, die Anzeige folgt sofort.
* Geschrieben wird **entprellt**: erst wenn eine kurze Zeit lang nicht mehr
  gedreht wurde, und dann nur der Endwert. Wer von 40 auf 70 dreht, löst
  einen ``setvcp``-Aufruf aus, nicht dreißig.
* Alles läuft in einem eigenen Thread. Ein blockierender Aufruf von fast
  zwei Sekunden im Event-Loop würde das ganze Deck einfrieren.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: VCP-Code für Helligkeit (Standard aus der MCCS-Spezifikation).
VCP_BRIGHTNESS = "10"

DETECT_TIMEOUT_S = 20.0
COMMAND_TIMEOUT_S = 15.0

#: So lange nach der letzten Drehung wird gewartet, bevor geschrieben wird.
WRITE_DELAY_S = 0.4

_DISPLAY_RE = re.compile(r"^Display\s+(\d+)", re.MULTILINE)
_MONITOR_RE = re.compile(r"^\s*Monitor:\s*(.+)$", re.MULTILINE)


@dataclass
class Display:
    number: int
    label: str


class DdcController:
    """Kennt die Monitore und hält deren Helligkeit."""

    def __init__(self) -> None:
        self._displays: list[Display] | None = None
        self._values: dict[int, int] = {}
        self._pending: dict[int, int] = {}
        self._timers: dict[int, threading.Timer] = {}
        self._lock = threading.Lock()
        self._available: bool | None = None
        self.last_error: str | None = None

    # -- Geräte ------------------------------------------------------------

    def available(self) -> bool:
        if self._available is None:
            import shutil

            self._available = shutil.which("ddcutil") is not None
            if not self._available:
                self.last_error = "ddcutil ist nicht installiert"
        return self._available

    def displays(self, refresh: bool = False) -> list[Display]:
        """Erkannte Monitore. Wird einmal ermittelt und dann behalten."""
        if self._displays is not None and not refresh:
            return self._displays
        if not self.available():
            self._displays = []
            return self._displays

        try:
            result = subprocess.run(
                ["ddcutil", "detect", "--brief"],
                capture_output=True,
                text=True,
                timeout=DETECT_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"ddcutil detect: {exc}"
            self._displays = []
            return self._displays

        numbers = [int(n) for n in _DISPLAY_RE.findall(result.stdout)]
        labels = [m.strip() for m in _MONITOR_RE.findall(result.stdout)]
        displays = []
        for index, number in enumerate(numbers):
            raw = labels[index] if index < len(labels) else ""
            displays.append(Display(number=number, label=_pretty(raw) or f"Monitor {number}"))

        self._displays = displays
        if not displays:
            self.last_error = (
                "Kein Monitor über DDC/CI erreichbar — viele Geräte müssen das "
                "im Menü erst freischalten, und über DisplayPort-Hubs geht es oft gar nicht"
            )
        return displays

    # -- Helligkeit --------------------------------------------------------

    def brightness(self, number: int) -> int | None:
        """Zuletzt bekannter Wert. ``None``, solange noch keiner gelesen wurde."""
        return self._values.get(number)

    def read_brightness(self, number: int) -> int | None:
        """Liest den Wert am Monitor. Blockiert ~2 s — nicht im Loop rufen."""
        if not self.available():
            return None
        try:
            result = subprocess.run(
                ["ddcutil", "--display", str(number), "getvcp", VCP_BRIGHTNESS, "--brief"],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"getvcp: {exc}"
            return None

        # Format: "VCP 10 C <aktuell> <maximum>"
        parts = result.stdout.split()
        if len(parts) < 5 or parts[0] != "VCP":
            self.last_error = (result.stderr or result.stdout).strip()[:120] or "getvcp fehlgeschlagen"
            return None
        try:
            value = int(parts[3])
        except ValueError:
            return None

        with self._lock:
            # Einen noch nicht geschriebenen Wunsch nicht überschreiben.
            if number not in self._pending:
                self._values[number] = value
        return value

    def nudge(self, number: int, delta: int) -> int:
        """Ändert die Helligkeit um ``delta`` und liefert den neuen Wert.

        Wirkt sofort auf den geführten Wert; der Monitor folgt kurz darauf.
        """
        with self._lock:
            current = self._pending.get(number, self._values.get(number))
            if current is None:
                # Noch nichts gelesen — von der Mitte ausgehen ist besser als
                # gar nichts zu tun. Der erste echte Wert korrigiert das.
                current = 50
            value = max(0, min(100, current + delta))
            self._pending[number] = value
            self._values[number] = value
            self._schedule(number)
        return value

    def set(self, number: int, value: int) -> int:
        with self._lock:
            value = max(0, min(100, value))
            self._pending[number] = value
            self._values[number] = value
            self._schedule(number)
        return value

    def _schedule(self, number: int) -> None:
        """Schreibvorgang neu anstoßen — Aufrufer hält die Sperre."""
        timer = self._timers.get(number)
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(WRITE_DELAY_S, self._flush, args=(number,))
        timer.daemon = True
        self._timers[number] = timer
        timer.start()

    def _flush(self, number: int) -> None:
        with self._lock:
            value = self._pending.pop(number, None)
            self._timers.pop(number, None)
        if value is None:
            return

        started = time.monotonic()
        try:
            result = subprocess.run(
                ["ddcutil", "--display", str(number), "setvcp", VCP_BRIGHTNESS, str(value)],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"setvcp: {exc}"
            log.warning("Helligkeit für Monitor %s nicht gesetzt: %s", number, exc)
            return

        if result.returncode != 0:
            self.last_error = (result.stderr or "").strip()[:120] or "setvcp fehlgeschlagen"
            log.warning("setvcp %s → %s: %s", number, value, self.last_error)
            return

        self.last_error = None
        log.debug("Monitor %s auf %d %% (%.2f s)", number, value, time.monotonic() - started)

    def shutdown(self) -> None:
        """Laufende Timer abbrechen — beim Beenden des Plugins."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


def _pretty(raw: str) -> str:
    """``PHL:27M2N3200:UK024…`` → ``27M2N3200``.

    ddcutil hängt Hersteller-Kürzel und Seriennummer an; auf einer Taste ist
    davon nur die Modellbezeichnung nützlich.
    """
    parts = [p for p in raw.split(":") if p]
    if len(parts) >= 2:
        return parts[1].strip()
    return raw.strip()
