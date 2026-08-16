"""Netz-Decks: ein zweiter, absichtlich winziger Server.

**Warum nicht einfach den vorhandenen Server ins Netz stellen?** Weil der
alles darf: Belegungen ändern, Plugins installieren, die Konfiguration
exportieren — samt der Zugangsdaten, die in den Plugin-Einstellungen
stehen. Er bindet deshalb ausschließlich an ``127.0.0.1``, und dabei bleibt
es.

Ins Netz geht stattdessen diese Anwendung hier. Sie kann genau drei Dinge:
anmelden, Kacheln zeigen, Tasten drücken. Es gibt schlicht keinen
Endpunkt, mit dem sich etwas ändern ließe — der Schutz liegt in dem, was
nicht existiert, und nicht in einer Regel, die jemand später falsch
anpasst.

Erreichbar ist ein Deck nur, wenn es
``kind == "network"`` ist, eingeschaltet wurde *und* ein Passwort hat.
Ohne Passwort bleibt es zu; ein Deck, das einen fremden Rechner steuert,
darf nicht versehentlich offen stehen.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import netauth
from .virtualdeck import VirtualDevice

log = logging.getLogger(__name__)

#: Die Seite, die der Gast im Browser bekommt.
CLIENT_HTML = Path(__file__).resolve().parent / "web" / "netdeck.html"


class Anmeldung(BaseModel):
    deck: str
    password: str


class Eingabe(BaseModel):
    input_type: str = "key"
    index: int = 0
    #: ``down``/``up`` einzeln, ``click`` für beides, ``rotate`` fürs Drehen.
    action: str = "click"
    delta: int = 0


def create_net_app(runtime, sitzungen: netauth.Sitzungen) -> FastAPI:
    app = FastAPI(
        title="DECK//SWITCH — Netz-Deck",
        # Keine Schnittstellenbeschreibung ins Netz: Sie verrät den Aufbau
        # und lädt zum Stöbern ein.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Kein CORS. Die Seite kommt vom selben Server wie die Daten; alles
    # andere hat hier nichts zu suchen.

    def deck_aus_token(authorization: str = Header(default="")) -> Any:
        """Löst das Token auf und liefert das Deck — oder wirft 401."""
        token = ""
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        deck_key = sitzungen.pruefe_token(token)
        if deck_key is None:
            raise HTTPException(401, "Nicht angemeldet")
        deck = _erreichbares_deck(runtime, deck_key)
        if deck is None:
            # Das Deck wurde abgeschaltet oder entfernt, während jemand
            # angemeldet war. Dann endet die Sitzung sofort mit.
            sitzungen.verwerfen(token)
            raise HTTPException(403, "Dieses Deck wird nicht mehr angeboten")
        return deck

    # -- Seite -------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def start() -> HTMLResponse:
        """Die Auswahl. Zeigt nur Namen — nie Belegungen oder Kacheln."""
        eintraege = "".join(
            f'<li><a href="/deck/{deck.key}">{_escape(deck.label)}</a></li>'
            for deck in runtime.decks_in_order()
            if _erreichbar(deck)
        )
        if not eintraege:
            eintraege = "<li>Zurzeit wird kein Deck angeboten.</li>"
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>DECK//SWITCH</title>"
            "<style>body{background:#0e0e11;color:#e5e7eb;font-family:system-ui;"
            "padding:2rem;line-height:1.8}a{color:#60a5fa}</style>"
            f"<h1>DECK//SWITCH</h1><ul>{eintraege}</ul>"
        )

    @app.get("/deck/{key}", response_class=HTMLResponse)
    async def client(key: str) -> Response:
        deck = _erreichbares_deck(runtime, key)
        if deck is None:
            raise HTTPException(404, "Dieses Deck gibt es hier nicht")
        if not CLIENT_HTML.is_file():
            raise HTTPException(500, "Client-Seite fehlt")
        # Der Name wird eingesetzt statt nachgeladen: Vor der Anmeldung gibt
        # es kein Token, und dafür einen zweiten offenen Endpunkt zu bauen
        # wäre mehr Angriffsfläche für einen Namen, der auf der Übersicht
        # ohnehin steht.
        seite = CLIENT_HTML.read_text(encoding="utf-8")
        seite = seite.replace("{{DECKNAME}}", _escape(deck.label))
        return HTMLResponse(seite)

    # -- Anmelden ----------------------------------------------------------

    @app.post("/api/login")
    async def login(payload: Anmeldung, request: Request) -> dict[str, Any]:
        adresse = request.client.host if request.client else "?"

        sperre = sitzungen.gesperrt_bis(adresse)
        if sperre:
            raise HTTPException(429, "Zu viele Fehlversuche. Bitte später erneut.")

        deck = _erreichbares_deck(runtime, payload.deck)
        # Auch bei unbekanntem Deck erst das Passwort prüfen lassen und
        # dieselbe Meldung geben: Sonst verriete die Antwort, welche Decks
        # es gibt.
        gespeichert = deck.binding.password_hash if deck is not None else ""
        if not netauth.pruefe_passwort(payload.password, gespeichert):
            sitzungen.melde_fehlversuch(adresse)
            await asyncio.sleep(netauth.STRAFE_S)
            log.warning("Fehlgeschlagene Anmeldung von %s", adresse)
            raise HTTPException(401, "Deck oder Passwort stimmt nicht")

        sitzungen.melde_erfolg(adresse)
        token, gueltig = sitzungen.neues_token(deck.key)
        log.info("Netz-Deck '%s': Anmeldung von %s", deck.label, adresse)
        return {"token": token, "expires_in": gueltig, "name": deck.label}

    @app.post("/api/logout")
    async def logout(authorization: str = Header(default="")) -> dict[str, bool]:
        if authorization.lower().startswith("bearer "):
            sitzungen.verwerfen(authorization[7:].strip())
        return {"ok": True}

    # -- Anzeigen und drücken ----------------------------------------------

    @app.get("/api/deck")
    async def layout(deck=Depends(deck_aus_token)) -> dict[str, Any]:
        """Alles zum Zeichnen — dasselbe, was auch ein Overlay bekäme."""
        device = deck.device
        return {
            "name": deck.label,
            "columns": deck.binding.columns,
            "rows": deck.binding.rows,
            "dials": deck.binding.dials,
            "tile_size": deck.binding.key_size,
            "revision": device.revision,
            "versions": device.versions(),
            "filled": _belegt(deck),
        }

    @app.get("/api/tile/{input_type}/{index}.png")
    async def kachel(input_type: str, index: int, deck=Depends(deck_aus_token)) -> Response:
        daten = deck.device.image(input_type, index)
        if daten is None:
            raise HTTPException(404, "Für diese Kachel gibt es noch kein Bild")
        return Response(daten, media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/input")
    async def eingabe(payload: Eingabe, deck=Depends(deck_aus_token)) -> dict[str, bool]:
        """Ein Druck aus dem Netz — derselbe Weg wie am echten Gerät."""
        device = deck.device
        if payload.action == "rotate":
            device.rotate(payload.index, payload.delta or 1)
        elif payload.action == "down":
            device.press(payload.input_type, payload.index, True)
        elif payload.action == "up":
            device.press(payload.input_type, payload.index, False)
        else:
            device.press(payload.input_type, payload.index, True)
            await asyncio.sleep(0.02)
            device.press(payload.input_type, payload.index, False)
        return {"ok": True}

    return app


class NetzService:
    """Startet und stoppt den Netz-Server, je nachdem ob er gebraucht wird."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.sitzungen = netauth.Sitzungen()
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None
        self._port: int = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- An und aus --------------------------------------------------------

    async def sync(self) -> None:
        """Bringt den Server in den Zustand, den die Konfiguration verlangt.

        Wird nach jeder Änderung an den Decks gerufen. Läuft nichts mehr im
        Netz, hört der Server auf zu lauschen — ein offener Port ohne Zweck
        ist eine Angriffsfläche ohne Gegenwert.
        """
        gebraucht = any(_erreichbar(deck) for deck in self.runtime.decks.values())
        port = self.runtime.config.app.network_port

        if self.running and (not gebraucht or port != self._port):
            await self.stop()
        if gebraucht and not self.running:
            await self.start(port)

    async def start(self, port: int) -> None:
        if self.running:
            return
        app = create_net_app(self.runtime, self.sitzungen)
        config = uvicorn.Config(
            app,
            # Hier ist ``0.0.0.0`` beabsichtigt: Genau diese Anwendung soll
            # aus dem Netz erreichbar sein. Der Server mit der vollen API
            # bleibt davon unberührt auf 127.0.0.1.
            host="0.0.0.0",  # noqa: S104
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._port = port
        self._task = asyncio.create_task(self._server.serve())
        # Kurz Luft lassen, damit ein belegter Port sofort auffällt statt
        # erst beim ersten Zugriff.
        await asyncio.sleep(0.2)
        if self._task.done():
            self._task = None
            log.error("Netz-Server auf Port %s ließ sich nicht starten", port)
            return
        log.info("Netz-Decks erreichbar auf Port %s", port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._server = None
        self._task = None
        self._port = 0

    # -- Auskunft für die Oberfläche ---------------------------------------

    def urls(self, deck_key: str) -> list[str]:
        """Adressen, unter denen das Deck im Netz zu erreichen ist."""
        if not self.running:
            return []
        return [f"http://{ip}:{self._port}/deck/{deck_key}" for ip in lan_adressen()]

    def set_password(self, deck_key: str, passwort: str) -> bool:
        """Setzt oder entfernt das Passwort. Wirft alle Sitzungen raus."""
        deck = self.runtime.decks.get(deck_key)
        if deck is None or not deck.binding.is_network:
            raise RuntimeError("Kein Netz-Deck")
        deck.binding.password_hash = netauth.hash_passwort(passwort) if passwort else ""
        # Ein Passwortwechsel muss auch die trennen, die schon drin sind —
        # sonst wechselt man es genau in dem Moment umsonst, in dem es zählt.
        self.sitzungen.alle_verwerfen(deck_key)
        self.runtime.save_config()
        return bool(deck.binding.password_hash)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _erreichbar(deck) -> bool:
    """Ob dieses Deck im Netz angeboten wird — die eine maßgebliche Regel."""
    binding = deck.binding
    return (
        binding.is_network
        and binding.network_enabled
        and bool(binding.password_hash)
        and isinstance(deck.device, VirtualDevice)
    )


def _erreichbares_deck(runtime, key: str):
    deck = runtime.decks.get(key)
    return deck if deck is not None and _erreichbar(deck) else None


def _belegt(deck) -> list[str]:
    seite = deck.current_page
    return [f"key:{i}" for i in seite.keys] + [f"dial:{i}" for i in seite.dials]


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def lan_adressen() -> list[str]:
    """IP-Adressen dieses Rechners im Netz — für die Anzeige in der GUI."""
    adressen: set[str] = set()
    try:
        for eintrag in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = eintrag[4][0]
            if not ip.startswith("127."):
                adressen.add(ip)
    except OSError:
        pass

    if not adressen:
        # Der Hostname löst nicht immer auf. Dann fragen wir das Betriebs-
        # system, über welche Adresse es nach draußen ginge — verschickt
        # wird dabei nichts, UDP baut keine Verbindung auf.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.connect(("192.0.2.1", 9))  # dokumentierte Testadresse
                adressen.add(probe.getsockname()[0])
            except OSError:
                pass
    return sorted(adressen)
