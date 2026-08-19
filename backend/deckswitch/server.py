"""Lokaler HTTP-/WebSocket-Server als Brücke zur GUI.

Bindet ausschließlich an ``127.0.0.1``. Änderungen aus der GUI landen direkt
in der laufenden Runtime — kein „speichern und Backend neu starten“.

Über den WebSocket gehen Ereignisse in die Gegenrichtung: Geräteverbindung,
Seitenwechsel, Plugin-Fehler, Zustandsänderungen von außen.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import mimetypes
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from . import events as ev
from . import paths
from .config import Config, DeviceSettings, Page, Slot, TouchWallpaper
from .plugins import installer
from .runtime import Runtime
from .virtualdeck import VirtualDevice
from .services import autostart, backgrounds, screensaver
from .services import render as render_service

log = logging.getLogger(__name__)

#: Bildformate, die ein Plugin als Symbol mitbringen darf.
PLUGIN_ICON_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

#: Dateiendungen, die als Bildschirmschoner infrage kommen.
SCREENSAVER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class SlotPayload(BaseModel):
    slot: Slot | None = None


class PageCreate(BaseModel):
    name: str = "Neue Seite"
    parent_id: str | None = None


class PageUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    #: Hintergrundbild des Touchstrips dieser Seite.
    touch_wallpaper: dict | None = None


class AppSettingsUpdate(BaseModel):
    """Nur die App-Einstellungen — kein Rundumschlag über die ganze Config."""

    language: str | None = None
    active_iconset: str | None = None


class VirtualDeckCreate(BaseModel):
    """Ein neues Overlay-Deck. Raster frei wählbar — es hängt an keiner Hardware."""

    name: str = "Virtuelles Deck"
    columns: int = 4
    rows: int = 2
    dials: int = 0


class NetworkDeckCreate(BaseModel):
    """Ein neues Deck, das über das Netz bedient wird."""

    name: str = "Netz-Deck"
    columns: int = 4
    rows: int = 2
    dials: int = 0


class NetworkPassword(BaseModel):
    """Passwort setzen — leer entfernt es und sperrt das Deck damit."""

    password: str = ""


class OverlayToggle(BaseModel):
    """Overlay eines virtuellen Decks zeigen, verstecken oder umschalten."""

    #: ``None`` = umschalten.
    visible: bool | None = None
    at_cursor: bool = True


class OverlayPosition(BaseModel):
    """Wohin das Overlay gezogen wurde — in Bildschirmkoordinaten."""

    x: int
    y: int


class DeckInput(BaseModel):
    """Eine Eingabe aus dem Overlay."""

    input_type: str = "key"
    index: int = 0
    #: ``down``/``up`` für gedrückt/losgelassen, ``click`` für beides
    #: nacheinander, ``rotate`` für das Mausrad auf einem Dial.
    action: str = "click"
    delta: int = 0


class DeckUpdate(BaseModel):
    """Was sich an einem Deck einstellen lässt."""

    name: str | None = None
    order: int | None = None
    profile_id: str | None = None
    #: Vollständige Geräteeinstellungen (Helligkeit, Zeiten, Schoner).
    device: dict | None = None
    #: Nur bei virtuellen Decks: Raster und Kachelgröße.
    columns: int | None = None
    rows: int | None = None
    dials: int | None = None
    tile_size: int | None = None
    overlay_transparent: bool | None = None
    hide_empty: bool | None = None
    #: Nur bei Overlay-Decks: globaler Kurzbefehl zum Umschalten. Leer
    #: nimmt ihn wieder weg.
    overlay_hotkey: str | None = None
    #: Nur bei Netz-Decks: ob sie im Netz angeboten werden.
    network_enabled: bool | None = None


class PageMove(BaseModel):
    """Neue Position einer Seite: Elternteil + Index unter den Geschwistern.

    Beides wird immer mitgeschickt — Umsortieren innerhalb des gleichen
    Elternteils ist schlicht ein Move mit unverändertem ``parent_id``.
    """

    parent_id: str | None = None
    index: int = 0


def _allowed_origins(host: str, port: int, dev: bool = False) -> set[str]:
    """Herkünfte, denen der Server trauen darf.

    Der Server bindet nur an 127.0.0.1, aber das schützt nicht vor dem
    Browser: Jede offene Webseite läuft auf demselben Rechner und könnte
    sonst im Hintergrund mit dem Deck reden. Deshalb eine feste Liste statt
    ``*`` — die eigene GUI und das Tauri-Fenster.

    Die Vite-Ports stehen **nur im Entwicklungsmodus** darin. Im normalen
    Betrieb wären sie ein offenes Scheunentor: Wer auf 5173 irgendetwas
    laufen lässt, dürfte sonst die ganze API lesen — samt ``/api/export``
    mit den Zugangsdaten in den Plugin-Einstellungen.
    """
    hosts = {host, "127.0.0.1", "localhost"}
    origins = {f"http://{h}:{port}" for h in hosts}
    if dev:
        for dev_port in (5173, 5174, 4173):
            origins |= {f"http://{h}:{dev_port}" for h in ("localhost", "127.0.0.1")}
    # Das Tauri-Fenster meldet sich je nach Plattform unterschiedlich.
    origins |= {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
    return origins


#: HTTP-Methoden, die etwas verändern — nur die brauchen den Origin-Riegel.
_UNSAFE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def create_app(
    runtime: Runtime,
    *,
    host: str = "127.0.0.1",
    port: int = 8770,
    dev: bool = False,
) -> FastAPI:
    app = FastAPI(title="DECK//SWITCH", version=__version__, docs_url="/api/docs")
    allowed_origins = _allowed_origins(host, port, dev)

    # CORS auf die bekannten Herkünfte einschränken. Damit blockt der Browser
    # das *Lesen* fremder Antworten und lässt vorab geprüfte Anfragen (JSON,
    # also alles, was die GUI schickt) gar nicht erst durch.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _origin_guard(request, call_next):
        """Zweiter Riegel gegen fremde Webseiten.

        CORS schützt nur, was der Browser *vorab prüft*. Eine „einfache"
        Anfrage (Formular-POST, GET) geht ohne Vorabprüfung raus, und der
        Browser blockt danach nur das Lesen der Antwort — die Aktion wäre
        aber schon passiert. Deshalb: Trägt eine verändernde Anfrage einen
        fremden ``Origin``, wird sie hier abgewiesen, bevor sie etwas tut.

        Ohne ``Origin`` (Kommandozeile, gleiche Herkunft) bleibt alles frei —
        der Schutz richtet sich gegen den Browser, nicht gegen den Nutzer.
        """
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse(
                    {"detail": "Zugriff von einer fremden Herkunft abgelehnt"},
                    status_code=403,
                )
        return await call_next(request)

    # ======================================================================
    # Zustand
    # ======================================================================

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        primary = runtime.primary
        return {
            # Die Oberfläche zeigt die Version des *Backends*, nicht ihre
            # eigene: Bei einem Netz-Deck oder einer halb aktualisierten
            # Installation ist das die Zahl, die zählt.
            "version": __version__,
            # ``device`` bleibt das Hauptdeck — für alles, was nur ein Gerät
            # kennt. Die vollständige Liste steht in ``decks``.
            "device": primary.device.info.as_dict(),
            "decks": runtime.decks_payload(),
            "active_deck": primary.key,
            "config": runtime.config.model_dump(mode="json"),
            "current_page_id": primary.current_page_id(),
            "plugins": _plugins_payload(runtime),
            "errors": runtime.errors[-50:],
            "backgrounds": backgrounds.PRESETS,
        }

    @app.get("/api/device")
    async def get_device(deck: str | None = None) -> dict[str, Any]:
        return runtime.deck(deck).device.info.as_dict()

    # ======================================================================
    # Decks
    # ======================================================================

    @app.get("/api/decks")
    async def list_decks() -> list[dict[str, Any]]:
        return runtime.decks_payload()

    @app.post("/api/decks/virtual")
    async def create_virtual_deck(payload: VirtualDeckCreate) -> dict[str, Any]:
        """Legt ein Deck an, das als Overlay auf dem Bildschirm liegt."""
        deck = runtime.create_virtual_deck(
            payload.name.strip() or "Virtuelles Deck",
            columns=payload.columns,
            rows=payload.rows,
            dials=payload.dials,
        )
        return deck.as_dict()

    @app.post("/api/decks/network")
    async def create_network_deck(payload: NetworkDeckCreate) -> dict[str, Any]:
        """Legt ein Deck an, das jemand im selben Netz im Browser bedient.

        Angeboten wird es erst, sobald ein Passwort gesetzt ist.
        """
        deck = runtime.create_network_deck(
            payload.name.strip() or "Netz-Deck",
            columns=payload.columns,
            rows=payload.rows,
            dials=payload.dials,
        )
        await runtime.netz.sync()
        runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=runtime.decks_payload())
        return deck.as_dict()

    @app.post("/api/decks/{key}/password")
    async def set_network_password(key: str, payload: NetworkPassword) -> dict[str, Any]:
        """Setzt das Passwort eines Netz-Decks oder entfernt es.

        Das Passwort wird nur abgeleitet gespeichert und nie zurückgegeben.
        Wer es ändert, trennt damit auch alle, die gerade angemeldet sind.
        """
        try:
            gesetzt = runtime.netz.set_password(key, payload.password)
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc
        await runtime.netz.sync()
        runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=runtime.decks_payload())
        return {"has_password": gesetzt, "urls": runtime.netz.urls(key)}

    @app.post("/api/decks/{key}/overlay")
    async def deck_overlay(key: str, payload: OverlayToggle) -> dict[str, Any]:
        """Zeigt das Overlay, versteckt es oder schaltet um."""
        deck = runtime.decks.get(key)
        if deck is None or not deck.binding.is_overlay:
            raise HTTPException(404, "Kein Deck mit Overlay")
        try:
            if payload.visible is None:
                sichtbar = await runtime.overlay.toggle(key, at_cursor=payload.at_cursor)
            elif payload.visible:
                await runtime.overlay.show(key, at_cursor=payload.at_cursor)
                sichtbar = True
            else:
                runtime.overlay.hide(key)
                sichtbar = False
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=runtime.decks_payload())
        return {"visible": sichtbar}

    @app.post("/api/decks/{key}/overlay/position")
    async def deck_overlay_position(key: str, payload: OverlayPosition) -> dict[str, Any]:
        """Merkt sich, wo das Overlay abgelegt wurde, und setzt es dorthin.

        Das Overlay ruft das selbst, sobald man es loslässt — nicht während
        des Ziehens: Sonst schriebe jede Mausbewegung die Konfiguration.

        Der Neuaufbau ist nötig, weil eine Layer-Shell-Surface im Betrieb
        nicht umziehen kann (siehe ``deck-overlay.qml``). Er läuft absichtlich
        erst *nach* dieser Antwort: Sonst beendeten wir den Prozess, der noch
        auf sie wartet.
        """
        try:
            x, y = runtime.overlay.remember_position(key, payload.x, payload.y)
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc

        if runtime.overlay.is_visible(key):
            async def an_neue_stelle() -> None:
                await asyncio.sleep(0.05)
                try:
                    await runtime.overlay.show(key, at_cursor=False)
                except RuntimeError:
                    log.warning("Overlay ließ sich nicht neu setzen", exc_info=True)

            asyncio.create_task(an_neue_stelle())

        runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=runtime.decks_payload())
        return {"x": x, "y": y}

    @app.get("/api/decks/{key}/tiles")
    async def deck_tiles(key: str) -> dict[str, Any]:
        """Alles, was das Overlay zum Zeichnen braucht.

        ``versions`` sagt je Kachel, wie oft sie sich geändert hat — das
        Overlay lädt daraufhin nur die Bilder, die wirklich neu sind.
        """
        deck = runtime.decks.get(key)
        if deck is None:
            raise HTTPException(404, "Deck nicht gefunden")
        device = deck.device
        if not isinstance(device, VirtualDevice):
            raise HTTPException(400, "Dieses Deck ist kein virtuelles")
        return {
            "deck": deck.key,
            "name": deck.label,
            "columns": deck.binding.columns,
            "rows": deck.binding.rows,
            "dials": deck.binding.dials,
            "tile_size": deck.binding.key_size,
            "transparent": deck.binding.overlay_transparent,
            "hide_empty": deck.binding.hide_empty,
            "brightness": device.brightness,
            "revision": device.revision,
            "versions": device.versions(),
            "page_id": deck.current_page_id(),
            # Welche Plätze überhaupt belegt sind — nur damit kann das
            # Overlay leere ausblenden, ohne die Belegung zu kennen.
            "filled": _belegte_plaetze(deck),
        }

    @app.get("/api/decks/{key}/tile/{input_type}/{index}.png")
    async def deck_tile(key: str, input_type: str, index: int) -> Response:
        """Das Bild einer Kachel — genau so, wie es auf einem Deck stünde."""
        deck = runtime.decks.get(key)
        device = deck.device if deck else None
        if not isinstance(device, VirtualDevice):
            raise HTTPException(404, "Kein virtuelles Deck")
        data = device.image(input_type, index)
        if data is None:
            raise HTTPException(404, "Für diese Kachel gibt es noch kein Bild")
        return Response(
            data, media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/decks/{key}/input")
    async def deck_input(key: str, payload: DeckInput) -> dict[str, Any]:
        """Eine Eingabe aus dem Overlay — derselbe Weg wie am echten Gerät."""
        deck = runtime.decks.get(key)
        device = deck.device if deck else None
        if not isinstance(device, VirtualDevice):
            raise HTTPException(404, "Kein virtuelles Deck")

        if payload.action == "rotate":
            device.rotate(payload.index, payload.delta or 1)
        elif payload.action == "down":
            device.press(payload.input_type, payload.index, True)
        elif payload.action == "up":
            device.press(payload.input_type, payload.index, False)
        else:
            # Ein Klick ist Drücken und Loslassen — nur so greifen
            # Push-to-Talk und die Tastenlogik wie am Gerät.
            device.press(payload.input_type, payload.index, True)
            await asyncio.sleep(0.02)
            device.press(payload.input_type, payload.index, False)
        return {"ok": True}

    @app.patch("/api/decks/{key}")
    async def update_deck(key: str, payload: DeckUpdate) -> dict[str, Any]:
        deck = runtime.decks.get(key)
        if deck is None:
            raise HTTPException(404, "Deck nicht gefunden")

        if payload.name is not None:
            deck.binding.name = payload.name.strip() or deck.device.info.deck_type
        if payload.order is not None:
            deck.binding.order = payload.order
        if payload.profile_id is not None:
            if payload.profile_id not in runtime.config.profiles:
                raise HTTPException(404, "Profil nicht gefunden")
            deck.binding.profile_id = payload.profile_id
            deck.apply_config()
        if payload.device is not None:
            try:
                deck.binding.device = DeviceSettings.model_validate(payload.device)
            except ValidationError as exc:
                raise HTTPException(422, f"Geräteeinstellungen ungültig: {exc}") from exc
            deck.apply_config()

        # Nach außen heißt die Kachelgröße ``tile_size`` — im Modell
        # ``key_size``, weil ein Gerät seine Tastengröße so nennt. Die
        # Zuordnung steht hier ausdrücklich; sie stillschweigend über den
        # Feldnamen zu erraten war genau der Fehler.
        raster = (
            ("columns", "columns", 1, 16),
            ("rows", "rows", 1, 8),
            ("dials", "dials", 0, 8),
            ("tile_size", "key_size", 48, 256),
        )
        geaendert = False
        for aussen, innen, kleinster, groesster in raster:
            wert = getattr(payload, aussen)
            if wert is None:
                continue
            if not deck.binding.is_virtual:
                raise HTTPException(400, "Das Raster gilt nur für Decks ohne Gerät")
            setattr(deck.binding, innen, max(kleinster, min(groesster, int(wert))))
            geaendert = True
        for schalter in ("overlay_transparent", "hide_empty"):
            wert = getattr(payload, schalter)
            if wert is None:
                continue
            if not deck.binding.is_overlay:
                raise HTTPException(400, "Diese Einstellung gilt nur fürs Overlay")
            setattr(deck.binding, schalter, bool(wert))
            geaendert = True

        if payload.overlay_hotkey is not None:
            if not deck.binding.is_overlay:
                raise HTTPException(400, "Ein Kurzbefehl holt nur ein Overlay")
            deck.binding.overlay_hotkey = payload.overlay_hotkey.strip()

        if payload.network_enabled is not None:
            if not deck.binding.is_network:
                raise HTTPException(400, "Diese Einstellung gilt nur für Netz-Decks")
            deck.binding.network_enabled = bool(payload.network_enabled)
            runtime.save_config()
            # An- und Abschalten wirkt sofort: Der Server hört auf zu
            # lauschen, sobald das letzte Deck aus ist.
            await runtime.netz.sync()

        if geaendert:
            runtime.update_virtual_geometry(deck)

        runtime.save_config()
        # Nach *jeder* Änderung: Der Kurzbefehl hängt nicht nur an der
        # Kombination, sondern auch am Decknamen — unter dem steht er in den
        # KDE-Systemeinstellungen. Hat sich nichts geändert, tut das nichts.
        await runtime.shortcuts.sync()
        eintraege = runtime.decks_payload()
        runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=eintraege)
        # Dieselbe Form wie in der Liste zurückgeben — sonst fehlten der GUI
        # nach dem Speichern genau die Felder, die sie gerade geändert hat.
        for eintrag in eintraege:
            if eintrag["id"] == deck.key:
                return eintrag
        return deck.as_dict()

    @app.delete("/api/decks/{key}")
    async def forget_deck(key: str) -> dict[str, Any]:
        try:
            if not runtime.forget_deck(key):
                raise HTTPException(404, "Deck nicht gefunden")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Wer gerade an diesem Deck hing, fliegt sofort raus — und war es
        # das letzte im Netz, hört der Server auf zu lauschen.
        runtime.netz.sitzungen.alle_verwerfen(key)
        await runtime.netz.sync()
        # Und der Kurzbefehl des Decks wird wieder frei.
        await runtime.shortcuts.sync()
        return {"forgotten": key}

    @app.post("/api/device/brightness")
    async def set_brightness(
        value: int = Body(..., embed=True), deck: str | None = None
    ) -> dict[str, Any]:
        session = runtime.deck(deck)
        session.settings.brightness = max(0, min(100, value))
        session.device.set_brightness(session.settings.brightness)
        runtime.save_config()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="brightness")
        return {"brightness": session.settings.brightness}

    @app.post("/api/device/reconnect")
    async def reconnect(deck: str | None = None) -> dict[str, Any]:
        runtime.deck(deck).device.close()
        return {"ok": True}

    # ======================================================================
    # Schriften und Eingabegerät
    # ======================================================================

    @app.get("/api/fonts")
    def list_fonts() -> list[str]:
        """Installierte Schriftfamilien für die Beschriftungsauswahl."""
        return render_service.list_font_families()

    @app.get("/api/input/status")
    def input_status() -> dict[str, Any]:
        """Kann die App Tastendrücke schicken? Was sagt die Belegung?"""
        available, reason = runtime.input.available()
        return {
            "available": available,
            "reason": reason,
            "layout": runtime.input.layout if available else "",
        }

    # ======================================================================
    # Config
    # ======================================================================

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return runtime.config.model_dump(mode="json")

    @app.patch("/api/config/app")
    async def patch_app_settings(payload: AppSettingsUpdate) -> dict[str, Any]:
        """Ändert gezielt die App-Einstellungen.

        Bewusst *nicht* über ``PUT /api/config``: Wer für eine Sprachumstellung
        die ganze Config zurückschickt, überschreibt alles, was in der
        Zwischenzeit woanders passiert ist — eine Helligkeit, die am Dial
        verstellt wurde, oder ein Deck, das sich gerade angemeldet hat.
        """
        app_settings = runtime.config.app
        if payload.language is not None:
            if payload.language not in ("de", "en"):
                raise HTTPException(422, "Unbekannte Sprache")
            app_settings.language = payload.language
        if payload.active_iconset is not None:
            app_settings.active_iconset = payload.active_iconset

        runtime.save_config()
        runtime.icons.clear_cache()
        runtime.request_redraw()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="app_settings")
        return app_settings.model_dump(mode="json")

    @app.put("/api/config")
    async def put_config(payload: dict = Body(...)) -> dict[str, Any]:
        try:
            config = Config.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(422, f"Config ungültig: {exc}") from exc
        runtime.apply_config(config)
        return config.model_dump(mode="json")

    # ======================================================================
    # Bildschirmschoner
    # ======================================================================

    @app.get("/api/screensavers")
    async def list_screensavers() -> list[dict[str, Any]]:
        """Alles, was sich als Schoner einstellen lässt.

        Hochgeladene Bilder und Schoner-Plugins in einer Liste — die GUI
        soll dafür nicht zwei Quellen zusammenfügen müssen.
        """
        entries: list[dict[str, Any]] = []

        for loaded in runtime.registry.screensavers:
            # ``instance`` fehlt, wenn das Plugin beim Laden gescheitert ist.
            # So eines anzubieten hieße, den Fehler erst beim Auswählen zu
            # zeigen — und dann als leeres Deck statt als Meldung.
            if not loaded.enabled or loaded.instance is None:
                continue
            entries.append(
                {
                    "source": f"plugin:{loaded.id}",
                    "kind": "plugin",
                    "name": loaded.manifest.name,
                    "description": loaded.manifest.description,
                    "animated": getattr(loaded.instance, "interval_s", 0) > 0,
                    "preview_url": f"/api/screensavers/preview?source=plugin:{loaded.id}",
                }
            )

        if paths.UPLOADS_DIR.is_dir():
            for path in sorted(paths.UPLOADS_DIR.iterdir()):
                if path.suffix.lower() not in SCREENSAVER_SUFFIXES:
                    continue
                entries.append(
                    {
                        "source": f"upload:{path.name}",
                        "kind": "upload",
                        "name": path.stem,
                        "description": "",
                        "animated": path.suffix.lower() == ".gif",
                        "preview_url": f"/api/uploads/{path.name}",
                    }
                )
        return entries

    @app.get("/api/screensavers/preview")
    def screensaver_preview(source: str, deck: str | None = None) -> Response:
        """Zeigt, wie der Schoner auf dem Deck aussieht — inklusive Fugen."""
        session = runtime.deck(deck)
        layout = screensaver.layout(
            session.device.info.key_size,
            session.device.info.key_count or 8,
            session.device.info.touchscreen_size,
        )
        try:
            image = session.screensaver_preview(source, layout)
        except Exception as exc:
            raise HTTPException(404, f"Schoner nicht darstellbar: {exc}") from exc

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")

    @app.post("/api/screensavers/test")
    async def test_screensaver(deck: str | None = None) -> dict[str, Any]:
        """Zeigt den eingestellten Schoner sofort — zum Ausprobieren."""
        session = runtime.deck(deck)
        if not session.settings.screensaver.source:
            raise HTTPException(400, "Kein Bildschirmschoner eingestellt")
        session.start_screensaver_now()
        return {"ok": True}

    # ======================================================================
    # Touchstrip-Hintergrundbild
    # ======================================================================

    @app.get("/api/wallpapers")
    async def list_wallpapers() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = [
            {
                "source": f"plugin:{loaded.id}",
                "kind": "plugin",
                "name": loaded.manifest.name,
                "description": loaded.manifest.description,
                "preview_url": f"/api/wallpapers/preview?source=plugin:{loaded.id}",
            }
            for loaded in runtime.registry.wallpapers
            if loaded.enabled and loaded.instance is not None
        ]

        if paths.WALLPAPERS_DIR.is_dir():
            for path in sorted(paths.WALLPAPERS_DIR.iterdir()):
                if path.suffix.lower() not in SCREENSAVER_SUFFIXES:
                    continue
                entries.append(
                    {
                        "source": f"upload:{path.name}",
                        "kind": "upload",
                        "name": path.stem,
                        "description": "",
                        "preview_url": (
                            f"/api/wallpapers/preview?source=upload:{path.name}"
                        ),
                    }
                )
        return entries

    @app.get("/api/wallpapers/preview")
    def wallpaper_preview(
        source: str, fit: str = "cover", opacity: int = 100, deck: str | None = None
    ) -> Response:
        """Der Streifen, wie er auf dem Gerät ankommt — mit Segmentgrenzen.

        Einpassung und Deckkraft kommen als Parameter statt aus der Config:
        So lässt sich die Wirkung ausprobieren, bevor man sie speichert.
        """
        try:
            image = runtime.deck(deck).wallpaper_preview(
                source, fit=fit, opacity=opacity
            )
        except Exception as exc:
            raise HTTPException(404, f"Hintergrundbild nicht darstellbar: {exc}") from exc
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")

    # ======================================================================
    # Autostart
    # ======================================================================

    # Bewusst synchron: ``systemctl`` ist ein Unterprozess. In einer
    # ``async``-Route würde er den Event-Loop blockieren und damit auch den
    # WebSocket, über den das Deck seine Ereignisse meldet. So gibt FastAPI
    # die Route in den Threadpool.

    @app.get("/api/autostart")
    def get_autostart() -> dict[str, Any]:
        return autostart.status().as_dict()

    @app.post("/api/autostart")
    def set_autostart(payload: dict = Body(...)) -> dict[str, Any]:
        try:
            return autostart.set_enabled(bool(payload.get("enabled"))).as_dict()
        except autostart.AutostartUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except (autostart.AutostartError, OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(500, f"Autostart nicht schaltbar: {exc}") from exc

    @app.get("/api/export")
    async def export_config() -> Response:
        return Response(
            runtime.store.export_json(),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="streamdeck-config.json"'
            },
        )

    @app.post("/api/import")
    async def import_config(
        payload: dict = Body(...), merge_profiles: bool = False
    ) -> dict[str, Any]:
        try:
            config = runtime.store.import_json(
                json.dumps(payload), merge_profiles=merge_profiles
            )
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(422, f"Import fehlgeschlagen: {exc}") from exc
        runtime.apply_config(config, save=False)
        return config.model_dump(mode="json")

    # ======================================================================
    # Seiten
    # ======================================================================

    @app.get("/api/pages")
    async def list_pages(deck: str | None = None) -> dict[str, Any]:
        session = runtime.deck(deck)
        profile = session.profile
        return {
            "deck": session.key,
            "profile_id": profile.id,
            "root_page_id": profile.root_page_id,
            "current_page_id": session.current_page_id(),
            "pages": {pid: page.model_dump(mode="json") for pid, page in profile.pages.items()},
        }

    @app.post("/api/pages")
    async def create_page(payload: PageCreate, deck: str | None = None) -> dict[str, Any]:
        profile = runtime.deck(deck).profile
        parent_id = payload.parent_id
        if parent_id is not None and parent_id not in profile.pages:
            raise HTTPException(404, "Übergeordnete Seite existiert nicht")
        page = Page(
            name=payload.name,
            parent_id=parent_id,
            # Neue Seiten hinten anhängen, statt vor bestehende zu springen.
            order=len(profile.children(parent_id)),
        )
        profile.pages[page.id] = page
        runtime.save_config()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="page_created", page_id=page.id)
        return page.model_dump(mode="json")

    @app.patch("/api/pages/{page_id}")
    async def update_page(
        page_id: str, payload: PageUpdate, deck: str | None = None
    ) -> dict[str, Any]:
        profile = runtime.deck(deck).profile
        page = profile.pages.get(page_id)
        if page is None:
            raise HTTPException(404, "Seite nicht gefunden")
        if payload.name is not None:
            page.name = payload.name
        if payload.touch_wallpaper is not None:
            try:
                page.touch_wallpaper = TouchWallpaper.model_validate(
                    payload.touch_wallpaper
                )
            except ValidationError as exc:
                raise HTTPException(422, f"Hintergrundbild ungültig: {exc}") from exc
        if payload.parent_id is not None:
            new_parent = payload.parent_id or None
            _check_move_target(profile, page_id, new_parent)
            # Ans Ende des neuen Elternteils — eine sinnvollere Position kennt
            # ein reines Umhängen nicht; die gibt es über /move.
            profile.move_page(page_id, new_parent, len(profile.children(new_parent)))
        runtime.save_config()
        runtime.request_redraw()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="page_updated", page_id=page_id)
        return page.model_dump(mode="json")

    @app.post("/api/pages/{page_id}/move")
    async def move_page(
        page_id: str, payload: PageMove, deck: str | None = None
    ) -> dict[str, Any]:
        """Sortiert eine Seite um und/oder hängt sie an ein anderes Elternteil."""
        profile = runtime.deck(deck).profile
        if page_id not in profile.pages:
            raise HTTPException(404, "Seite nicht gefunden")
        if page_id == profile.root_page_id and payload.parent_id is not None:
            raise HTTPException(400, "Die Startseite kann keine Unterseite werden")
        _check_move_target(profile, page_id, payload.parent_id)

        profile.move_page(page_id, payload.parent_id, payload.index)
        runtime.save_config()
        runtime.request_redraw()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="page_moved", page_id=page_id)
        return {
            "pages": {pid: p.model_dump(mode="json") for pid, p in profile.pages.items()}
        }

    @app.delete("/api/pages/{page_id}")
    async def delete_page(page_id: str, deck: str | None = None) -> dict[str, Any]:
        session = runtime.deck(deck)
        profile = session.profile
        if page_id == profile.root_page_id:
            raise HTTPException(400, "Die Startseite kann nicht gelöscht werden")
        if page_id not in profile.pages:
            raise HTTPException(404, "Seite nicht gefunden")

        # Unterseiten mitnehmen — sonst blieben unerreichbare Waisen zurück.
        parent_id = profile.pages[page_id].parent_id
        removed = profile.subtree_ids(page_id)
        for pid in removed:
            profile.pages.pop(pid, None)
        _drop_references(profile, removed)
        profile.reindex(parent_id)

        if session.current_page_id() in removed:
            session.navigate(profile.root_page_id)
        runtime.save_config()
        runtime.request_redraw()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="page_deleted", page_id=page_id)
        return {"deleted": sorted(removed)}

    @app.post("/api/navigate/{page_id}")
    async def navigate(page_id: str, deck: str | None = None) -> dict[str, Any]:
        session = runtime.deck(deck)
        if page_id not in session.profile.pages:
            raise HTTPException(404, "Seite nicht gefunden")
        session.navigate(page_id)
        return {"current_page_id": session.current_page_id(), "deck": session.key}

    # ======================================================================
    # Belegungen
    # ======================================================================

    @app.put("/api/pages/{page_id}/slots/{input_type}/{index}")
    async def put_slot(
        page_id: str,
        input_type: str,
        index: int,
        payload: SlotPayload,
        deck: str | None = None,
    ) -> dict[str, Any]:
        session = runtime.deck(deck)
        page = _require_page(session, page_id)
        mapping = _require_mapping(page, input_type)
        _check_index(session, input_type, index)

        if payload.slot is None:
            mapping.pop(index, None)
        else:
            if runtime.registry.get(payload.slot.plugin_id) is None:
                raise HTTPException(404, f"Plugin '{payload.slot.plugin_id}' nicht gefunden")
            mapping[index] = payload.slot

        runtime.save_config()
        session.drop_context(page_id, input_type, index)
        if page_id == session.current_page_id():
            session._mark_dirty((input_type, index))
        runtime.bus.publish(
            ev.EVT_CONFIG_CHANGED,
            reason="slot_changed",
            deck=session.key,
            page_id=page_id,
            input_type=input_type,
            index=index,
        )
        return {"ok": True}

    @app.delete("/api/pages/{page_id}/slots/{input_type}/{index}")
    async def delete_slot(
        page_id: str, input_type: str, index: int, deck: str | None = None
    ) -> dict[str, Any]:
        return await put_slot(page_id, input_type, index, SlotPayload(slot=None), deck)

    @app.post("/api/pages/{page_id}/slots/{input_type}/{index}/trigger")
    async def trigger_slot(
        page_id: str, input_type: str, index: int, deck: str | None = None
    ) -> dict[str, Any]:
        """Belegung aus der GUI auslösen — zum Ausprobieren ohne Gerät."""
        session = runtime.deck(deck)
        if page_id != session.current_page_id():
            session.navigate(page_id)
        if input_type == "key":
            await session.handle_key(index, True)
            await session.handle_key(index, False)
        else:
            await session.handle_dial_push(index, True)
        return {"ok": True}

    @app.post("/api/pages/{page_id}/slots/dial/{index}/cycle")
    async def cycle_stack(
        page_id: str, index: int, deck: str | None = None
    ) -> dict[str, Any]:
        """Schaltet einen Dial-Stack weiter — dasselbe wie langes Drücken."""
        session = runtime.deck(deck)
        if page_id != session.current_page_id():
            session.navigate(page_id)
        if not session.cycle_stack(index):
            raise HTTPException(400, "Auf diesem Dial liegt kein Stack")
        return {"stack_index": session.stack_index(index)}

    # ======================================================================
    # Plugins
    # ======================================================================

    @app.get("/api/plugins")
    async def list_plugins() -> list[dict[str, Any]]:
        return _plugins_payload(runtime)

    @app.post("/api/plugins/{plugin_id}/options/{source}")
    async def plugin_options(
        plugin_id: str,
        source: str,
        context: dict = Body(default={}),
        deck: str | None = None,
    ) -> list[dict[str, Any]]:
        """Auswahlliste eines Feldes.

        ``context`` sind die bereits gesetzten Einstellungen der Belegung —
        damit kann ein Plugin abhängige Listen liefern (die Filter *dieser*
        Quelle, die Quellen *dieser* Szene). Zusätzlich steckt darin unter
        ``__deck``, welches Gerät die GUI gerade bearbeitet: Die Seitenliste
        etwa gibt es je Deck einmal.
        """
        plugin = runtime.registry.instance(plugin_id)
        if plugin is None:
            raise HTTPException(404, "Plugin nicht geladen")
        payload = dict(context or {})
        payload["__deck"] = runtime.deck(deck).key
        try:
            return await runtime._call_hook(
                plugin.get_dynamic_options, source, payload
            )
        except Exception as exc:
            raise HTTPException(500, f"Optionen nicht abrufbar: {exc}") from exc

    @app.get("/api/plugins/{plugin_id}/icon")
    async def plugin_icon(plugin_id: str) -> Response:
        """Das Bild, das ein Plugin in der Übersicht vertritt."""
        loaded = runtime.registry.get(plugin_id)
        if loaded is None or not loaded.manifest.icon:
            raise HTTPException(404, "Kein Symbol hinterlegt")

        # Der Dateiname kommt aus einem fremden Manifest — er darf auf
        # nichts außerhalb des Plugin-Ordners zeigen.
        directory = loaded.directory.resolve()
        candidate = (directory / loaded.manifest.icon).resolve()
        if directory not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "Symboldatei nicht gefunden")
        if candidate.suffix.lower() not in PLUGIN_ICON_SUFFIXES:
            raise HTTPException(415, f"Nicht unterstützt: {candidate.suffix}")

        media = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        # Wie beim Upload: Ein Plugin-Symbol kommt aus fremder Hand und darf
        # bei direktem Aufruf kein Skript ausführen.
        headers = {"X-Content-Type-Options": "nosniff"}
        if candidate.suffix.lower() == ".svg":
            headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return FileResponse(candidate, media_type=media, headers=headers)

    @app.put("/api/plugins/{plugin_id}/config")
    async def put_plugin_config(plugin_id: str, payload: dict = Body(...)) -> dict[str, Any]:
        if runtime.registry.get(plugin_id) is None:
            raise HTTPException(404, "Plugin nicht gefunden")
        runtime.config.plugin_settings[plugin_id] = payload
        runtime.save_config()
        runtime.notify_plugin_config_changed(plugin_id)
        runtime.request_redraw()
        return payload

    @app.post("/api/plugins/{plugin_id}/command/{command}")
    async def plugin_command(
        plugin_id: str, command: str, payload: dict = Body(default={})
    ) -> dict[str, Any]:
        plugin = runtime.registry.instance(plugin_id)
        if plugin is None:
            raise HTTPException(404, "Plugin nicht geladen")
        # Discords „Jetzt verbinden“ öffnet einen Dialog im Client — großzügig
        # bemessener Timeout, damit der User Zeit zum Bestätigen hat.
        try:
            result = await asyncio.wait_for(
                plugin.gui_command(command, payload), timeout=60
            )
        except NotImplementedError as exc:
            raise HTTPException(400, str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "Zeitüberschreitung") from exc
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
        return result if isinstance(result, dict) else {"result": result}

    @app.post("/api/plugins/{plugin_id}/enabled")
    async def set_plugin_enabled(
        plugin_id: str, enabled: bool = Body(..., embed=True)
    ) -> dict[str, Any]:
        loaded = runtime.registry.get(plugin_id)
        if loaded is None:
            raise HTTPException(404, "Plugin nicht gefunden")
        disabled = set(runtime.config.disabled_plugins)
        disabled.discard(plugin_id) if enabled else disabled.add(plugin_id)
        runtime.config.disabled_plugins = sorted(disabled)
        runtime.save_config()
        await runtime.reload_plugins()
        return {"plugin_id": plugin_id, "enabled": enabled}

    @app.post("/api/plugins/reload")
    async def reload_plugins() -> dict[str, Any]:
        await runtime.reload_plugins()
        return {"plugins": _plugins_payload(runtime)}

    # -- Installieren und Entfernen ----------------------------------------

    @app.post("/api/plugins/install-url")
    async def install_from_url(url: str = Body(..., embed=True)) -> dict[str, Any]:
        """Lädt ein Plugin-Archiv von einer Adresse und installiert es."""
        try:
            manifest = await asyncio.get_running_loop().run_in_executor(
                None, installer.install_url, url
            )
        except installer.InstallError as exc:
            raise HTTPException(400, str(exc)) from exc
        await runtime.reload_plugins()
        return {"installed": manifest.id, "version": manifest.version}

    # -- Anfragen über streamdeck:// ---------------------------------------

    @app.post("/api/plugins/install-request")
    async def request_install(
        url: str = Body(..., embed=True), origin: str = Body("", embed=True)
    ) -> dict[str, Any]:
        """Nimmt eine ``streamdeck://``-Anfrage entgegen — ohne zu installieren.

        Ein Klick auf einen Link im Browser darf keinen Code auf den Rechner
        bringen. Die Anfrage wartet auf Bestätigung in der GUI.
        """
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "Nur http(s)-Adressen werden angenommen")
        request = runtime.add_install_request(url, origin)
        return request.as_dict()

    @app.get("/api/plugins/install-requests")
    async def list_install_requests() -> list[dict[str, Any]]:
        return runtime.pending_install_requests()

    @app.post("/api/plugins/install-requests/{request_id}")
    async def confirm_install_request(request_id: str) -> dict[str, Any]:
        request = runtime.take_install_request(request_id)
        if request is None:
            raise HTTPException(404, "Anfrage nicht gefunden oder abgelaufen")
        try:
            manifest = await asyncio.get_running_loop().run_in_executor(
                None, installer.install_url, request.url
            )
        except installer.InstallError as exc:
            raise HTTPException(400, str(exc)) from exc
        await runtime.reload_plugins()
        return {"installed": manifest.id, "version": manifest.version}

    @app.delete("/api/plugins/install-requests/{request_id}")
    async def dismiss_install_request(request_id: str) -> dict[str, Any]:
        runtime.take_install_request(request_id)
        return {"dismissed": request_id}

    @app.post("/api/plugins/install")
    async def install_archive(file: UploadFile = File(...)) -> dict[str, Any]:
        data = await file.read(installer.MAX_ARCHIVE_BYTES + 1)
        if len(data) > installer.MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "Archiv zu groß (max. 64 MB)")
        try:
            manifest = installer.install_archive(data, filename=file.filename or "")
        except installer.InstallError as exc:
            raise HTTPException(400, str(exc)) from exc
        await runtime.reload_plugins()
        return {"installed": manifest.id, "version": manifest.version}

    @app.delete("/api/plugins/{plugin_id}")
    async def uninstall_plugin(plugin_id: str) -> dict[str, Any]:
        loaded = runtime.registry.get(plugin_id)
        if loaded is not None and loaded.builtin:
            raise HTTPException(400, "Eingebaute Plugins lassen sich nicht entfernen")
        try:
            installer.uninstall(plugin_id)
        except installer.InstallError as exc:
            raise HTTPException(400, str(exc)) from exc

        # Belegungen, die auf das entfernte Plugin zeigen, würden sonst als
        # Fehlerkacheln stehen bleiben.
        removed = _drop_plugin_slots(runtime, plugin_id)
        runtime.config.app.plugin_order = [
            p for p in runtime.config.app.plugin_order if p != plugin_id
        ]
        runtime.save_config()
        await runtime.reload_plugins()
        return {"uninstalled": plugin_id, "slots_removed": removed}

    @app.put("/api/plugins/order")
    async def set_plugin_order(order: list[str] = Body(..., embed=True)) -> dict[str, Any]:
        """Reihenfolge der Plugins in Bibliothek und Plugin-Liste."""
        known = set(runtime.registry.plugins)
        unknown = [p for p in order if p not in known]
        if unknown:
            raise HTTPException(404, f"Unbekannte Plugins: {', '.join(unknown)}")

        runtime.config.app.plugin_order = list(dict.fromkeys(order))
        runtime.save_config()
        runtime.bus.publish(ev.EVT_CONFIG_CHANGED, reason="plugin_order")
        return {"order": runtime.config.app.plugin_order}

    # ======================================================================
    # Icons und Uploads
    # ======================================================================

    @app.get("/api/icons/sets")
    async def icon_sets() -> list[dict[str, Any]]:
        return [
            {k: v for k, v in entry.items() if k != "icons"}
            for entry in runtime.icons.list_sets()
        ]

    @app.get("/api/icons/sets/{set_id}")
    async def icon_set(set_id: str, query: str = "", limit: int = 500) -> dict[str, Any]:
        names = runtime.icons.list_icons(set_id)
        if query:
            needle = query.lower()
            names = [n for n in names if needle in n.lower()]
        return {"set_id": set_id, "total": len(names), "icons": names[:limit]}

    @app.get("/api/icons/svg/{set_id}/{name}")
    async def icon_svg(set_id: str, name: str) -> Response:
        source = runtime.icons.icon_svg_source(set_id, name)
        if source is None:
            raise HTTPException(404, "Icon nicht gefunden")
        return Response(source, media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...), kind: str = "icon") -> dict[str, Any]:
        """Nimmt ein Bild an. ``kind=wallpaper`` legt es zu den Streifen.

        Die Ablage entscheidet sich beim Hochladen, weil nur dort bekannt
        ist, wofür das Bild gedacht war — hinterher sieht man es der Datei
        nicht mehr an.
        """
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Datei zu groß (max. 4 MB)")

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}:
            raise HTTPException(415, "Nur PNG, JPG, WEBP, GIF oder SVG")

        stem = SAFE_FILENAME.sub("-", Path(file.filename or "icon").stem)[:40] or "icon"
        filename = f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        target = paths.WALLPAPERS_DIR if kind == "wallpaper" else paths.UPLOADS_DIR
        target.mkdir(parents=True, exist_ok=True)
        (target / filename).write_bytes(data)
        return {"filename": filename, "url": f"/api/uploads/{filename}"}

    @app.get("/api/uploads/{filename}")
    async def get_upload(filename: str) -> FileResponse:
        candidate = paths.image_path(filename)
        if candidate is None:
            raise HTTPException(404, "Datei nicht gefunden")
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"

        # nosniff verhindert, dass der Browser den Typ überstimmt. Ein
        # hochgeladenes SVG kann <script> enthalten; im <img> läuft das nie,
        # beim *direkten* Aufruf der URL aber schon. ``sandbox`` schaltet die
        # Skriptausführung für diesen Fall ab, ohne die Bilddarstellung zu
        # stören — fremdes SVG bleibt damit ein Bild, kein Programm.
        headers = {"X-Content-Type-Options": "nosniff"}
        if candidate.suffix.lower() == ".svg":
            headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return FileResponse(candidate, media_type=media_type, headers=headers)

    @app.get("/api/uploads")
    async def list_uploads() -> list[dict[str, Any]]:
        """Eigene Bilder für Kacheln — ohne die Touchstrip-Streifen.

        Die liegen in einer eigenen Ablage und werden über ``/api/wallpapers``
        angeboten; in der Icon- und Hintergrundauswahl wären sie nur Ballast.
        """
        if not paths.UPLOADS_DIR.is_dir():
            return []
        return [
            {"filename": p.name, "url": f"/api/uploads/{p.name}", "size": p.stat().st_size}
            for p in sorted(paths.UPLOADS_DIR.iterdir())
            if p.is_file()
        ]

    # ======================================================================
    # Vorschau — dieselbe Render-Pipeline wie auf dem Gerät
    # ======================================================================

    @app.get("/api/preview/{page_id}/{input_type}/{index}.png")
    async def preview(
        page_id: str,
        input_type: str,
        index: int,
        deck: str | None = None,
        entry: int | None = None,
    ) -> Response:
        if input_type not in ("key", "dial"):
            raise HTTPException(400, "input_type muss 'key' oder 'dial' sein")
        try:
            image = await runtime.deck(deck).render_preview(
                page_id, input_type, index, entry
            )
        except Exception as exc:
            raise HTTPException(500, f"Vorschau fehlgeschlagen: {exc}") from exc
        buffer = io.BytesIO()
        image.convert("RGBA").save(buffer, format="PNG")
        return Response(
            buffer.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    # ======================================================================
    # Fehlerzustände
    # ======================================================================

    @app.get("/api/errors")
    async def get_errors() -> list[dict[str, Any]]:
        return runtime.errors

    @app.delete("/api/errors")
    async def clear_errors() -> dict[str, Any]:
        runtime.clear_errors()
        return {"ok": True}

    # ======================================================================
    # WebSocket
    # ======================================================================

    @app.websocket("/ws")
    async def websocket_endpoint(socket: WebSocket) -> None:
        # WebSockets unterliegen **nicht** der Same-Origin-Policy, und die
        # CORS-Middleware sieht den Handshake nie. Ohne diese Prüfung könnte
        # jede offene Webseite mitlesen, was hier durchläuft — Seriennummer,
        # Seitennamen, Plugin-Fehler samt Pfaden.
        #
        # Ohne ``Origin`` (eigenes Werkzeug, Kommandozeile) bleibt es frei:
        # Der Riegel richtet sich gegen den Browser, nicht gegen den Nutzer —
        # dieselbe Linie wie beim HTTP-Riegel.
        origin = socket.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            log.warning("WebSocket von fremder Herkunft abgelehnt: %s", origin)
            await socket.close(code=1008)
            return

        await socket.accept()
        try:
            await socket.send_json(
                {
                    "type": "hello",
                    "data": {
                        "device": runtime.device.info.as_dict(),
                        "current_page_id": runtime.current_page_id(),
                    },
                }
            )
            async with runtime.bus.subscribe() as queue:
                # Parallel lauschen, obwohl die GUI nichts schickt: Ein
                # Endpunkt, der nur sendet, merkt das Ende der Verbindung
                # erst beim nächsten Ereignis. Ohne angeschlossenes Deck
                # kommt lange keines — die Aufgabe bliebe hängen und mit ihr
                # das Herunterfahren des Servers, das auf offene Verbindungen
                # wartet. Gemessen am 2026-08-16 in einem frischen Container:
                # Der Shutdown kam nie zum Ende.
                lauscher = asyncio.create_task(socket.receive())
                try:
                    while True:
                        senden = asyncio.create_task(queue.get())
                        fertig, offen = await asyncio.wait(
                            {senden, lauscher}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if lauscher in fertig:
                            # Entweder eine Nachricht oder das Ende — beides
                            # heißt hier: Diese Runde ist vorbei.
                            senden.cancel()
                            nachricht = lauscher.result()
                            if nachricht.get("type") == "websocket.disconnect":
                                break
                            lauscher = asyncio.create_task(socket.receive())
                            continue
                        event = senden.result()
                        await socket.send_json({"type": event.type, "data": event.data})
                finally:
                    lauscher.cancel()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.debug("WebSocket beendet: %s", exc)

    # ======================================================================
    # Ausgelieferte GUI (falls gebaut)
    # ======================================================================

    gui_dist = paths.GUI_DIST
    if gui_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(gui_dist), html=True), name="gui")
    else:

        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "DECK//SWITCH",
                    "hint": "GUI noch nicht gebaut — 'npm run dev' im Ordner gui/",
                    "api": "/api/docs",
                }
            )

    return app


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def _belegte_plaetze(deck) -> list[str]:
    """``["key:0", "dial:2", …]`` — was auf der aktuellen Seite belegt ist."""
    seite = deck.current_page
    return [f"key:{index}" for index in seite.keys] + [
        f"dial:{index}" for index in seite.dials
    ]


def _has_icon(loaded) -> bool:
    if not loaded.manifest.icon:
        return False
    directory = loaded.directory.resolve()
    candidate = (directory / loaded.manifest.icon).resolve()
    return directory in candidate.parents and candidate.is_file()


def _plugins_payload(runtime: Runtime) -> list[dict[str, Any]]:
    """Plugins in der vom User festgelegten Reihenfolge.

    Was noch nicht in ``plugin_order`` steht (frisch installiert), landet
    hinten — so verschiebt ein neues Plugin nie die gewohnte Anordnung.
    """
    order = runtime.config.app.plugin_order
    position = {plugin_id: i for i, plugin_id in enumerate(order)}
    ordered = sorted(
        runtime.registry.plugins.values(),
        key=lambda p: (position.get(p.id, len(position)), p.id),
    )

    result = []
    for loaded in ordered:
        result.append(
            {
                "id": loaded.id,
                "manifest": loaded.manifest.model_dump(mode="json", by_alias=True),
                # Ob die Datei wirklich da ist, weiß nur das Backend — die
                # GUI soll kein Bild anfragen, das es nicht gibt.
                "has_icon": _has_icon(loaded),
                "builtin": loaded.builtin,
                "enabled": loaded.enabled,
                "loaded": loaded.instance is not None or loaded.is_iconset,
                "error": loaded.error,
                "config": runtime.config.plugin_settings.get(loaded.id, {}),
                # None bei Plugins ohne externe Verbindung — die GUI zeigt
                # dann auch keine Statusanzeige.
                "status": runtime.plugin_status(loaded.id),
            }
        )
    return result


def _require_page(session, page_id: str) -> Page:
    page = session.profile.pages.get(page_id)
    if page is None:
        raise HTTPException(404, "Seite nicht gefunden")
    return page


def _require_mapping(page: Page, input_type: str) -> dict:
    if input_type == "key":
        return page.keys
    if input_type == "dial":
        return page.dials
    raise HTTPException(400, "input_type muss 'key' oder 'dial' sein")


def _check_index(session, input_type: str, index: int) -> None:
    limit = (
        (session.device.info.key_count or 8)
        if input_type == "key"
        else (session.device.info.dial_count or 4)
    )
    if not 0 <= index < limit:
        raise HTTPException(400, f"Index {index} liegt außerhalb von 0..{limit - 1}")


def _check_move_target(profile, page_id: str, parent_id: str | None) -> None:
    """Verhindert, dass eine Seite unter sich selbst wandert.

    Ohne die Prüfung hinge der ganze Teilbaum in einem Ring und wäre von der
    Wurzel aus nicht mehr erreichbar — die Seiten blieben in der Config, aber
    weder GUI-Baum noch Zurück-Taste kämen je wieder dort hin.
    """
    if parent_id is None:
        return
    if parent_id not in profile.pages:
        raise HTTPException(404, "Übergeordnete Seite existiert nicht")
    if parent_id in profile.subtree_ids(page_id):
        raise HTTPException(400, "Eine Seite kann nicht unter sich selbst liegen")


def _drop_plugin_slots(runtime: Runtime, plugin_id: str) -> int:
    """Entfernt alles, was auf ein entferntes Plugin zeigt.

    Das ist mehr als die Belegung selbst: Zweitbelegungen, die Einträge
    eines Dial-Stacks und die Schritte einer Multi-Aktion können ebenso
    darauf zeigen. Bliebe eines davon stehen, wäre die Taste beim nächsten
    Druck eine Fehlerkachel.
    """
    count = 0
    for profile in runtime.config.profiles.values():
        for page in profile.pages.values():
            for mapping in (page.keys, page.dials):
                for index, slot in list(mapping.items()):
                    if slot.plugin_id == plugin_id:
                        mapping.pop(index, None)
                        count += 1
                        continue
                    count += _clean_slot(slot, plugin_id)
    return count


def _clean_slot(slot: Slot, plugin_id: str) -> int:
    """Zweige, Stack-Einträge und Schritte einer Belegung säubern."""
    count = 0
    for branch in ("long_press", "double_press", "turn_left", "turn_right"):
        nested = getattr(slot, branch)
        if nested is None:
            continue
        if nested.plugin_id == plugin_id:
            setattr(slot, branch, None)
            count += 1
        else:
            count += _clean_slot(nested, plugin_id)

    remaining = [entry for entry in slot.stack if entry.plugin_id != plugin_id]
    count += len(slot.stack) - len(remaining)
    slot.stack = remaining
    for entry in slot.stack:
        count += _clean_slot(entry, plugin_id)

    for field in ("steps", "steps_off"):
        steps = getattr(slot, field)
        kept = [s for s in steps if s.plugin_id != plugin_id]
        count += len(steps) - len(kept)
        setattr(slot, field, kept)
    return count


def _drop_references(profile, removed: set[str]) -> None:
    """Belegungen entfernen, die auf gelöschte Seiten zeigen."""
    for page in profile.pages.values():
        for mapping in (page.keys, page.dials):
            for index, slot in list(mapping.items()):
                if _points_to_removed(slot, removed):
                    mapping.pop(index, None)
                    continue
                # Auch Schritte einer Multi-Aktion können auf eine gelöschte
                # Seite zeigen — die Kette bliebe sonst mit einem toten
                # Schritt stehen.
                for field in ("steps", "steps_off"):
                    steps = getattr(slot, field)
                    setattr(
                        slot,
                        field,
                        [
                            s
                            for s in steps
                            if not (
                                s.plugin_id == "streamdeck"
                                and s.settings.get("page_id") in removed
                            )
                        ],
                    )


def _points_to_removed(slot: Slot, removed: set[str]) -> bool:
    return slot.plugin_id == "streamdeck" and slot.settings.get("page_id") in removed
