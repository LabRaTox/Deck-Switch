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
import contextlib
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import netauth
from .virtualdeck import VirtualDevice
from . import texte

log = logging.getLogger(__name__)

#: Die Seite, die der Gast im Browser bekommt.
CLIENT_HTML = Path(__file__).resolve().parent / "web" / "netdeck.html"

#: Mindestlänge eines Passworts für ein Netz-Deck.
MIN_PASSWORT = 4

#: So lange darf eine Sitzung, die Tasten hält, ohne jede Anfrage bleiben.
#: Die Seite fragt etwa alle halbe Sekunde nach dem Stand, ein Tab im
#: Hintergrund immer noch einmal je Sekunde. Bleibt sie länger stumm, ist
#: der Browser weg, und das Loslassen käme nie.
WACHHUND_S = 5.0


class StillerServer(uvicorn.Server):
    """uvicorn ohne eigene Signal-Handler.

    ``uvicorn.Server.serve`` merkt sich beim Start die gerade gültigen
    Handler für SIGINT und SIGTERM und setzt sie beim Ende zurück. Laufen
    mehrere Server in einem Loop und enden sie nicht in umgekehrter
    Reihenfolge, steht danach ein veralteter Handler da, im schlimmsten Fall
    der Standard, der den Prozess ohne Aufräumen beendet. Die Signale
    verwaltet deshalb allein der Einstiegspunkt über den Event-Loop.
    """

    def capture_signals(self):  # type: ignore[override]
        return contextlib.nullcontext()


class Anmeldung(BaseModel):
    deck: str
    password: str


class Eingabe(BaseModel):
    input_type: str = "key"
    index: int = 0
    #: ``down``/``up`` einzeln, ``click`` für beides, ``rotate`` fürs Drehen.
    action: str = "click"
    delta: int = 0
    #: Laufende Nummer vom Browser, je Eingabe steigend. Drücken und
    #: Loslassen sind getrennte Anfragen und können sich überholen; eine
    #: Meldung, die älter ist als die zuletzt angenommene, zählt nicht mehr.
    seq: int | None = None


@dataclass
class _Stand:
    """Was eine Sitzung gerade gedrückt hält."""

    deck: Any
    zuletzt: float = field(default_factory=time.monotonic)
    #: (Eingabeart, Index) → letzte angenommene Nummer
    folge: dict[tuple[str, int], int] = field(default_factory=dict)
    gehalten: set[tuple[str, int]] = field(default_factory=set)


class NetzTasten:
    """Führt Buch, welche Tasten über das Netz gehalten werden.

    Am Gerät folgt auf jedes Drücken ein Loslassen, im Netz nicht: Die
    Anfrage kann verloren gehen, der Browser zugeklappt werden, die Sitzung
    enden. Hält die Taste dann Push-to-Talk oder eine Umschalttaste, bleibt
    das hängen. Deshalb merkt sich jede Sitzung, was sie drückt, und lässt
    es los, sobald sie endet oder verstummt.
    """

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._staende: dict[str, _Stand] = {}

    def lebenszeichen(self, token: str) -> None:
        stand = self._staende.get(token)
        if stand is not None:
            stand.zuletzt = time.monotonic()

    def eingabe(self, token: str, deck, payload: Eingabe) -> bool:
        """Wendet ein Drücken oder Loslassen an. ``False`` = verworfen."""
        stand = self._staende.get(token)
        if stand is None or stand.deck is not deck:
            if stand is not None:
                self._loslassen(stand)
            stand = self._staende[token] = _Stand(deck)
        stand.zuletzt = time.monotonic()

        ziel = (payload.input_type, payload.index)
        if payload.seq is not None:
            if payload.seq <= stand.folge.get(ziel, -1):
                return False
            stand.folge[ziel] = payload.seq

        device = deck.device
        if payload.action == "down":
            if ziel in stand.gehalten:
                return False
            stand.gehalten.add(ziel)
            device.press(payload.input_type, payload.index, True)
        elif payload.action == "up":
            # Ohne vorheriges Drücken dieser Sitzung gibt es nichts
            # loszulassen, etwa wenn das Loslassen das Drücken überholt hat.
            if ziel not in stand.gehalten:
                return False
            stand.gehalten.discard(ziel)
            device.press(payload.input_type, payload.index, False)
        return True

    def sitzung_endet(self, token: str, _deck_key: str = "") -> None:
        stand = self._staende.pop(token, None)
        if stand is not None:
            self._loslassen(stand)

    def alle_loslassen(self) -> None:
        for token in list(self._staende):
            self.sitzung_endet(token)

    def pruefen(self, sitzungen: netauth.Sitzungen | None = None) -> None:
        """Lässt los, was verstummte oder nicht mehr erreichbare Sitzungen halten."""
        jetzt = time.monotonic()
        for token, stand in list(self._staende.items()):
            erreichbar = _erreichbares_deck(self.runtime, stand.deck.key) is stand.deck
            if not erreichbar:
                if sitzungen is not None:
                    sitzungen.verwerfen(token)
                self.sitzung_endet(token)
            elif stand.gehalten and jetzt - stand.zuletzt > WACHHUND_S:
                log.info("Netz-Deck '%s': Sitzung verstummt, gehaltene Tasten losgelassen",
                         stand.deck.label)
                self._loslassen(stand)

    async def wache(self, sitzungen: netauth.Sitzungen) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                self.pruefen(sitzungen)
            except Exception:  # noqa: BLE001 - die Wache darf nicht sterben
                log.exception("Prüfen der gehaltenen Netz-Tasten fehlgeschlagen")

    def _loslassen(self, stand: _Stand) -> None:
        gehalten, stand.gehalten = stand.gehalten, set()
        for art, index in sorted(gehalten):
            with contextlib.suppress(Exception):
                stand.deck.device.press(art, index, False)
        if gehalten and self.runtime.decks.get(stand.deck.key) is not stand.deck:
            # Das Deck ist schon entfernt, seine Eingaben laufen womöglich
            # nicht mehr durch. Dann wenigstens gehaltene Tasten freigeben.
            with contextlib.suppress(Exception):
                self.runtime.input.release_all()

    @staticmethod
    def fuer(runtime, sitzungen: netauth.Sitzungen) -> "NetzTasten":
        """Die Buchführung zu diesen Sitzungen, notfalls eine neue."""
        netz = getattr(runtime, "netz", None)
        if netz is not None and getattr(netz, "sitzungen", None) is sitzungen:
            return netz.tasten
        tasten = NetzTasten(runtime)
        sitzungen.bei_ende.append(tasten.sitzung_endet)
        return tasten


def create_net_app(
    runtime, sitzungen: netauth.Sitzungen, tasten: NetzTasten | None = None
) -> FastAPI:
    if tasten is None:
        tasten = NetzTasten.fuer(runtime, sitzungen)

    @contextlib.asynccontextmanager
    async def lebenslauf(_app):
        wache = asyncio.create_task(tasten.wache(sitzungen), name="netz-tasten")
        try:
            yield
        finally:
            wache.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wache
            # Ohne Server kommt kein Loslassen mehr an.
            tasten.alle_loslassen()

    app = FastAPI(
        title="DECK//SWITCH · Netz-Deck",
        # Keine Schnittstellenbeschreibung ins Netz: Sie verrät den Aufbau
        # und lädt zum Stöbern ein.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lebenslauf,
    )

    # Kein CORS. Die Seite kommt vom selben Server wie die Daten; alles
    # andere hat hier nichts zu suchen.

    def sitzung_aus_token(authorization: str = Header(default="")) -> tuple[str, Any]:
        """Löst das Token auf und liefert Token und Deck — oder wirft 401."""
        token = ""
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        deck_key = sitzungen.pruefe_token(token)
        if deck_key is None:
            raise HTTPException(401, texte.t("netserver.nicht_angemeldet"))
        deck = _erreichbares_deck(runtime, deck_key)
        if deck is None:
            # Das Deck wurde abgeschaltet oder entfernt, während jemand
            # angemeldet war. Dann endet die Sitzung sofort mit.
            sitzungen.verwerfen(token)
            raise HTTPException(403, texte.t("netserver.dieses_deck_wird_nicht"))
        tasten.lebenszeichen(token)
        return token, deck

    def deck_aus_token(sitzung: tuple[str, Any] = Depends(sitzung_aus_token)) -> Any:
        return sitzung[1]

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
            eintraege = "<li>" + texte.t("netserver.zurzeit_kein_deck_angeboten") + "</li>"
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
            raise HTTPException(404, texte.t("netserver.dieses_deck_gibt_nicht"))
        if not CLIENT_HTML.is_file():
            raise HTTPException(500, texte.t("netserver.client_seite_fehlt"))
        # Der Name wird eingesetzt statt nachgeladen: Vor der Anmeldung gibt
        # es kein Token, und dafür einen zweiten offenen Endpunkt zu bauen
        # wäre mehr Angriffsfläche für einen Namen, der auf der Übersicht
        # ohnehin steht.
        seite = CLIENT_HTML.read_text(encoding="utf-8")
        seite = seite.replace("{{DECKNAME}}", _escape(deck.label))
        return HTMLResponse(_setze_texte(seite))

    # -- Anmelden ----------------------------------------------------------

    @app.post("/api/login")
    async def login(payload: Anmeldung, request: Request) -> dict[str, Any]:
        adresse = request.client.host if request.client else "?"

        deck = _erreichbares_deck(runtime, payload.deck)
        # Gezählt wird je Adresse *und* Deck. Unbekannte Decks laufen unter
        # einem gemeinsamen Eintrag, sonst füllte jeder erfundene Name den
        # Speicher.
        ziel = deck.key if deck is not None else ""

        sperre = sitzungen.gesperrt_bis(adresse, ziel)
        if sperre:
            raise HTTPException(429, texte.t("netserver.viele_fehlversuche_bitte_spaeter"))

        # Auch bei unbekanntem Deck dieselbe Meldung geben: Sonst verriete
        # die Antwort, welche Decks es gibt.
        gespeichert = deck.binding.password_hash if deck is not None else ""
        # Der Versuch zählt schon *vor* dem Prüfen. Das Prüfen läuft in einem
        # Thread, damit der Schlüssel den Loop nicht anhält; ohne Vormerken
        # kämen parallele Anfragen alle an der Sperre vorbei, bevor die erste
        # ihren Fehlversuch einträgt.
        versuch = sitzungen.melde_fehlversuch(adresse, ziel)
        stimmt = await asyncio.to_thread(
            netauth.pruefe_passwort, payload.password, gespeichert
        )
        if not stimmt:
            await asyncio.sleep(netauth.STRAFE_S)
            log.warning("Fehlgeschlagene Anmeldung von %s", adresse)
            raise HTTPException(401, texte.t("netserver.deck_oder_passwort_stimmt"))

        sitzungen.melde_erfolg(adresse, ziel, versuch)
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
            raise HTTPException(404, texte.t("netserver.diese_kachel_gibt_kein"))
        return Response(daten, media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/input")
    async def eingabe(
        payload: Eingabe, sitzung: tuple[str, Any] = Depends(sitzung_aus_token)
    ) -> dict[str, bool]:
        """Ein Druck aus dem Netz — derselbe Weg wie am echten Gerät."""
        token, deck = sitzung
        device = deck.device
        if payload.action == "rotate":
            device.rotate(payload.index, payload.delta or 1)
        elif payload.action in ("down", "up"):
            return {"ok": tasten.eingabe(token, deck, payload)}
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
        self.tasten = NetzTasten(runtime)
        self.sitzungen.bei_ende.append(self.tasten.sitzung_endet)
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None
        self._port: int = 0
        #: Der tatsächlich belegte Port. Weicht nur bei ``0`` vom
        #: eingestellten ab.
        self.bound_port: int = 0

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
        # Ein abgeschaltetes oder entferntes Deck lässt sofort los, was über
        # das Netz gedrückt war, nicht erst beim nächsten Rundgang der Wache.
        self.tasten.pruefen(self.sitzungen)
        gebraucht = any(_erreichbar(deck) for deck in self.runtime.decks.values())
        port = self.runtime.config.app.network_port

        if self.running and (not gebraucht or port != self._port):
            await self.stop()
        if gebraucht and not self.running:
            await self.start(port)

    async def start(self, port: int) -> None:
        if self.running:
            return
        # Den Port selbst belegen statt uvicorn das tun zu lassen: Scheitert
        # dort das Binden, ruft uvicorn ``sys.exit`` auf, und ein
        # ``SystemExit`` aus einem Task beendet den ganzen Event-Loop samt
        # Gerätesteuerung. Hier bleibt es ein gewöhnlicher Fehler.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Hier ist ``0.0.0.0`` beabsichtigt: Genau diese Anwendung soll
            # aus dem Netz erreichbar sein. Der Server mit der vollen API
            # bleibt davon unberührt auf 127.0.0.1.
            sock.bind(("0.0.0.0", port))  # noqa: S104
            sock.setblocking(False)
        except (OSError, OverflowError) as exc:
            sock.close()
            log.error("Netz-Server auf Port %s ließ sich nicht starten: %s", port, exc)
            return

        app = create_net_app(self.runtime, self.sitzungen)
        config = uvicorn.Config(app, log_level="warning", access_log=False)
        self._server = StillerServer(config)
        self._port = port
        self.bound_port = sock.getsockname()[1]
        self._task = asyncio.create_task(self._serve(self._server, sock), name="netz-server")
        # Kurz Luft lassen, damit ein Fehler beim Hochfahren sofort auffällt.
        await asyncio.sleep(0.2)
        if self._task.done():
            self._task = None
            self._server = None
            self._port = 0
            log.error("Netz-Server auf Port %s ließ sich nicht starten", port)
            return
        log.info("Netz-Decks erreichbar auf Port %s", self.bound_port)

    @staticmethod
    async def _serve(server: uvicorn.Server, sock: socket.socket) -> None:
        """Lässt den Server laufen. Ein ``SystemExit`` von uvicorn endet hier."""
        try:
            await server.serve(sockets=[sock])
        except SystemExit as exc:
            log.error("Netz-Server hat sich beendet (Code %s)", exc.code)
        finally:
            sock.close()

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
        self.bound_port = 0

    # -- Auskunft für die Oberfläche ---------------------------------------

    def urls(self, deck_key: str) -> list[str]:
        """Adressen, unter denen das Deck im Netz zu erreichen ist."""
        if not self.running:
            return []
        return [f"http://{ip}:{self.bound_port}/deck/{deck_key}" for ip in lan_adressen()]

    def set_password(self, deck_key: str, passwort: str) -> bool:
        """Setzt oder entfernt das Passwort. Wirft alle Sitzungen raus."""
        deck = self.runtime.decks.get(deck_key)
        if deck is None or not deck.binding.is_network:
            raise RuntimeError(texte.t("netserver.kein_netz_deck"))
        if passwort and len(passwort) < MIN_PASSWORT:
            raise ValueError(texte.t("netserver.passwort_zu_kurz", n=MIN_PASSWORT))
        deck.binding.password_hash = netauth.hash_passwort(passwort) if passwort else ""
        # Ein Passwortwechsel muss auch die trennen, die schon drin sind —
        # sonst wechselt man es genau in dem Moment umsonst, in dem es zählt.
        self.sitzungen.alle_verwerfen(deck_key)
        self.runtime.save_config()
        return bool(deck.binding.password_hash)


# ---------------------------------------------------------------------------
# Hilfen

_PLATZHALTER = re.compile(r"\{\{([TJ]):([a-z_.]+)\}\}")


def _setze_texte(seite: str) -> str:
    """Setzt die Texte der Seite in der eingestellten Sprache ein.

    ``{{T:schluessel}}`` steht in HTML und wird maskiert, ``{{J:schluessel}}``
    steht in Skript und wird zu einem JavaScript-String.
    """

    def ersetze(treffer: re.Match[str]) -> str:
        text = str(texte.t(treffer.group(2)))
        if treffer.group(1) == "T":
            return _escape(text)
        return json.dumps(text, ensure_ascii=False).replace("</", "<\\/")

    seite = seite.replace("{{LANG}}", texte.sprache())
    return _PLATZHALTER.sub(ersetze, seite)
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
