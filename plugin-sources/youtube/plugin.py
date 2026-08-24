"""YouTube-Livestream vom Deck aus.

Fünf Aktionen: Zuschauerzahl, Chatnachricht, Werbung, Dashboard, Stream
starten und beenden. Alles über YouTubes Data API v3.

**Was hier anders ist als bei Twitch.** Zwei Dinge, und beide haben Folgen
für die Bedienung:

Erstens braucht jeder eigene Zugangsdaten, weil YouTubes Kontingent je
Google-Projekt gilt und nicht je Benutzer. Eine mitgelieferte Kennung wäre
nach ein paar Dutzend Installationen für alle erschöpft.

Zweitens lässt sich der Stream hier wirklich starten und beenden — anders
als bei Twitch, das dafür keinen Aufruf hat. YouTube kennt Sendungen als
eigene Objekte mit Zuständen, und zwischen denen wird gewechselt. Angelegt
werden muss die Sendung trotzdem vorher in YouTube Studio.

**Womit gerechnet wird: mit Einheiten.** Lesen kostet eine, Schreiben
fünfzig, und der Vorrat ist zehntausend am Tag. ``render`` fragt deshalb
nie selbst, sondern zeichnet aus gespiegelten Werten; geholt wird im
Hintergrund und nur so oft wie eingestellt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any

from deckswitch import paths
from deckswitch.plugins.base import ActionPlugin

from .youtube_api import (
    KeineZugangsdaten,
    NichtAngemeldet,
    Anmeldung,
    YouTubeApi,
    YouTubeError,
)

log = logging.getLogger(__name__)

ACCENT = "#ff0033"

#: Hier liegt das Token — neben der Konfiguration, nur für den Benutzer
#: lesbar. Ohne die Datei muss man sich neu anmelden.
TOKEN_DATEI = paths.CONFIG_DIR / "youtube-token.json"

#: Wie oft der Hintergrund mindestens nachsieht, wenn nichts eingestellt ist.
STANDARD_TAKT_S = 30.0

FARBE_LIVE = "#22c55e"
FARBE_AUS = "#6b7280"

WOERTER = {
    "de": {"offline": "nicht live", "live": "live", "viewers": "Zuschauer",
           "no_login": "nicht verbunden", "no_keys": "keine Zugangsdaten",
           "no_broadcast": "keine Sendung", "ready": "bereit", "ask": "noch mal drücken"},
    "en": {"offline": "not live", "live": "live", "viewers": "viewers",
           "no_login": "not connected", "no_keys": "no credentials",
           "no_broadcast": "no broadcast", "ready": "ready", "ask": "press again"},
}


def _lade_token() -> dict[str, Any]:
    try:
        return json.loads(TOKEN_DATEI.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _schreib_token(daten: dict[str, Any]) -> None:
    TOKEN_DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst schreiben, dann die Rechte setzen, dann tauschen: Zwischen
    # Anlegen und chmod stünde die Datei sonst kurz für alle offen.
    vorlaeufig = TOKEN_DATEI.with_suffix(".neu")
    vorlaeufig.write_text(json.dumps(daten, indent=2) + "\n", encoding="utf-8")
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.replace(TOKEN_DATEI)


def _oeffne(adresse: str) -> None:
    """Eine Adresse im Browser — abgekoppelt, damit sie uns nicht anhängt."""
    if not adresse.startswith("https://"):
        raise YouTubeError(f"Keine sichere Adresse: {adresse}")
    subprocess.Popen(
        ["xdg-open", adresse],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def _zahl(wert: int) -> str:
    """Große Zahlen kurz: 1234 → 1,2k. Auf einer Taste ist wenig Platz."""
    if wert < 1000:
        return str(wert)
    if wert < 1_000_000:
        knapp = wert / 1000
        return f"{knapp:.1f}k".replace(".", ",") if knapp < 10 else f"{round(knapp)}k"
    return f"{wert / 1_000_000:.1f}M".replace(".", ",")


class YouTubePlugin(ActionPlugin):
    def __init__(self, manifest, services) -> None:
        super().__init__(manifest, services)
        self.api = YouTubeApi()
        self.api.beim_aendern = lambda anmeldung: _schreib_token(anmeldung.als_dict())
        self.fehler = ""

        # Gespiegelter Zustand — nur daraus zeichnet render().
        self.sendung = None
        self.zuschauer: int | None = None
        self.stand_geholt = 0.0

        self._rueckfrage: dict[str, float] = {}
        self._laufende_anmeldung: dict[str, Any] = {}
        self._auffrischer: asyncio.Task | None = None
        self._holt = asyncio.Lock()
        #: Ob überhaupt jemand hinsieht. Ohne sichtbare Kachel wird nicht
        #: gefragt — jede Abfrage kostet eine Einheit vom Tagesvorrat.
        self._gefragt = False

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self) -> None:
        self._uebernimm_konfiguration()
        gespeichert = _lade_token()
        if gespeichert:
            self.api.anmeldung = Anmeldung.aus_dict(gespeichert)
        self._auffrischer = asyncio.create_task(self._schleife(), name="youtube-auffrischen")

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
        self.api.client_id = str(self.plugin_config.get("client_id") or "").strip()
        self.api.client_secret = str(self.plugin_config.get("client_secret") or "").strip()
        self.api.vergiss()
        # Kurz halten: Der Text steht auf der Plugin-Karte, und dort ist
        # kein Platz für eine Begründung. Warum jeder eigene Zugangsdaten
        # braucht, steht als Hilfe am Feld selbst und in der Doku — dort
        # sucht man es auch.
        self.fehler = "" if (self.api.client_id and self.api.client_secret) else (
            "Zugangsdaten fehlen — siehe Plugin-Einstellungen"
        )

    @property
    def takt(self) -> float:
        try:
            return max(10.0, float(self.plugin_config.get("poll_s") or STANDARD_TAKT_S))
        except (TypeError, ValueError):
            return STANDARD_TAKT_S

    def get_status(self) -> dict[str, Any] | None:
        if self.fehler:
            return {"connected": False, "detail": self.fehler}
        if not self.api.angemeldet:
            return {"connected": False, "detail": "nicht mit YouTube verbunden"}
        kanal = self.api.anmeldung.kanal or "verbunden"
        if self.sendung is None:
            return {"connected": True, "detail": f"{kanal} — keine Sendung"}
        if self.sendung.laeuft:
            zahl = self.zuschauer if self.zuschauer is not None else "?"
            return {"connected": True, "detail": f"{kanal} — live, {zahl} Zuschauer"}
        return {"connected": True, "detail": f"{kanal} — Sendung bereit"}

    # -- Hintergrund -------------------------------------------------------

    async def _schleife(self) -> None:
        while True:
            await asyncio.sleep(self.takt)
            if not self.api.angemeldet or not self._gefragt:
                continue
            try:
                await self._hole_stand()
            except Exception as exc:  # noqa: BLE001 — die Schleife darf nie sterben
                log.debug("YouTube: Auffrischen fehlgeschlagen: %s", exc)

    async def _hole_stand(self) -> None:
        if self._holt.locked():
            return
        async with self._holt:
            def arbeit():
                sendung = self.api.sendung()
                zuschauer = self.api.zuschauer() if sendung and sendung.laeuft else None
                return sendung, zuschauer

            try:
                sendung, zuschauer = await asyncio.to_thread(arbeit)
            except (NichtAngemeldet, KeineZugangsdaten):
                return
            except YouTubeError as exc:
                self.notify_error(f"YouTube: {exc}")
                return

            self.sendung = sendung
            self.zuschauer = zuschauer
            self.stand_geholt = time.monotonic()
            self.services.runtime.request_redraw()

    # -- Anmeldung über die GUI -------------------------------------------

    async def gui_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "status":
            return {
                "angemeldet": self.api.angemeldet,
                "konto": self.api.anmeldung.kanal,
                "fehler": self.fehler,
            }
        if command == "verbinden":
            daten = await asyncio.to_thread(self.api.geraetecode)
            self._laufende_anmeldung = {
                "device_code": str(daten.get("device_code") or ""),
                "interval": float(daten.get("interval") or 5),
                "endet": time.monotonic() + float(daten.get("expires_in") or 1800),
            }
            return {
                "code": daten.get("user_code"),
                "url": daten.get("verification_url") or daten.get("verification_uri")
                or "https://www.google.com/device",
                "interval": self._laufende_anmeldung["interval"],
            }
        if command == "nachfragen":
            return await self._nachfragen()
        if command == "abmelden":
            await asyncio.to_thread(self.api.abmelden)
            TOKEN_DATEI.unlink(missing_ok=True)
            self.sendung = None
            self.zuschauer = None
            self.services.runtime.request_redraw()
            return {"angemeldet": False}
        raise NotImplementedError(f"YouTube kennt kein Kommando '{command}'")

    async def _nachfragen(self) -> dict[str, Any]:
        laufend = self._laufende_anmeldung
        if not laufend:
            return {"angemeldet": self.api.angemeldet, "wartet": False}
        if time.monotonic() > laufend["endet"]:
            self._laufende_anmeldung = {}
            raise YouTubeError("Der Code ist abgelaufen — bitte neu anfangen")

        anmeldung = await asyncio.to_thread(
            self.api.code_einloesen, laufend["device_code"]
        )
        if not anmeldung.access_token:
            return {"angemeldet": False, "wartet": True}

        self._laufende_anmeldung = {}
        _schreib_token(anmeldung.als_dict())
        await self._hole_stand()
        return {"angemeldet": True, "wartet": False, "konto": anmeldung.kanal}

    # -- Bedienung ---------------------------------------------------------

    async def on_key_down(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def on_dial_push(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def _ausfuehren(self, action_id, settings, ctx) -> None:
        if self.fehler:
            self.notify_error(self.fehler)
            return
        if not self.api.angemeldet:
            self.notify_error("Für YouTube ist niemand verbunden — Plugin-Einstellungen")
            return

        # Was sich nicht zurücknehmen lässt, fragt einmal nach. Beim Stream
        # nur das Beenden: Starten ist harmlos, Beenden endgültig.
        braucht_rueckfrage = bool(settings.get("confirm"))
        if action_id == "stream":
            braucht_rueckfrage = braucht_rueckfrage and bool(
                self.sendung and self.sendung.laeuft
            )
        if braucht_rueckfrage and not self._bestaetigt(ctx.key):
            self.notify_info("Noch einmal drücken zum Auslösen")
            ctx.request_redraw()
            return

        try:
            await asyncio.to_thread(self._arbeit, action_id, dict(settings))
        except YouTubeError as exc:
            self.notify_error(f"{action_id}: {exc}")
        else:
            await self._hole_stand()
        ctx.request_redraw()

    def _bestaetigt(self, schluessel: str) -> bool:
        bis = self._rueckfrage.get(schluessel, 0.0)
        if time.monotonic() < bis:
            self._rueckfrage.pop(schluessel, None)
            return True
        self._rueckfrage[schluessel] = time.monotonic() + 5.0
        return False

    def _arbeit(self, action_id: str, settings: dict[str, Any]) -> None:
        """Alles, was mit YouTube spricht — läuft in einem Thread."""
        if action_id == "viewers":
            # Ein Druck holt die Zahl sofort, statt auf den Takt zu warten.
            self.api.vergiss()
            self.api.zuschauer()

        elif action_id == "chat":
            text = str(settings.get("message") or "").strip()
            if not text:
                raise YouTubeError("Für diese Taste ist keine Nachricht eingetragen")
            self.api.schicke_chat(text)

        elif action_id == "ad":
            self.api.werbung(int(settings.get("duration") or 30))

        elif action_id == "dashboard":
            self.api.sendung()
            _oeffne(self.api.dashboard_adresse())

        elif action_id == "stream":
            laufend = self.api.sendung(erneut=True)
            if laufend is None:
                raise YouTubeError(
                    "Es gibt keine Sendung. Eine muss in YouTube Studio angelegt "
                    "sein, bevor sie sich von hier starten lässt."
                )
            self.api.wechsle("complete" if laufend.laeuft else "live")

    # -- Anzeige -----------------------------------------------------------

    async def on_tick(self, action_id, settings, ctx):
        """Merkt, dass jemand hinsieht, und frischt im Takt auf."""
        self._gefragt = True
        if not self.api.angemeldet or self.fehler:
            return
        if time.monotonic() - self.stand_geholt >= self.takt:
            await self._hole_stand()

    def _wort(self, name: str) -> str:
        try:
            sprache = self.services.config.app.language
        except AttributeError:
            sprache = "de"
        return WOERTER.get(sprache, WOERTER["de"]).get(name, name)

    def get_state(self, action_id, settings, ctx):
        if action_id == "viewers":
            return "live" if (self.sendung and self.sendung.laeuft) else "aus"
        if action_id == "stream":
            if self.sendung is None:
                return "keine"
            return "live" if self.sendung.laeuft else "bereit"
        return None

    def render(self, action_id, settings, ctx):
        if action_id not in ("viewers", "stream"):
            return super().render(action_id, settings, ctx)

        render = self.services.render
        live = bool(self.sendung and self.sendung.laeuft)
        farbe = FARBE_LIVE if live else FARBE_AUS
        bild = render.background(ctx.size, ctx.appearance, accent=ACCENT,
                                 frame_time=ctx.frame_time)
        breite, hoehe = ctx.size

        if self.fehler:
            gross, klein = "—", self._wort("no_keys")
        elif not self.api.angemeldet:
            gross, klein = "—", self._wort("no_login")
        elif action_id == "stream":
            if self.sendung is None:
                gross, klein = "—", self._wort("no_broadcast")
            elif live:
                gross, klein = self._wort("live"), self.sendung.titel
            else:
                gross, klein = self._wort("ready"), self.sendung.titel
        elif not live:
            gross, klein = "—", self._wort("offline")
        elif self.zuschauer is None:
            gross, klein = "…", self._wort("viewers")
        else:
            gross, klein = _zahl(self.zuschauer), self._wort("viewers")

        beschriftung = ctx.appearance.label_text or ""

        if ctx.input_type == "dial":
            render.draw_text_at(bild, beschriftung or "YouTube", x=10, y=8, size=13,
                                color="#c7c7d1", max_width=breite - 70)
            if self.api.angemeldet:
                render.draw_text_at(bild, self._wort("live") if live else self._wort("offline"),
                                    x=breite - 10, y=8, size=13, color=farbe, align="right")
            render.draw_text_at(bild, gross, x=10, y=30, size=38, bold=True,
                                color=ctx.appearance.label_color)
            return bild

        groesse = 28 if len(gross) <= 5 else 20
        render.draw_text(bild, gross, y=hoehe // 2 - groesse // 2 - 6, size=groesse,
                         bold=True, color=ctx.appearance.label_color)
        if klein:
            render.draw_text(bild, klein[:18], y=hoehe // 2 + groesse // 2 - 2, size=12,
                             color="#c7c7d1")
        if beschriftung:
            render.draw_text(bild, beschriftung, y=8, size=12, color="#9ca3af")
        # Ein schmaler Streifen sagt live oder nicht — Farbe liest man
        # schneller als ein Wort.
        if self.api.angemeldet and not self.fehler:
            render.draw_bar(bild, 1.0 if live else 0.0, color=farbe,
                            box=(12, hoehe - 14, breite - 12, hoehe - 9))
        return bild
