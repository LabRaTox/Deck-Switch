"""Misst, was gerade aus einem Ausgang kommt.

Lautstärke ist eine Einstellung, Pegel ist das Signal. Gelesen wird der
Monitor des Ausgangs über ``parec``, in niedriger Abtastrate: Für eine Anzeige
reicht das, und die Messung soll auch mit vier Dials nicht auffallen.

Eine Messung läuft nur, solange eine Kachel sie zeigt. Dafür meldet sich jede
Kachel beim Zeichnen und im Tick (:meth:`Pegelmesser.lesen`). Bleibt die
Meldung aus, etwa nach einem Seitenwechsel, endet die Messung von selbst. So
braucht es keine Abmeldung, die vergessen werden könnte.
"""

from __future__ import annotations

import array
import contextlib
import logging
import math
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

ABTASTRATE = 8000
#: Sekunden Signal je Messwert, also auch der Takt der Anzeige.
FENSTER_S = 0.05
#: Unterhalb davon gilt es als Stille, die Skala beginnt hier.
UNTERGRENZE_DB = -60.0
#: So schnell fällt die Anzeige. Sie steigt sofort, sonst entgehen ihr Spitzen.
FALLEN_DB_JE_S = 30.0
#: So lange bleibt die Spitzenmarke stehen, bevor sie mitfällt.
SPITZE_HALTEN_S = 1.5
#: So lange gilt eine Meldung einer Kachel. Mehrere Ticks, damit ein später
#: Tick die Messung nicht anhält.
MELDUNG_GILT_S = 5.0
#: So oft höchstens je Kachel neu zeichnen. Jedes Bild geht über USB.
BILDER_JE_S = 12
#: Unterhalb dieser Änderung sieht niemand einen Unterschied.
SCHWELLE = 1 / 60
#: Wartezeit, bevor eine abgebrochene Messung neu startet.
NEUSTART_S = 5.0
#: So oft sieht der Wächter nach, ob noch eine Kachel misst. Ein ruhender
#: Ausgang liefert über ``parec`` gar keine Daten, das Lesen kehrte dann
#: nie zurück, und die Messung liefe ohne Kachel ewig weiter.
WAECHTER_S = 1.0
DEFAULT_TTL_S = 2.0


def db(spitze: float) -> float:
    """Spitzenwert 0.0 … 1.0 in dBFS."""
    if spitze <= 0:
        return UNTERGRENZE_DB
    return max(UNTERGRENZE_DB, 20 * math.log10(spitze))


def anzeige_wert(pegel_db: float) -> float:
    """dBFS auf die Skala 0.0 … 1.0."""
    return max(0.0, min(1.0, 1 - pegel_db / UNTERGRENZE_DB))


@dataclass
class Traegheit:
    """Macht aus rohen Messwerten eine ruhige Anzeige."""

    pegel_db: float = UNTERGRENZE_DB
    spitze_db: float = UNTERGRENZE_DB
    spitze_seit: float = 0.0

    def weiter(self, messung_db: float, dt: float, jetzt: float) -> None:
        self.pegel_db = max(messung_db, self.pegel_db - FALLEN_DB_JE_S * dt)
        if self.pegel_db >= self.spitze_db:
            self.spitze_db = self.pegel_db
            self.spitze_seit = jetzt
        elif jetzt - self.spitze_seit > SPITZE_HALTEN_S:
            self.spitze_db = max(self.pegel_db, self.spitze_db - FALLEN_DB_JE_S * dt)


@dataclass
class _Messung:
    """Eine laufende Messung an einem Monitor."""

    quelle: str
    traegheit: Traegheit = field(default_factory=Traegheit)
    #: Kennung der Kachel → (gilt bis, ihr Kontext).
    kacheln: dict[str, tuple[float, Any]] = field(default_factory=dict)
    gezeichnet: tuple[float, float] = (0.0, 0.0)
    gezeichnet_um: float = 0.0
    prozess: subprocess.Popen | None = None


class Pegelmesser:
    def __init__(
        self, standard_ausgang: Callable[[], str], neu_zeichnen: Callable[[Any], None]
    ) -> None:
        self._standard_ausgang = standard_ausgang
        self._neu_zeichnen = neu_zeichnen
        self._lock = threading.Lock()
        self._messungen: dict[str, _Messung] = {}
        self._standard: tuple[float, str] = (0.0, "")
        self._aus = False
        self.verfuegbar = shutil.which("parec") is not None

    def lesen(self, ausgang: str, standard: bool, ctx: Any) -> tuple[float, float]:
        """Pegel und Spitze (0.0 … 1.0) und die Meldung: Diese Kachel zeigt ihn."""
        if not self.verfuegbar:
            return (0.0, 0.0)
        quelle = f"{self._aufgeloest() if standard else ausgang}.monitor"
        jetzt = time.monotonic()
        with self._lock:
            if self._aus:
                return (0.0, 0.0)
            messung = self._messungen.get(quelle)
            if messung is None:
                messung = _Messung(quelle)
                self._messungen[quelle] = messung
                threading.Thread(
                    target=self._lauf, args=(messung,), name=f"pegel-{quelle}", daemon=True
                ).start()
            messung.kacheln[ctx.key] = (jetzt + MELDUNG_GILT_S, ctx)
            traegheit = messung.traegheit
            return (anzeige_wert(traegheit.pegel_db), anzeige_wert(traegheit.spitze_db))

    def stoppen(self) -> None:
        with self._lock:
            self._aus = True
            messungen = list(self._messungen.values())
            self._messungen.clear()
        for messung in messungen:
            if messung.prozess is not None:
                with contextlib.suppress(OSError):
                    messung.prozess.terminate()

    def _aufgeloest(self) -> str:
        # Wird beim Zeichnen gefragt und ist ein Programmaufruf, also nicht
        # bei jedem Bild.
        jetzt = time.monotonic()
        with self._lock:
            gueltig_bis, name = self._standard
        if jetzt < gueltig_bis:
            return name
        name = self._standard_ausgang()
        with self._lock:
            self._standard = (jetzt + DEFAULT_TTL_S, name)
        return name

    def _beenden_wenn_ungenutzt(self, messung: _Messung) -> bool:
        jetzt = time.monotonic()
        with self._lock:
            messung.kacheln = {k: v for k, v in messung.kacheln.items() if v[0] > jetzt}
            if messung.kacheln and not self._aus:
                return False
            if self._messungen.get(messung.quelle) is messung:
                del self._messungen[messung.quelle]
            return True

    def _lauf(self, messung: _Messung) -> None:
        while not self._beenden_wenn_ungenutzt(messung):
            try:
                self._miss(messung)
            except OSError as exc:
                log.debug("Pegelmessung %s: %s", messung.quelle, exc)
            if self._beenden_wenn_ungenutzt(messung):
                return
            time.sleep(NEUSTART_S)

    def _miss(self, messung: _Messung) -> None:
        bytes_je_fenster = round(ABTASTRATE * FENSTER_S) * 4
        # node.passive: Nur mithören hält den Ausgang nicht wach.
        prozess = subprocess.Popen(
            [
                "parec", "--device", messung.quelle, "--raw",
                "--format=float32le", f"--rate={ABTASTRATE}", "--channels=1",
                "--latency-msec=50", "--client-name=DECK//SWITCH",
                "--stream-name=Pegelanzeige", "--property=node.passive=true",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        messung.prozess = prozess
        fertig = threading.Event()
        threading.Thread(
            target=self._waechter,
            args=(messung, prozess, fertig),
            name=f"pegel-waechter-{messung.quelle}",
            daemon=True,
        ).start()
        zuletzt = time.monotonic()
        try:
            while True:
                daten = prozess.stdout.read(bytes_je_fenster)
                if len(daten) < 4:
                    return
                proben = array.array("f", daten[: len(daten) // 4 * 4])
                jetzt = time.monotonic()
                with self._lock:
                    messung.traegheit.weiter(db(max(map(abs, proben))), jetzt - zuletzt, jetzt)
                zuletzt = jetzt
                self._melde_aenderung(messung, jetzt)
                if self._beenden_wenn_ungenutzt(messung):
                    return
        finally:
            fertig.set()
            prozess.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                prozess.wait(timeout=1)
            prozess.stdout.close()

    def _ungenutzt(self, messung: _Messung) -> bool:
        """Zeigt keine Kachel diese Messung mehr? Ändert nichts."""
        jetzt = time.monotonic()
        with self._lock:
            return self._aus or not any(v[0] > jetzt for v in messung.kacheln.values())

    def _waechter(self, messung: _Messung, prozess, fertig: threading.Event) -> None:
        """Beendet ``parec``, sobald niemand mehr hinsieht.

        Das Lesen selbst kann das nicht: Es wartet auf Daten, die von einem
        ruhenden Ausgang nicht kommen. Endet der Prozess, kehrt es mit
        leerem Ergebnis zurück, und die Messung räumt sich auf.
        """
        while not fertig.wait(WAECHTER_S):
            if self._ungenutzt(messung):
                with contextlib.suppress(OSError):
                    prozess.terminate()
                return

    def _melde_aenderung(self, messung: _Messung, jetzt: float) -> None:
        with self._lock:
            werte = (
                anzeige_wert(messung.traegheit.pegel_db),
                anzeige_wert(messung.traegheit.spitze_db),
            )
            veraendert = any(
                abs(neu - alt) >= SCHWELLE for neu, alt in zip(werte, messung.gezeichnet)
            )
            if not veraendert or jetzt - messung.gezeichnet_um < 1 / BILDER_JE_S:
                return
            messung.gezeichnet = werte
            messung.gezeichnet_um = jetzt
            kontexte = [ctx for _, ctx in messung.kacheln.values()]
        for ctx in kontexte:
            self._neu_zeichnen(ctx)
