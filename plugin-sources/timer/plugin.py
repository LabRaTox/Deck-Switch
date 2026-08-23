"""Countdown, Stoppuhr und Wecker.

Drei Aktionen, ein Prinzip: Jede Belegung führt ihre eigene Uhr. Zwei
Belegungen mit derselben Aktion stören sich nicht — die eine kocht Eier,
die andere misst die Pause.

**Warum ein eigener Wächter und nicht ``on_tick``.** Der Tick erreicht nur
Belegungen auf der Seite, die gerade auf dem Gerät liegt. Ein Timer, den man
startet und dann eine Seite weiterblättert, würde damit nie klingeln. Der
Wächter hier läuft unabhängig von der Anzeige und weckt die Anzeige, wenn
etwas passiert ist.

**Was einen Neustart nicht überlebt:** die laufenden Uhren und die am Dial
gedrehten Zeiten. Ein Plugin kann seine Einstellungen nicht selbst
zurückschreiben, und einen halb abgelaufenen Timer über einen Neustart zu
retten wäre mehr Versprechen als Nutzen. Was im Formular steht, gilt nach
dem Neustart wieder.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from deckswitch.plugins.base import ActionPlugin

#: Wie oft der Wächter nachsieht. Feiner als eine Sekunde, damit der Ton
#: nicht bis zu einer Sekunde zu spät kommt; grob genug, um im Leerlauf
#: nichts zu kosten — ohne laufende Uhr tut die Schleife gar nichts.
WACHINTERVALL = 0.25

#: Der mitgelieferte Klang.
KLINGEL = Path(__file__).resolve().parent / "sounds" / "klingel.wav"

#: Farben der Anzeige. Bewusst nicht aus der Akzentfarbe abgeleitet: Ein
#: laufender und ein abgelaufener Timer müssen sich auf einen Blick
#: unterscheiden, auch aus zwei Metern Entfernung.
FARBE_LAEUFT = "#f59e0b"
FARBE_PAUSE = "#9ca3af"
FARBE_FERTIG = "#ef4444"
FARBE_BEREIT = "#6b7280"

#: Die wenigen Wörter, die auf einer Kachel stehen. Ein Plugin bekommt vom
#: Rahmenwerk keine Übersetzung mitgeliefert; für sechs Begriffe lohnt kein
#: Apparat, aber deutsche Wörter in einer englischen Oberfläche fallen auf.
WOERTER = {
    "de": {"paused": "pausiert", "done": "fertig", "off": "aus",
           "ringing": "klingelt", "now": "jetzt", "in": "in",
           "day": "Tag", "days": "Tagen", "min": "min"},
    "en": {"paused": "paused", "done": "done", "off": "off",
           "ringing": "ringing", "now": "now", "in": "in",
           "day": "day", "days": "days", "min": "min"},
}

#: Der Rahmen um die Stoppuhr. Sie hat kein Ziel und deshalb auch keinen
#: Balken, an dem man ihren Zustand ablesen könnte — zwei Farben am Rand
#: sagen aus der Entfernung mehr als eine Zeile Text.
RAHMEN_LAEUFT = "#22c55e"
RAHMEN_PAUSE = "#f59e0b"


def zu_sekunden(text: Any, standard: int = 0) -> int:
    """``"5:00"``, ``"90"``, ``"1h30m"`` → Sekunden.

    Absichtlich großzügig: Wer eine Dauer eintippt, denkt nicht daran, in
    welchem Format das erwartet wird. Alles, was sich eindeutig lesen lässt,
    wird gelesen; alles andere fällt auf den Standard zurück, statt die
    Belegung mit einer Fehlermeldung lahmzulegen.
    """
    if isinstance(text, (int, float)):
        return max(0, int(text))
    roh = str(text or "").strip().lower()
    if not roh:
        return standard

    if ":" in roh:
        teile = roh.split(":")
        if len(teile) > 3 or not all(t.strip().isdigit() or not t.strip() for t in teile):
            return standard
        zahlen = [int(t) if t.strip() else 0 for t in teile]
        # mm:ss oder hh:mm:ss — die letzte Zahl sind immer Sekunden.
        while len(zahlen) < 3:
            zahlen.insert(0, 0)
        stunden, minuten, sekunden = zahlen
        return max(0, stunden * 3600 + minuten * 60 + sekunden)

    if roh.isdigit():
        return max(0, int(roh))

    treffer = re.findall(r"(\d+)\s*([hms])", roh)
    if not treffer:
        return standard
    faktor = {"h": 3600, "m": 60, "s": 1}
    return max(0, sum(int(zahl) * faktor[einheit] for zahl, einheit in treffer))


def als_text(sekunden: float, *, aufrunden: bool = True) -> str:
    """Sekunden als ``mm:ss``, ab einer Stunde als ``h:mm:ss``.

    Aufgerundet, weil ein Countdown sonst die letzte Sekunde als ``00:00``
    zeigt, während er noch läuft — beim Kochen zählt genau die.
    """
    gesamt = int(sekunden + 0.999) if aufrunden else int(sekunden)
    gesamt = max(0, gesamt)
    stunden, rest = divmod(gesamt, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}:{minuten:02d}:{sek:02d}"
    return f"{minuten:02d}:{sek:02d}"


def uhrzeit_zu_minuten(text: Any, standard: int = 7 * 60) -> int:
    """``"07:30"`` → Minuten seit Mitternacht."""
    roh = str(text or "").strip()
    treffer = re.fullmatch(r"(\d{1,2})[:.]?(\d{2})?", roh)
    if not treffer:
        return standard
    stunde = int(treffer.group(1))
    minute = int(treffer.group(2) or 0)
    if stunde > 23 or minute > 59:
        return standard
    return stunde * 60 + minute


def minuten_als_uhrzeit(minuten: int) -> str:
    minuten %= 24 * 60
    return f"{minuten // 60:02d}:{minuten % 60:02d}"


@dataclass
class Lauf:
    """Eine Uhr, die zu genau einer Belegung gehört."""

    laeuft: bool = False
    #: Zeitpunkt des letzten Starts (``time.monotonic``).
    seit: float = 0.0
    #: Was vor der letzten Pause schon zusammengekommen ist.
    gesammelt: float = 0.0
    #: Soll-Dauer des Countdowns in Sekunden. Für die Stoppuhr belanglos.
    dauer: int = 0
    #: Abgelaufen und noch nicht quittiert — die Kachel blinkt.
    fertig: bool = False
    #: Am Dial gedrehte Werte, die die Einstellung überstimmen.
    eigene_dauer: int | None = None
    eigene_uhrzeit: int | None = None
    #: Wecker: scharf oder nicht; und wann er zuletzt geklingelt hat, damit
    #: er in derselben Minute nicht zweimal losgeht.
    scharf: bool | None = None
    zuletzt_geklingelt: str = ""
    #: Ein einmaliger Wecker, der geklingelt hat, ist aufgebraucht. Das ist
    #: etwas anderes als „von Hand ausgeschaltet": Er zeigt dann gar nichts
    #: mehr an, statt eine Restzeit zu behaupten, die es nicht gibt.
    verbraucht: bool = False

    def verstrichen(self) -> float:
        if self.laeuft:
            return self.gesammelt + (time.monotonic() - self.seit)
        return self.gesammelt

    def rest(self) -> float:
        return max(0.0, self.dauer - self.verstrichen())

    def starte(self) -> None:
        if not self.laeuft:
            self.seit = time.monotonic()
            self.laeuft = True

    def halte_an(self) -> None:
        if self.laeuft:
            self.gesammelt = self.verstrichen()
            self.laeuft = False

    def zurueck(self) -> None:
        self.laeuft = False
        self.gesammelt = 0.0
        self.fertig = False


class TimerPlugin(ActionPlugin):
    def __init__(self, manifest, services) -> None:
        super().__init__(manifest, services)
        #: Eine Uhr je Belegung, angesprochen über ``ctx.key``.
        self._laeufe: dict[str, Lauf] = {}
        #: Was der Wächter braucht, um eine Belegung zu bedienen, ohne dass
        #: gerade jemand hinsieht: die Einstellungen der letzten Berührung.
        self._bekannt: dict[str, tuple[str, dict[str, Any]]] = {}
        self._waechter: asyncio.Task | None = None
        #: Zuletzt gezeigte Sekunde je Belegung — verhindert, dass die
        #: Anzeige viermal je Sekunde neu gezeichnet wird.
        self._gezeigt: dict[str, str] = {}

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self) -> None:
        self._waechter = asyncio.create_task(self._wache(), name="timer-wache")

    async def teardown(self) -> None:
        if self._waechter is not None:
            self._waechter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._waechter
            self._waechter = None
        for schluessel in list(self._laeufe):
            self.services.sound.stop(schluessel)
        self._laeufe.clear()
        self._bekannt.clear()

    async def _wache(self) -> None:
        """Sieht nach, ob eine Uhr abgelaufen ist oder ein Wecker fällig."""
        while True:
            await asyncio.sleep(WACHINTERVALL)
            try:
                if self._runde():
                    self.services.runtime.request_redraw()
            except Exception as exc:  # noqa: BLE001 — der Wächter darf nie sterben
                self.notify_error(f"Timer: {exc}")

    def _runde(self) -> bool:
        """Eine Prüfrunde. Liefert ``True``, wenn sich etwas getan hat."""
        etwas_passiert = False
        for schluessel, lauf in list(self._laeufe.items()):
            aktion, einstellungen = self._bekannt.get(schluessel, ("", {}))
            if aktion == "countdown":
                if lauf.laeuft and not lauf.fertig and lauf.rest() <= 0:
                    lauf.laeuft = False
                    lauf.gesammelt = lauf.dauer
                    lauf.fertig = True
                    self._klingle(schluessel, einstellungen,
                                  standard_wiederholung=False)
                    etwas_passiert = True
            elif aktion == "alarm":
                if self._wecker_faellig(lauf, einstellungen):
                    lauf.fertig = True
                    lauf.zuletzt_geklingelt = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if str(einstellungen.get("days") or "daily") == "once":
                        lauf.verbraucht = True
                    self._klingle(schluessel, einstellungen,
                                  standard_wiederholung=True)
                    etwas_passiert = True
        return etwas_passiert

    # -- Klingeln ----------------------------------------------------------

    def _klingle(self, schluessel: str, einstellungen: dict[str, Any],
                 *, standard_wiederholung: bool) -> None:
        """Spielt den Ton — auf Wunsch so lange, bis jemand drückt.

        Ein Wecker, der einmal klingelt und dann schweigt, weckt niemanden;
        ein Küchentimer, der nicht aufhört, nervt. Deshalb dieselbe Technik,
        aber verschiedene Vorgaben.
        """
        wahl = str(einstellungen.get("sound") or "bell")
        if wahl == "none":
            return
        if wahl == "file":
            pfad = str(einstellungen.get("sound_file") or "").strip()
            if not pfad:
                self.notify_error("Timer: keine Audiodatei eingestellt")
                return
        else:
            pfad = str(KLINGEL)
        wiederholen = bool(einstellungen.get("repeat", standard_wiederholung))
        try:
            self.services.sound.play(
                pfad, owner=schluessel, volume=int(einstellungen.get("volume") or 80),
                loop=wiederholen,
            )
        except Exception as exc:  # noqa: BLE001 — ohne Ton läuft der Timer weiter
            self.notify_error(f"Timer: {exc}")

    # -- Bedienung ---------------------------------------------------------

    def on_key_down(self, action_id, settings, ctx):
        self._druck(action_id, settings, ctx)

    def on_dial_push(self, action_id, settings, ctx):
        self._druck(action_id, settings, ctx)

    def _druck(self, action_id, settings, ctx) -> None:
        lauf = self._hole(action_id, settings, ctx)

        # Was klingelt, wird als Erstes still. Alles andere wäre zynisch:
        # Man drückt auf einen Wecker, um ihn abzustellen.
        if lauf.fertig:
            self._quittiere(ctx.key, lauf)
            ctx.request_redraw()
            return

        if action_id == "alarm":
            if lauf.verbraucht:
                # Ein aufgebrauchter Einmal-Wecker wird durch den Druck
                # wieder scharf — sonst wäre die Taste danach tot.
                lauf.verbraucht = False
                lauf.scharf = True
            else:
                lauf.scharf = not self._scharf(lauf, settings)
            ctx.request_redraw()
            return

        wahl = str(settings.get("on_press") or "start_pause")
        if wahl == "reset":
            lauf.zurueck()
        elif wahl == "restart":
            lauf.zurueck()
            lauf.starte()
        elif lauf.laeuft:
            lauf.halte_an()
        else:
            lauf.starte()
        ctx.request_redraw()

    def _quittiere(self, schluessel: str, lauf: Lauf) -> None:
        lauf.fertig = False
        lauf.zurueck()
        self.services.sound.stop(schluessel)

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        lauf = self._hole(action_id, settings, ctx)

        if action_id == "alarm":
            jetzt = self._weckzeit(lauf, settings)
            lauf.eigene_uhrzeit = (jetzt + delta * 5) % (24 * 60)
            ctx.request_redraw()
            return

        if action_id == "stopwatch":
            # An einer Stoppuhr gibt es nichts zu stellen; Drehen setzt sie
            # zurück, solange sie nicht läuft. Das ist die einzige sinnvolle
            # Bedeutung, die eine Drehung hier haben kann.
            if not lauf.laeuft:
                lauf.zurueck()
                ctx.request_redraw()
            return

        schritt = max(1, int(settings.get("step") or 30))
        neu = max(0, self._solldauer(lauf, settings) + delta * schritt)
        lauf.eigene_dauer = neu
        lauf.dauer = neu
        # Läuft die Uhr schon, verschiebt sich damit das Ziel — genau wie an
        # einer Mikrowelle, an der man während des Laufs nachlegt.
        if lauf.verstrichen() >= neu and lauf.laeuft:
            lauf.gesammelt = max(0.0, neu - 0.1)
            lauf.seit = time.monotonic()
        ctx.request_redraw()

    def on_tick(self, action_id, settings, ctx):
        """Hält die sichtbare Anzeige aktuell — aber nur, wenn nötig."""
        lauf = self._hole(action_id, settings, ctx)
        text = self._anzeige(action_id, settings, lauf)
        if self._gezeigt.get(ctx.key) != text:
            self._gezeigt[ctx.key] = text
            ctx.request_redraw()

    # -- Zustand einer Belegung -------------------------------------------

    def _hole(self, action_id, settings, ctx) -> Lauf:
        """Die Uhr dieser Belegung, notfalls neu angelegt."""
        lauf = self._laeufe.get(ctx.key)
        if lauf is None:
            lauf = Lauf(dauer=zu_sekunden(settings.get("duration"), 300))
            self._laeufe[ctx.key] = lauf
        # Der Wächter sieht keine Kontexte. Damit er weiß, was zu tun ist,
        # merkt sich jede Berührung Aktion und Einstellungen.
        self._bekannt[ctx.key] = (action_id, dict(settings))
        if action_id == "countdown" and lauf.eigene_dauer is None:
            # Wer die Dauer im Formular ändert, will sie auch sehen —
            # solange am Dial nichts anderes gedreht wurde.
            neu = zu_sekunden(settings.get("duration"), 300)
            if neu != lauf.dauer and not lauf.laeuft and not lauf.fertig:
                lauf.dauer = neu
        return lauf

    def _solldauer(self, lauf: Lauf, settings: dict[str, Any]) -> int:
        if lauf.eigene_dauer is not None:
            return lauf.eigene_dauer
        return zu_sekunden(settings.get("duration"), 300)

    def _weckzeit(self, lauf: Lauf, settings: dict[str, Any]) -> int:
        if lauf.eigene_uhrzeit is not None:
            return lauf.eigene_uhrzeit
        return uhrzeit_zu_minuten(settings.get("time"))

    def _scharf(self, lauf: Lauf, settings: dict[str, Any]) -> bool:
        if lauf.scharf is not None:
            return lauf.scharf
        return bool(settings.get("armed", True))

    @staticmethod
    def _tag_passt(tage: str, wochentag: int) -> bool:
        """``wochentag`` nach Python-Zählung: 0 ist Montag, 6 ist Sonntag."""
        if tage == "weekdays":
            return wochentag < 5
        if tage == "weekend":
            return wochentag >= 5
        return True

    def _naechster_termin(
        self, lauf: Lauf, settings: dict[str, Any], jetzt: datetime | None = None
    ) -> datetime | None:
        """Wann es das nächste Mal klingelt — ``None``, wenn gar nicht mehr.

        Vorher rechnete die Anzeige nur die Differenz innerhalb eines Tages
        aus. Bei „Montag bis Freitag" stand deshalb am Samstag „in 8 h",
        obwohl bis zum nächsten Klingeln zwei Tage vergehen. Hier wird der
        Termin gesucht, statt die Uhrzeit zu verrechnen.
        """
        if lauf.verbraucht or not self._scharf(lauf, settings):
            return None

        jetzt = jetzt or datetime.now()
        minuten = self._weckzeit(lauf, settings)
        heute = jetzt.replace(hour=minuten // 60, minute=minuten % 60,
                              second=0, microsecond=0)
        tage = str(settings.get("days") or "daily")
        # Acht Tage reichen: Bei „Wochenende" liegen höchstens sieben
        # zwischen zwei Terminen.
        for versatz in range(8):
            kandidat = heute + timedelta(days=versatz)
            if kandidat <= jetzt:
                continue
            if self._tag_passt(tage, kandidat.weekday()):
                return kandidat
        return None

    def _wecker_faellig(self, lauf: Lauf, settings: dict[str, Any]) -> bool:
        if lauf.fertig or lauf.verbraucht or not self._scharf(lauf, settings):
            return False
        jetzt = datetime.now()
        stempel = jetzt.strftime("%Y-%m-%d %H:%M")
        if lauf.zuletzt_geklingelt == stempel:
            return False
        if jetzt.hour * 60 + jetzt.minute != self._weckzeit(lauf, settings):
            return False
        return self._tag_passt(str(settings.get("days") or "daily"), jetzt.weekday())

    # -- Darstellung -------------------------------------------------------

    def get_state(self, action_id, settings, ctx):
        lauf = self._laeufe.get(ctx.key)
        if action_id == "alarm":
            if lauf is not None and lauf.fertig:
                return "klingelt"
            if lauf is not None and not self._scharf(lauf, settings):
                return "aus"
            return "scharf" if settings.get("armed", True) or (
                lauf is not None and lauf.scharf) else "aus"
        if lauf is None:
            return "bereit"
        if lauf.fertig:
            return "abgelaufen"
        if lauf.laeuft:
            return "laeuft"
        if lauf.verstrichen() > 0:
            return "pausiert"
        return "bereit"

    def _wort(self, name: str) -> str:
        try:
            sprache = self.services.config.app.language
        except AttributeError:
            sprache = "de"
        return WOERTER.get(sprache, WOERTER["de"]).get(name, name)

    def _restzeit(self, offen: timedelta) -> str:
        """„in 12 min", „in 3 h 05 min", „in 2 Tagen 4 h"."""
        sekunden = max(0, int(offen.total_seconds()))
        if sekunden < 60:
            return self._wort("now")
        minuten = sekunden // 60
        tage, rest = divmod(minuten, 24 * 60)
        stunden, minuten_rest = divmod(rest, 60)
        wort = self._wort("in")
        if tage:
            einheit = self._wort("day") if tage == 1 else self._wort("days")
            return f"{wort} {tage} {einheit} {stunden} h"
        if stunden:
            return f"{wort} {stunden} h {minuten_rest:02d} {self._wort('min')}"
        return f"{wort} {minuten_rest} {self._wort('min')}"

    def _anzeige(self, action_id, settings, lauf: Lauf) -> str:
        """Der große Text auf der Kachel."""
        if action_id == "alarm":
            return minuten_als_uhrzeit(self._weckzeit(lauf, settings))
        if action_id == "stopwatch":
            return als_text(lauf.verstrichen(), aufrunden=False)
        if lauf.fertig:
            return als_text(0)
        if lauf.laeuft or lauf.verstrichen() > 0:
            return als_text(lauf.rest())
        return als_text(self._solldauer(lauf, settings))

    def _farbe(self, action_id, settings, lauf: Lauf) -> str:
        if lauf.fertig:
            return FARBE_FERTIG
        if action_id == "alarm":
            return FARBE_LAEUFT if self._scharf(lauf, settings) else FARBE_BEREIT
        if lauf.laeuft:
            return FARBE_LAEUFT
        if lauf.verstrichen() > 0:
            return FARBE_PAUSE
        return FARBE_BEREIT

    #: Fenster, über das der Balken eines Weckers läuft. Ein Balken über eine
    #: ganze Woche stünde tagelang fast leer und sagte nichts; über den
    #: letzten Tag zeigt er, dass es gleich so weit ist.
    WECKER_FENSTER = timedelta(hours=24)

    def _fortschritt(self, action_id, settings, lauf: Lauf) -> float | None:
        """0…1 für den Balken, ``None`` wo er nichts zu sagen hätte."""
        if action_id == "countdown":
            soll = max(1, self._solldauer(lauf, settings))
            if lauf.fertig:
                return 1.0
            return min(1.0, lauf.verstrichen() / soll)
        if action_id == "alarm":
            if lauf.fertig:
                return 1.0
            termin = self._naechster_termin(lauf, settings)
            if termin is None:
                return None
            offen = termin - datetime.now()
            if offen > self.WECKER_FENSTER:
                return 0.0
            return 1.0 - offen / self.WECKER_FENSTER
        return None

    def _zusatz(self, action_id, settings, lauf: Lauf) -> str:
        """Die kleine Zeile unter der Zeit."""
        if action_id == "alarm":
            if lauf.fertig:
                return self._wort("ringing")
            # Ein einmaliger Wecker, der geklingelt hat, ist vorbei. Dort
            # noch „in 23 h" zu schreiben, hieße den nächsten Tag zu
            # versprechen — und den gibt es bei „einmalig" nicht.
            if lauf.verbraucht:
                return ""
            if not self._scharf(lauf, settings):
                return self._wort("off")
            termin = self._naechster_termin(lauf, settings)
            if termin is None:
                return ""
            return self._restzeit(termin - datetime.now())
        if lauf.fertig:
            return self._wort("done")
        if lauf.laeuft:
            return ""
        if lauf.verstrichen() > 0:
            return self._wort("paused")
        return ""

    def render(self, action_id, settings, ctx):
        lauf = self._hole(action_id, settings, ctx)
        render = self.services.render
        farbe = self._farbe(action_id, settings, lauf)
        bild = render.background(ctx.size, ctx.appearance, accent=farbe,
                                 frame_time=ctx.frame_time)

        rahmenbreite = max(3, min(ctx.size) // 24)

        # Abgelaufen: Der Rahmen blinkt im Sekundentakt. Ohne laufende
        # Animation bleibt er stehen und ist trotzdem zu sehen.
        if lauf.fertig and int(ctx.frame_time * 2) % 2 == 0:
            render.draw_badge(bild, color=FARBE_FERTIG, width=rahmenbreite)
        elif action_id == "stopwatch" and lauf.laeuft:
            render.draw_badge(bild, color=RAHMEN_LAEUFT, width=rahmenbreite)
        elif action_id == "stopwatch" and lauf.verstrichen() > 0:
            render.draw_badge(bild, color=RAHMEN_PAUSE, width=rahmenbreite)

        zeit = self._anzeige(action_id, settings, lauf)
        zusatz = self._zusatz(action_id, settings, lauf)
        breite, hoehe = ctx.size
        beschriftung = ctx.appearance.label_text or ""

        if ctx.input_type == "dial":
            # Kopfzeile mit zwei Enden: links, worum es geht, rechts, wie es
            # steht. Beides in dieselbe Zeile, weil die Zeit darunter die
            # ganze Breite braucht — „in 12 h 19 min" neben einer Uhrzeit
            # überlappte sie sonst.
            render.draw_text_at(bild, beschriftung or self._name(action_id), x=10, y=8,
                                size=13, color="#c7c7d1",
                                max_width=breite - 30 - (len(zusatz) * 7 if zusatz else 0))
            if zusatz:
                render.draw_text_at(bild, zusatz, x=breite - 10, y=8, size=13,
                                    color="#9ca3af", align="right")
            render.draw_text_at(bild, zeit, x=10, y=30, size=40, bold=True,
                                color=ctx.appearance.label_color)
            anteil = self._fortschritt(action_id, settings, lauf)
            if anteil is not None:
                render.draw_bar(bild, anteil, color=farbe,
                                box=(10, hoehe - 16, breite - 10, hoehe - 8))
            return bild

        # Taste: die Zeit trägt die Kachel, alles andere ordnet sich unter.
        groesse = 30 if len(zeit) <= 5 else 24
        render.draw_text(bild, zeit, y=hoehe // 2 - groesse // 2 - 6, size=groesse,
                         bold=True, color=ctx.appearance.label_color)
        if zusatz:
            render.draw_text(bild, zusatz, y=hoehe // 2 + groesse // 2 - 2, size=12,
                             color="#c7c7d1")
        if beschriftung:
            render.draw_text(bild, beschriftung, y=8, size=12, color="#9ca3af")
        anteil = self._fortschritt(action_id, settings, lauf)
        if anteil is not None:
            render.draw_bar(bild, anteil, color=farbe,
                            box=(12, hoehe - 16, breite - 12, hoehe - 9))
        return bild

    @staticmethod
    def _name(action_id: str) -> str:
        return {"countdown": "Timer", "stopwatch": "Stoppuhr", "alarm": "Wecker"}.get(
            action_id, action_id
        )
