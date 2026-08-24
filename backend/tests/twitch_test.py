"""Prüft jede Twitch-Aktion gegen einen nachgebauten Helix-Server.

Keine Attrappe der eigenen Aufrufe: Das Plugin spricht hier wirklich HTTP,
nur eben mit einem Server, der in dieser Datei steht. Geprüft wird, was
tatsächlich über den Draht geht — Methode, Pfad, Abfrage, Rumpf. Genau
daran scheitert eine API-Anbindung nämlich: nicht am Code, sondern an einem
Feld, das im falschen Teil der Anfrage steht.

Twitch selbst wird dabei nicht befragt. Was der Server hier antwortet, ist
nach Twitchs Dokumentation nachgebaut und so knapp gehalten wie möglich —
geprüft wird, was hinausgeht, nicht was zurückkommt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/twitch_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import socket
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "twitch"

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

twitchmod = lade(PLUGIN_DIR)
# Dieselbe Datei, die auch das Plugin benutzt — nur so wirkt das
# Umbiegen der Adressen unten.
apimod = nachbar(twitchmod, "twitch_api")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# --------------------------------------------------------------------------
# Der nachgebaute Server
# --------------------------------------------------------------------------

#: Was der Server auf GET antwortet. Wird je Prüfung umgestellt.
ANTWORTEN: dict[str, dict] = {}
#: Jede Anfrage, die hereinkam.
PROTOKOLL: list[dict] = []
#: Pfade, die mit diesem HTTP-Code antworten sollen statt mit 200.
FEHLERCODE: dict[str, int] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102 — sonst rauscht die Ausgabe zu
        pass

    def _antworte(self, daten, code=200):
        roh = json.dumps(daten).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def _merke(self, methode):
        pfad, _, abfrage = self.path.partition("?")
        laenge = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(laenge) if laenge else b""
        rumpf = None
        if roh:
            try:
                rumpf = json.loads(roh)
            except json.JSONDecodeError:
                rumpf = dict(urllib.parse.parse_qsl(roh.decode()))
        eintrag = {
            "methode": methode,
            "pfad": pfad.replace("/helix", "", 1).replace("/id", "", 1),
            "abfrage": dict(urllib.parse.parse_qsl(abfrage)),
            "rumpf": rumpf,
            "client_id": self.headers.get("Client-Id"),
            "auth": self.headers.get("Authorization"),
        }
        PROTOKOLL.append(eintrag)
        return eintrag

    def do_GET(self):  # noqa: N802 — Name gibt die Bibliothek vor
        eintrag = self._merke("GET")
        self._antworte(ANTWORTEN.get(eintrag["pfad"], {"data": []}))

    def do_POST(self):  # noqa: N802
        eintrag = self._merke("POST")
        code = FEHLERCODE.get(eintrag["pfad"])
        self._antworte(ANTWORTEN.get(eintrag["pfad"], {"data": []}), code or 200)

    def do_PATCH(self):  # noqa: N802
        eintrag = self._merke("PATCH")
        self._antworte(ANTWORTEN.get(eintrag["pfad"], {"data": []}))

    def do_DELETE(self):  # noqa: N802
        self._merke("DELETE")
        self.send_response(204)
        self.end_headers()


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def letzte(methode=None, pfad=None):
    """Die jüngste Anfrage, die passt."""
    for eintrag in reversed(PROTOKOLL):
        if methode and eintrag["methode"] != methode:
            continue
        if pfad and eintrag["pfad"] != pfad:
            continue
        return eintrag
    return None


# --------------------------------------------------------------------------

manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()


class FakeRuntime:
    def request_redraw(self, ctx=None):
        pass

    def notify(self, *a, **k):
        pass


services = Services(
    audio=None, icons=icons, render=RenderService(icons), runtime=FakeRuntime(),
    config=config, plugin_dir=PLUGIN_DIR,
)


def ctx_for(action, settings, *, index=0, input_type="key"):
    slot = Slot(plugin_id="twitch", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


async def main() -> int:
    port = freier_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    apimod.HELIX = f"http://127.0.0.1:{port}/helix"
    apimod.ID_BASIS = f"http://127.0.0.1:{port}/id"

    plugin = twitchmod.TwitchPlugin(manifest, services)
    plugin.api.client_id = "pruef-client"
    twitchmod.EINGEBAUTE_CLIENT_ID = "pruef-client"

    try:
        print("== Anmeldung über Gerätecode ==")
        ANTWORTEN["/device"] = {
            "device_code": "GERAET-1", "user_code": "ABCD-1234",
            "verification_uri": "https://www.twitch.tv/activate",
            "expires_in": 1800, "interval": 5,
        }
        ANTWORTEN["/token"] = {
            "access_token": "zugriff-1", "refresh_token": "erneuern-1",
            "expires_in": 14000,
        }
        ANTWORTEN["/users"] = {"data": [{"id": "42", "login": "labratox",
                                         "display_name": "LabRaTox"}]}

        start = await plugin.gui_command("verbinden", {})
        check("der Code kommt zurück", start["code"] == "ABCD-1234", str(start))
        check("mit der Adresse zum Eintippen",
              start["url"] == "https://www.twitch.tv/activate")
        gefragt = letzte("POST", "/device")
        check("gefragt wird mit der Client-ID",
              gefragt["rumpf"]["client_id"] == "pruef-client", str(gefragt["rumpf"]))
        check("und mit allen Berechtigungen",
              gefragt["rumpf"]["scopes"] == " ".join(apimod.SCOPES),
              gefragt["rumpf"]["scopes"][:60] + " …")
        check("ein Secret wird nirgends mitgeschickt",
              "client_secret" not in (gefragt["rumpf"] or {}))

        # Twitch drückt „noch nicht bestätigt" als 400 mit der Kennung
        # authorization_pending aus. Vorher galt hier *jede* 400 als Warten
        # — eine falsche Client-ID hätte den Dialog bis zum Ablauf des Codes
        # wartend stehen lassen, ohne zu sagen, was los ist.
        ANTWORTEN["/token"] = {"status": 400, "message": "authorization_pending"}
        FEHLERCODE["/token"] = 400
        wartet = await plugin.gui_command("nachfragen", {})
        check("noch nicht bestätigt heißt warten",
              wartet == {"angemeldet": False, "wartet": True}, json.dumps(wartet))

        ANTWORTEN["/token"] = {"status": 400, "message": "invalid client"}
        try:
            await plugin.gui_command("nachfragen", {})
            check("eine echte Ablehnung wird gemeldet", False, "kam ohne Fehler durch")
        except twitchmod.TwitchError as exc:
            check("eine echte Ablehnung wird gemeldet", "invalid client" in str(exc),
                  str(exc)[:70])
        FEHLERCODE.clear()
        ANTWORTEN["/token"] = {
            "access_token": "zugriff-1", "refresh_token": "erneuern-1",
            "expires_in": 14000,
        }

        fertig = await plugin.gui_command("nachfragen", {})
        check("nach dem Eintippen ist man angemeldet", fertig["angemeldet"], str(fertig))
        check("und das Konto steht fest", fertig["konto"] == "LabRaTox", str(fertig))
        check("das Token liegt nur für den Benutzer lesbar",
              oct(twitchmod.TOKEN_DATEI.stat().st_mode)[-3:] == "600",
              oct(twitchmod.TOKEN_DATEI.stat().st_mode)[-3:])
        check("jeder Helix-Aufruf trägt die Client-ID",
              letzte("GET", "/users")["client_id"] == "pruef-client")
        check("und das Token",
              letzte("GET", "/users")["auth"] == "Bearer zugriff-1")

        print("\n== Ein erneuertes Token landet sofort auf der Platte ==")
        # Twitch tauscht beim Erneuern auch das Refresh-Token aus und macht
        # das alte ungültig. Wer das neue nur im Speicher hält, hat auf der
        # Platte eine verbrannte Anmeldung — im Betrieb merkt man nichts,
        # beim nächsten Start kommt „Invalid refresh token". Genau so
        # passiert am 2026-08-24.
        ANTWORTEN["/token"] = {
            "access_token": "zugriff-2", "refresh_token": "erneuern-2",
            "expires_in": 14000,
        }
        plugin.api.erneuere()
        auf_platte = json.loads(twitchmod.TOKEN_DATEI.read_text())
        check("das neue Zugriffstoken steht in der Datei",
              auf_platte["access_token"] == "zugriff-2", auf_platte["access_token"])
        check("und das neue Refresh-Token auch",
              auf_platte["refresh_token"] == "erneuern-2", auf_platte["refresh_token"])
        check("im Speicher steht dasselbe",
              plugin.api.anmeldung.refresh_token == "erneuern-2",
              plugin.api.anmeldung.refresh_token)

        print("\n== Was jede Aktion wirklich schickt ==")
        ANTWORTEN["/search/categories"] = {"data": [{"id": "509658", "name": "Just Chatting"}]}
        ANTWORTEN["/streams"] = {"data": []}
        ANTWORTEN["/channels"] = {"data": [{"title": "Alter Titel", "game_name": "Nix"}]}
        ANTWORTEN["/channels/followers"] = {"total": 1234, "data": []}
        ANTWORTEN["/chat/settings"] = {"data": [{"subscriber_mode": False,
                                                 "slow_mode": False}]}
        ANTWORTEN["/polls"] = {"data": []}
        ANTWORTEN["/predictions"] = {"data": []}
        ANTWORTEN["/clips"] = {"data": [{"id": "clip1",
                                         "edit_url": "https://clips.twitch.tv/clip1/edit"}]}

        faelle = [
            ("title", {"title": "Neuer Titel"}, "PATCH", "/channels"),
            ("category", {"category": "Just Chatting"}, "PATCH", "/channels"),
            ("commercial", {"length": "90", "confirm": False}, "POST", "/channels/commercial"),
            ("marker", {"description": "Highlight"}, "POST", "/streams/markers"),
            ("clip", {}, "POST", "/clips"),
            ("chat", {"message": "Hallo"}, "POST", "/chat/messages"),
            ("chat_mode", {"mode": "subscriber"}, "PATCH", "/chat/settings"),
            ("clear_chat", {"confirm": False}, "DELETE", "/moderation/chat"),
        ]
        for aktion, einstellungen, methode, pfad in faelle:
            PROTOKOLL.clear()
            ctx = ctx_for(aktion, einstellungen)
            await plugin.on_key_down(aktion, einstellungen, ctx)
            treffer = letzte(methode, pfad)
            check(f"{aktion} → {methode} {pfad}", treffer is not None,
                  json.dumps([f"{e['methode']} {e['pfad']}" for e in PROTOKOLL]))

        print("\n== Und mit welchem Inhalt ==")
        PROTOKOLL.clear()
        ctx = ctx_for("title", {"title": "Neuer Titel", "category": "Just Chatting"})
        await plugin.on_key_down("title", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/channels")
        check("der Titel steht im Rumpf",
              anfrage["rumpf"]["title"] == "Neuer Titel", json.dumps(anfrage["rumpf"]))
        check("die Kategorie als Kennung, nicht als Name",
              anfrage["rumpf"]["game_id"] == "509658", json.dumps(anfrage["rumpf"]))
        check("und der Kanal in der Abfrage",
              anfrage["abfrage"]["broadcaster_id"] == "42", json.dumps(anfrage["abfrage"]))

        PROTOKOLL.clear()
        ctx = ctx_for("commercial", {"length": "90", "confirm": False})
        await plugin.on_key_down("commercial", ctx.settings, ctx)
        anfrage = letzte("POST", "/channels/commercial")
        check("die Werbedauer ist eine Zahl, kein Text",
              anfrage["rumpf"]["length"] == 90, json.dumps(anfrage["rumpf"]))

        PROTOKOLL.clear()
        ctx = ctx_for("chat", {"message": "Hallo Welt"})
        await plugin.on_key_down("chat", ctx.settings, ctx)
        anfrage = letzte("POST", "/chat/messages")
        check("die Chatnachricht nennt Absender und Kanal",
              anfrage["rumpf"]["sender_id"] == "42"
              and anfrage["rumpf"]["broadcaster_id"] == "42",
              json.dumps(anfrage["rumpf"]))

        print("\n== Rückfrage, wo es kein Zurück gibt ==")
        PROTOKOLL.clear()
        ctx = ctx_for("commercial", {"length": "60", "confirm": True}, index=3)
        await plugin.on_key_down("commercial", ctx.settings, ctx)
        check("der erste Druck schickt nichts",
              letzte("POST", "/channels/commercial") is None,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
        await plugin.on_key_down("commercial", ctx.settings, ctx)
        check("der zweite löst aus",
              letzte("POST", "/channels/commercial") is not None)

        print("\n== Der Chatmodus schaltet um, statt blind zu setzen ==")
        ANTWORTEN["/chat/settings"] = {"data": [{"subscriber_mode": True,
                                                 "slow_mode": False}]}
        plugin.api.vergiss()
        PROTOKOLL.clear()
        ctx = ctx_for("chat_mode", {"mode": "subscriber"})
        await plugin.on_key_down("chat_mode", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/chat/settings")
        check("ist er an, wird er ausgeschaltet",
              anfrage["rumpf"]["subscriber_mode"] is False, json.dumps(anfrage["rumpf"]))

        plugin.api.vergiss()
        PROTOKOLL.clear()
        ctx = ctx_for("chat_mode", {"mode": "slow", "seconds": 45})
        await plugin.on_key_down("chat_mode", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/chat/settings")
        check("beim Einschalten kommt die Wartezeit mit",
              anfrage["rumpf"] == {"slow_mode": True, "slow_mode_wait_time": 45},
              json.dumps(anfrage["rumpf"]))

        print("\n== Umfrage und Vorhersage kennen ihren Zustand ==")
        plugin.umfrage = None
        PROTOKOLL.clear()
        ctx = ctx_for("poll", {"question": "Weiter?", "choices": "Ja | Nein",
                               "duration": 60})
        await plugin.on_key_down("poll", ctx.settings, ctx)
        anfrage = letzte("POST", "/polls")
        check("ohne laufende Umfrage wird eine gestartet", anfrage is not None)
        check("mit zwei Antworten",
              [c["title"] for c in anfrage["rumpf"]["choices"]] == ["Ja", "Nein"],
              json.dumps(anfrage["rumpf"]))

        plugin.umfrage = {"id": "umfrage-1", "status": "ACTIVE"}
        PROTOKOLL.clear()
        await plugin.on_key_down("poll", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/polls")
        check("läuft eine, wird sie beendet",
              anfrage and anfrage["rumpf"]["status"] == "TERMINATED",
              json.dumps(anfrage["rumpf"] if anfrage else None))

        plugin.vorhersage = {"id": "v1", "status": "ACTIVE",
                             "outcomes": [{"id": "a"}, {"id": "b"}]}
        PROTOKOLL.clear()
        ctx = ctx_for("prediction", {"question": "Schaffe ich das?",
                                     "choices": "Ja | Nein", "winner": 2})
        await plugin.on_key_down("prediction", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/predictions")
        check("eine offene Vorhersage wird gesperrt",
              anfrage and anfrage["rumpf"]["status"] == "LOCKED",
              json.dumps(anfrage["rumpf"] if anfrage else None))

        plugin.vorhersage = {"id": "v1", "status": "LOCKED",
                             "outcomes": [{"id": "a"}, {"id": "b"}]}
        PROTOKOLL.clear()
        await plugin.on_key_down("prediction", ctx.settings, ctx)
        anfrage = letzte("PATCH", "/predictions")
        check("eine gesperrte wird aufgelöst",
              anfrage and anfrage["rumpf"]["status"] == "RESOLVED",
              json.dumps(anfrage["rumpf"] if anfrage else None))
        check("und zwar auf die gewählte Antwort",
              anfrage and anfrage["rumpf"]["winning_outcome_id"] == "b",
              json.dumps(anfrage["rumpf"] if anfrage else None))

        print("\n== Raid: erst hin, dann ab ==")
        ANTWORTEN["/users"] = {"data": [{"id": "99", "login": "freund",
                                         "display_name": "Freund"}]}
        plugin.api.vergiss()
        PROTOKOLL.clear()
        ctx = ctx_for("raid", {"channel": "freund"})
        await plugin.on_key_down("raid", ctx.settings, ctx)
        anfrage = letzte("POST", "/raids")
        check("der erste Druck startet den Raid",
              anfrage and anfrage["abfrage"]["to_broadcaster_id"] == "99",
              json.dumps(anfrage["abfrage"] if anfrage else None))
        check("die Taste zeigt den Countdown",
              plugin.get_state("raid", ctx.settings, ctx) == "laeuft")
        PROTOKOLL.clear()
        await plugin.on_key_down("raid", ctx.settings, ctx)
        check("der zweite bricht ab", letzte("DELETE", "/raids") is not None)
        check("und die Taste ist wieder bereit",
              plugin.get_state("raid", ctx.settings, ctx) == "default")

        print("\n== Was die Kacheln zeigen ==")
        check("große Zahlen werden gekürzt",
              (twitchmod._zahl(999), twitchmod._zahl(1234), twitchmod._zahl(45678),
               twitchmod._zahl(1_200_000)) == ("999", "1,2k", "46k", "1,2M"),
              str((twitchmod._zahl(999), twitchmod._zahl(1234),
                   twitchmod._zahl(45678), twitchmod._zahl(1_200_000))))
        check("Laufzeit unter einer Stunde ohne Stundenanteil",
              twitchmod._dauer(134) == "2:14", twitchmod._dauer(134))
        check("darüber mit", twitchmod._dauer(43387) == "12:03:07",
              twitchmod._dauer(43387))

        plugin.stream = None
        for art in ("key", "dial"):
            bild = plugin.render("status", {}, ctx_for("status", {}, input_type=art))
            check(f"offline zeichnet als {art}",
                  bild.size == ((120, 120) if art == "key" else (200, 100)),
                  str(bild.size))

        plugin.stream = {"viewer_count": 1234, "started_at": "2026-08-23T10:00:00Z"}
        plugin.follower = 5678
        bild = plugin.render("status", {"show": "viewers"}, ctx_for("status", {}))
        check("live zeichnet auch", bild.size == (120, 120))
        check("und der Zustand ist live",
              plugin.get_state("status", {}, ctx_for("status", {})) == "live")

        print("\n== Ohne Anmeldung passiert nichts Schlimmes ==")
        await plugin.gui_command("abmelden", {})
        check("das Token ist weg", not twitchmod.TOKEN_DATEI.exists())
        check("die Kachel sagt es",
              plugin.get_status()["detail"] == "nicht mit Twitch verbunden",
              json.dumps(plugin.get_status()))
        PROTOKOLL.clear()
        await plugin.on_key_down("chat", {"message": "Hallo"}, ctx_for("chat", {}))
        check("und ein Druck schickt nichts", not PROTOKOLL,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
        bild = plugin.render("followers", {}, ctx_for("followers", {}))
        check("gezeichnet wird trotzdem", bild.size == (120, 120))
    finally:
        await plugin.teardown()
        server.shutdown()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(asyncio.run(main()))
