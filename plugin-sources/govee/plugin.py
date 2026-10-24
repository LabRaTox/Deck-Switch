"""Govee-Lampen vom Deck aus.

Sechs Aktionen: an und aus, Helligkeit, Farbe, Farbtemperatur, Szenen und
eine Taste, die alles auf einmal schaltet. Was ein Gerät kann, sagt Govee
selbst — die Auswahllisten kommen von dort, es wird nichts geraten.

**Womit hier gerechnet wird: mit Grenzen.** Govee zählt Anfragen streng
mit. Der Zustand wird deshalb gebündelt geholt und kurz festgehalten, und
jeder Befehl schreibt sein Ergebnis sofort mit hinein: Wer einschaltet,
sieht die Kachel umspringen, statt zwanzig Sekunden auf die nächste
Abfrage zu warten. ``render`` wartet nie auf das Netz.

**Der Schlüssel gehört dem Benutzer.** Anders als bei Twitch gibt es hier
keine App für alle — jeder holt sich seinen eigenen Schlüssel in der
Govee-Home-App. Er steht in den Plugin-Einstellungen als Passwortfeld,
damit er nicht offen auf dem Bildschirm liegt.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from deckswitch.plugins.base import ActionPlugin

from .govee_api import (
    STANDARD_MODUS,
    GoveeApi,
    GoveeError,
    KeinSchluessel,
    hex_zu_zahl,
    zahl_zu_hex,
    zahl_zu_rgb,
)

log = logging.getLogger(__name__)

ACCENT = "#7c3aed"

#: Wie oft der Hintergrund nachsieht, solange Kacheln sichtbar sind.
AUFFRISCHEN_S = 25.0

FARBE_AN = "#facc15"
FARBE_AUS = "#6b7280"
FARBE_WEG = "#ef4444"

def _kelvin_farbe(kelvin: int) -> str:
    """Ungefähr die Farbe, die eine Temperatur ergibt — für die Kachel.

    Keine Physik, sondern drei Stützstellen und dazwischen gemischt: warm
    (2000 K), neutral (4500 K), kalt (9000 K). Es geht darum, dass man auf
    einen Blick warm von kalt unterscheidet, nicht um Farbmetrik.
    """
    stuetzen = ((2000, (255, 160, 70)), (4500, (255, 235, 215)), (9000, (200, 220, 255)))
    kelvin = max(2000, min(9000, int(kelvin)))
    for (k1, c1), (k2, c2) in zip(stuetzen, stuetzen[1:]):
        if k1 <= kelvin <= k2:
            anteil = (kelvin - k1) / (k2 - k1)
            werte = [round(a + (b - a) * anteil) for a, b in zip(c1, c2)]
            return f"#{werte[0]:02x}{werte[1]:02x}{werte[2]:02x}"
    return "#ffffff"


class GoveePlugin(ActionPlugin):
    def __init__(self, manifest, services) -> None:
        super().__init__(manifest, services)
        self.api = GoveeApi(modus=STANDARD_MODUS)
        self._fehler = ""
        self._auffrischer: asyncio.Task | None = None
        self._holt = asyncio.Lock()
        self._zuletzt = 0.0
        #: Welche Geräte gerade auf einer sichtbaren Kachel liegen, mit dem
        #: Zeitpunkt des letzten Ticks. Nur die werden abgefragt, Govee zählt
        #: je Gerät mit. Wer länger nicht zu sehen war, fällt heraus.
        self._gefragt: dict[str, float] = {}
        #: Läuft gerade ein Abruf der Geräteliste für die Statusanzeige?
        self._liste_laedt = False
        self._liste_fehler = ""
        self._liste_versucht = 0.0

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self) -> None:
        self._uebernimm_konfiguration()
        self._auffrischer = asyncio.create_task(self._schleife(), name="govee-auffrischen")

    async def teardown(self) -> None:
        if self._auffrischer is not None:
            self._auffrischer.cancel()
            try:
                await self._auffrischer
            except asyncio.CancelledError:
                pass
            self._auffrischer = None

    def on_plugin_config_changed(self, config: dict[str, Any]) -> None:
        self._uebernimm_konfiguration()

    def _uebernimm_konfiguration(self) -> None:
        self.api.schluessel = str(self.plugin_config.get("api_key") or "").strip()
        # Ein Wechsel der Schnittstelle ändert, was die Geräte melden — der
        # Zwischenspeicher muss deshalb weg, nicht nur die Einstellung.
        self.api.modus = str(self.plugin_config.get("api") or "alt")
        self.api.vergiss()
        self.fehler = "" if self.api.schluessel else "plugin.schluessel_fehlt"

    @property
    def fehler(self) -> str:
        """Warum das Plugin nicht arbeiten kann, in der aktuellen Sprache."""
        return self.t(self._fehler) if self._fehler else ""

    @fehler.setter
    def fehler(self, schluessel: str) -> None:
        self._fehler = schluessel

    def get_status(self) -> dict[str, Any] | None:
        if self.fehler:
            return {"connected": False, "detail": self.fehler}
        # Nur aus dem Gemerkten: Dieser Hook läuft im Event-Loop und darf
        # nicht auf Govee warten. Fehlt die Liste, wird sie nebenher geholt.
        geraete = self.api.bekannte_geraete()
        if geraete is None:
            self._liste_nachholen()
            if self._liste_fehler:
                return {"connected": False, "detail": self._liste_fehler}
            return {"connected": False, "detail": self.t("status.laedt")}
        anzahl = len(geraete)
        if not anzahl:
            return {"connected": True, "detail": self.t("status.kein_geraet")}
        return {"connected": True, "detail": self.t("status.geraete", anzahl=anzahl)}

    def _liste_nachholen(self) -> None:
        """Holt die Geräteliste im Hintergrund und meldet danach den Status neu."""
        if self._liste_laedt or time.monotonic() - self._liste_versucht < AUFFRISCHEN_S:
            return
        self._liste_laedt = True
        self._liste_versucht = time.monotonic()

        async def holen():
            try:
                await asyncio.to_thread(self.api.geraete)
                self._liste_fehler = ""
            except GoveeError as exc:
                self._liste_fehler = str(exc)
            finally:
                self._liste_laedt = False
            self.services.runtime.publish_plugin_status(self.manifest.id)

        self.run_async(holen())

    # -- Hintergrund -------------------------------------------------------

    async def _schleife(self) -> None:
        while True:
            await asyncio.sleep(AUFFRISCHEN_S)
            if not self.api.schluessel or not self._sichtbar():
                continue
            try:
                await self._hole_stand()
            except Exception as exc:  # noqa: BLE001 — die Schleife darf nie sterben
                log.debug("Govee: Auffrischen fehlgeschlagen: %s", exc)

    async def _hole_stand(self) -> None:
        if self._holt.locked():
            return
        async with self._holt:
            gefragt = self._sichtbar()

            def arbeit():
                for schluessel in gefragt:
                    geraet = self.api.geraet(schluessel)
                    if geraet is not None:
                        self.api.zustand(geraet, erneut=True)

            # Auch ein Fehlschlag zählt als Versuch. Sonst fragte jeder Tick
            # sofort wieder nach und brauchte das Kontingent bei Govee auf.
            self._zuletzt = time.monotonic()
            try:
                await asyncio.to_thread(arbeit)
            except KeinSchluessel:
                return
            except GoveeError as exc:
                log.debug("Govee: %s", exc)
                return
            self.services.runtime.request_redraw()

    # -- Auswahllisten -----------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        context = context or {}
        if not self.api.schluessel:
            return []
        try:
            if source == "geraete":
                return [
                    {"value": g.schluessel, "label": f"{g.name} ({g.model})"}
                    for g in self.api.geraete()
                ]
            if source == "szenen":
                if not self.api.nutzt_neue:
                    return [{"value": "", "label": self.t("optionen.nur_neue_schnittstelle")}]
                geraet = self.api.geraet(str(context.get("device") or ""))
                if geraet is None:
                    return []
                return [{"value": name, "label": name} for name in sorted(geraet.szenen)]
        except GoveeError as exc:
            self.notify_error(f"Govee: {exc}")
        return []

    # -- Bedienung ---------------------------------------------------------

    async def on_key_down(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def on_dial_push(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def _ausfuehren(self, action_id, settings, ctx) -> None:
        if self.fehler:
            self.notify_error(self.fehler)
            return
        try:
            await asyncio.to_thread(self._arbeit, action_id, dict(settings))
        except GoveeError as exc:
            self.notify_error(f"{action_id}: {exc}")
        ctx.request_redraw()

    def _arbeit(self, action_id: str, settings: dict[str, Any]) -> None:
        if action_id == "all":
            self._alle(str(settings.get("mode") or "off"))
            return

        geraet = self._geraet(settings)

        if action_id == "power":
            modus = str(settings.get("mode") or "toggle")
            if modus == "on":
                self.api.schalte(geraet, True)
            elif modus == "off":
                self.api.schalte(geraet, False)
            else:
                self.api.schalte(geraet, not bool(self.api.zustand(geraet).an))

        elif action_id == "brightness":
            self.api.helligkeit(geraet, int(settings.get("value") or 60))

        elif action_id == "color":
            self.api.farbe(geraet, hex_zu_zahl(str(settings.get("color") or "#ffffff")))

        elif action_id == "temperature":
            self.api.temperatur(geraet, int(settings.get("kelvin") or 4000))

        elif action_id == "scene":
            name = str(settings.get("scene") or "").strip()
            if not name:
                raise GoveeError(self.t("aktion.keine_szene"))
            self.api.szene(geraet, name)

    def _alle(self, modus: str) -> None:
        geraete = self.api.geraete()
        if not geraete:
            raise GoveeError(self.t("aktion.keine_geraete"))
        if modus == "toggle":
            # Umschalten heißt hier: Brennt irgendwo Licht, geht alles aus.
            # Die andere Lesart — jedes Gerät für sich umschalten — ergäbe
            # ein halb erleuchtetes Zimmer, und danach weiß niemand mehr,
            # was der nächste Druck tut.
            an = any(bool(self.api.zustand(g).an) for g in geraete)
            ziel = not an
        else:
            ziel = modus == "on"
        fehler: list[str] = []
        for geraet in geraete:
            try:
                self.api.schalte(geraet, ziel)
            except GoveeError as exc:
                fehler.append(f"{geraet.name}: {exc}")
        if fehler:
            raise GoveeError("; ".join(fehler))

    def _geraet(self, settings: dict[str, Any]):
        schluessel = str(settings.get("device") or "").strip()
        if not schluessel:
            raise GoveeError(self.t("aktion.kein_geraet"))
        geraet = self.api.geraet(schluessel)
        if geraet is None:
            raise GoveeError(self.t("aktion.geraet_weg"))
        return geraet

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        if self.fehler or action_id not in ("brightness", "temperature", "power"):
            return

        def arbeit():
            geraet = self._geraet(settings)
            stand = self.api.zustand(geraet)
            if action_id == "temperature":
                jetzt = stand.temperatur or int(settings.get("kelvin") or 4000)
                self.api.temperatur(geraet, jetzt + delta * 100)
                return
            schritt = max(1, int(settings.get("step") or 5))
            jetzt = stand.helligkeit if stand.helligkeit is not None else 50
            self.api.helligkeit(geraet, jetzt + delta * schritt)

        try:
            await asyncio.to_thread(arbeit)
        except GoveeError as exc:
            self.notify_error(f"{action_id}: {exc}")
        ctx.request_redraw()

    # -- Anzeige -----------------------------------------------------------

    def _sichtbar(self) -> list[str]:
        """Geräte, deren Kachel in letzter Zeit einen Tick bekommen hat."""
        grenze = time.monotonic() - 2 * AUFFRISCHEN_S
        for schluessel in [s for s, zeit in self._gefragt.items() if zeit < grenze]:
            self._gefragt.pop(schluessel, None)
        return sorted(self._gefragt)

    async def on_tick(self, action_id, settings, ctx):
        """Merkt sich, welche Geräte sichtbar sind, und frischt sie auf."""
        schluessel = str(settings.get("device") or "").strip()
        if schluessel:
            self._gefragt[schluessel] = time.monotonic()
        if not self.api.schluessel:
            return
        if time.monotonic() - self._zuletzt >= AUFFRISCHEN_S:
            await self._hole_stand()

    def _stand(self, settings: dict[str, Any]):
        """Der bekannte Zustand — ohne zu fragen. ``None``, wenn unbekannt."""
        schluessel = str(settings.get("device") or "").strip()
        if not schluessel or not self.api.schluessel:
            return None, None
        # Nur in der gemerkten Liste suchen: ``geraet()`` holte nach Ablauf
        # des Zwischenspeichers die Liste neu, und das mitten im Zeichnen.
        geraet = next((g for g in self.api.bekannte_geraete() or []
                       if g.schluessel == schluessel), None)
        if geraet is None:
            return None, None
        gemerkt = self.api._zustand.get(geraet.schluessel)
        return geraet, (gemerkt[1] if gemerkt else None)

    def get_state(self, action_id, settings, ctx):
        if action_id not in ("power", "all"):
            return None
        if action_id == "all":
            return None
        _, stand = self._stand(settings)
        if stand is None:
            return None
        if not stand.erreichbar:
            return "weg"
        return "an" if stand.an else "aus"

    def render(self, action_id, settings, ctx):
        if action_id in ("scene", "all"):
            return super().render(action_id, settings, ctx)

        render = self.services.render
        geraet, stand = self._stand(settings)
        breite, hoehe = ctx.size

        # Der Rand trägt die Farbe: Bei „Farbe" die eingestellte, bei
        # „Weiß" die ungefähre Temperaturfarbe, sonst an oder aus.
        if action_id == "color":
            rand = str(settings.get("color") or "#ffffff")
        elif action_id == "temperature":
            rand = _kelvin_farbe(int(settings.get("kelvin") or 4000))
        elif stand is None:
            rand = FARBE_AUS
        elif not stand.erreichbar:
            rand = FARBE_WEG
        elif stand.an:
            rand = zahl_zu_hex(stand.farbe) if stand.farbe else FARBE_AN
        else:
            rand = FARBE_AUS

        bild = render.background(ctx.size, ctx.appearance, accent=ACCENT,
                                 frame_time=ctx.frame_time)

        if not self.api.schluessel:
            gross, klein = "---", self.t("kachel.kein_schluessel")
        elif not str(settings.get("device") or "").strip():
            gross, klein = "---", self.t("kachel.kein_geraet")
        elif action_id == "brightness":
            wenn_unbekannt = int(settings.get("value") or 60)
            wert = stand.helligkeit if stand and stand.helligkeit is not None else wenn_unbekannt
            gross, klein = f"{wert}%", geraet.name if geraet else ""
        elif action_id == "temperature":
            wert = stand.temperatur if stand and stand.temperatur else int(
                settings.get("kelvin") or 4000)
            gross, klein = f"{wert}K", geraet.name if geraet else ""
        elif action_id == "color":
            rot, gruen, blau = zahl_zu_rgb(hex_zu_zahl(rand))
            gross, klein = "", f"{rot}·{gruen}·{blau}"
        elif stand is None:
            gross, klein = "…", geraet.name if geraet else ""
        elif not stand.erreichbar:
            gross, klein = "!", self.t("kachel.weg")
        elif stand.an:
            gross = f"{stand.helligkeit}%" if stand.helligkeit is not None \
                else self.t("kachel.an")
            klein = geraet.name if geraet else ""
        else:
            gross, klein = self.t("kachel.aus"), geraet.name if geraet else ""

        beschriftung = ctx.appearance.label_text or ""

        if ctx.input_type == "dial":
            render.draw_text_at(bild, beschriftung or (geraet.name if geraet else "Govee"),
                                x=10, y=8, size=13, color="#c7c7d1", max_width=breite - 20)
            if gross:
                render.draw_text_at(bild, gross, x=10, y=30, size=38, bold=True,
                                    color=ctx.appearance.label_color)
            if action_id == "brightness" and stand and stand.helligkeit is not None:
                render.draw_bar(bild, stand.helligkeit / 100, color=rand,
                                box=(10, hoehe - 16, breite - 10, hoehe - 8))
            return bild

        render.draw_badge(bild, color=rand, width=max(3, min(ctx.size) // 20))
        if gross:
            groesse = 28 if len(gross) <= 4 else 22
            render.draw_text(bild, gross, y=hoehe // 2 - groesse // 2 - 4, size=groesse,
                             bold=True, color=ctx.appearance.label_color)
        # Beides, nicht eines von beiden: Die Beschriftung sagt, welche Lampe
        # gemeint ist, die kleine Zeile, was sie gerade tut. Mit „entweder
        # oder" stand auf einer benannten Taste nur ein Strich.
        if beschriftung:
            render.draw_text(bild, beschriftung, y=10, size=12, color="#9ca3af")
        if klein:
            render.draw_text(bild, klein, y=hoehe - 26, size=12, color="#c7c7d1")
        return bild
