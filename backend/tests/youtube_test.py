"""Prüft das YouTube-Plugin gegen eine nachgebaute Data API.

Das Plugin spricht hier wirklich HTTP, nur eben mit einem Server, der in
dieser Datei steht. Geprüft wird, was hinausgeht — und wie oft.

**Das Wievielmal ist hier so wichtig wie das Was.** YouTubes Kontingent
gilt je Google-Projekt: zehntausend Einheiten am Tag, Lesen kostet eine,
Schreiben fünfzig. Ein Plugin, das je Kachel und Sekunde nachfragt, wäre
mittags leer und danach für alles gesperrt — auch für das Beenden des
Streams. Der Server hier zählt deshalb jede Anfrage mit.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/youtube_test.py
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

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "youtube"

from _pluginlader import lade, nachbar  # noqa: E402

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

ytmod = lade(PLUGIN_DIR)
apimod = nachbar(ytmod, "youtube_api")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# --------------------------------------------------------------------------
# Die nachgebaute API
# --------------------------------------------------------------------------

PROTOKOLL: list[dict] = []
#: Zustand der Sendung, je Prüfung umgestellt: "", "ready" oder "live".
SENDUNG = "live"
ZUSCHAUER = "1234"
#: Steht hier etwas, antwortet die API damit als Fehler.
FEHLER: tuple[int, dict] | None = None


def _broadcast(status: str) -> dict:
    return {
        "items": [{
            "id": "sendung-1",
            "snippet": {"title": "Freitagsstream", "liveChatId": "chat-1"},
            "status": {"lifeCycleStatus": status},
        }],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _antwort(self, daten, code=200):
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
            "pfad": pfad.replace("/youtube/v3", "", 1),
            "abfrage": dict(urllib.parse.parse_qsl(abfrage)),
            "rumpf": rumpf,
            "auth": self.headers.get("Authorization"),
        }
        PROTOKOLL.append(eintrag)
        return eintrag

    def do_GET(self):  # noqa: N802
        eintrag = self._merke("GET")
        if FEHLER:
            self._antwort(FEHLER[1], FEHLER[0]); return
        pfad = eintrag["pfad"]
        if pfad == "/channels":
            self._antwort({"items": [{"id": "kanal-1",
                                      "snippet": {"title": "LabRaTox"}}]})
        elif pfad == "/liveBroadcasts":
            gesucht = eintrag["abfrage"].get("broadcastStatus")
            if SENDUNG == "live" and gesucht == "active":
                self._antwort(_broadcast("live"))
            elif SENDUNG == "ready" and gesucht == "upcoming":
                self._antwort(_broadcast("ready"))
            else:
                self._antwort({"items": []})
        elif pfad == "/videos":
            self._antwort({"items": [{
                "liveStreamingDetails": {"concurrentViewers": ZUSCHAUER},
            }]})
        else:
            self._antwort({})

    def do_POST(self):  # noqa: N802
        eintrag = self._merke("POST")
        if FEHLER:
            self._antwort(FEHLER[1], FEHLER[0]); return
        pfad = eintrag["pfad"]
        if pfad == "/device/code":
            self._antwort({"device_code": "GERAET-1", "user_code": "ABCD-EFGH",
                           "verification_url": "https://www.google.com/device",
                           "expires_in": 1800, "interval": 5})
        elif pfad == "/token":
            self._antwort({"access_token": "zugriff-1", "refresh_token": "erneuern-1",
                           "expires_in": 3600})
        elif pfad == "/liveBroadcasts/transition":
            neu = "live" if eintrag["abfrage"].get("broadcastStatus") == "live" else "complete"
            globals()["SENDUNG"] = "live" if neu == "live" else ""
            self._antwort(_broadcast(neu)["items"][0])
        else:
            self._antwort({"id": "ok"})


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def letzte(pfad=None, methode=None):
    for eintrag in reversed(PROTOKOLL):
        if pfad and eintrag["pfad"] != pfad:
            continue
        if methode and eintrag["methode"] != methode:
            continue
        return eintrag
    return None


def zaehle(pfad=None):
    return sum(1 for e in PROTOKOLL if pfad is None or e["pfad"] == pfad)


#: Was eine Anfrage aufs Kontingent kostet — so rechnet YouTube.
def einheiten() -> int:
    kosten = 0
    for eintrag in PROTOKOLL:
        if eintrag["pfad"] in ("/device/code", "/token"):
            continue  # Anmeldung läuft nicht über das Kontingent
        kosten += 50 if eintrag["methode"] == "POST" else 1
    return kosten


# --------------------------------------------------------------------------

manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()


class FakeRuntime:
    def request_redraw(self, ctx=None):
        pass

    def notify(self, *a, **k):
        pass


services = Services(audio=None, icons=icons, render=RenderService(icons),
                    runtime=FakeRuntime(), config=config, plugin_dir=PLUGIN_DIR)


def ctx_for(action, settings, *, index=0, input_type="key"):
    slot = Slot(plugin_id="youtube", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


async def main() -> int:
    global SENDUNG, FEHLER
    port = freier_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    apimod.API = f"http://127.0.0.1:{port}/youtube/v3"
    apimod.GERAET_URL = f"http://127.0.0.1:{port}/device/code"
    apimod.TOKEN_URL = f"http://127.0.0.1:{port}/token"
    apimod.WIDERRUF_URL = f"http://127.0.0.1:{port}/revoke"

    plugin = ytmod.YouTubePlugin(manifest, services)
    plugin.api.client_id = "pruef-id"
    plugin.api.client_secret = "pruef-secret"
    plugin.fehler = ""

    try:
        print("== Ohne Zugangsdaten geht nichts, und das steht auch da ==")
        leer = ytmod.YouTubePlugin(manifest, services)
        leer._uebernimm_konfiguration()
        check("das Plugin sagt, dass Zugangsdaten fehlen",
              "Zugangsdaten fehlen" in leer.fehler, leer.fehler)
        check("und verweist auf die Einstellungen, statt dort zu erklären",
              "Plugin-Einstellungen" in leer.fehler, leer.fehler)
        check("der Text bleibt kurz genug für eine Plugin-Karte",
              len(leer.fehler) <= 60, f"{len(leer.fehler)} Zeichen")
        # Am Feld steht, was man tun muss — mit der Adresse, auf die man
        # dafür gehen soll. Sie gehört dorthin und nicht auf die Karte.
        hilfe = json.dumps(
            [f for f in manifest.config_schema if f.key == "client_id"][0].help,
            ensure_ascii=False)
        check("am Feld steht, wo die Kennung herkommt",
              "YouTube Data API v3" in hilfe and "OAuth" in hilfe)
        check("und die Adresse dazu, klickbar in der Oberfläche",
              "https://console.cloud.google.com/apis/credentials" in hilfe)
        takt_hilfe = json.dumps(
            [f for f in manifest.config_schema if f.key == "poll_s"][0].help,
            ensure_ascii=False)
        check("das Tageslimit erklärt sich dort, wo es zählt",
              "Tageslimit" in takt_hilfe or "daily limit" in takt_hilfe)
        check("der Status zeigt darauf", leer.get_status()["connected"] is False)

        print("\n== Anmeldung über Gerätecode ==")
        start = await plugin.gui_command("verbinden", {})
        check("der Code kommt zurück", start["code"] == "ABCD-EFGH", str(start))
        check("mit Googles Adresse zum Eintippen",
              start["url"] == "https://www.google.com/device", str(start))
        gefragt = letzte("/device/code")
        check("gefragt wird mit der Client-ID",
              gefragt["rumpf"]["client_id"] == "pruef-id", json.dumps(gefragt["rumpf"]))
        check("und genau mit dem Bereich, den Google beim Gerätecode zulässt",
              gefragt["rumpf"]["scope"] == "https://www.googleapis.com/auth/youtube",
              gefragt["rumpf"]["scope"])
        check("force-ssl wird nicht verlangt — das ließe Google nicht zu",
              "force-ssl" not in gefragt["rumpf"]["scope"])

        # Solange der Code nicht bestätigt ist, antwortet Google mit 428 und
        # der Beschreibung „Precondition Required" — die Kennung dahinter
        # heißt authorization_pending. Wer auf den Text prüft, hält das
        # Warten für einen Abbruch und schließt den Dialog. Genau so
        # passiert am 2026-08-24.
        FEHLER = (428, {"error": "authorization_pending",
                        "error_description": "Precondition Required"})
        globals()["FEHLER"] = FEHLER
        wartet = await plugin.gui_command("nachfragen", {})
        check("noch nicht bestätigt heißt warten, nicht Abbruch",
              wartet == {"angemeldet": False, "wartet": True}, json.dumps(wartet))
        # Ein echter Fehler muss dagegen durchkommen — sonst wartet der
        # Dialog bis zum Ablauf des Codes auf etwas, das nie kommt.
        globals()["FEHLER"] = (400, {"error": "invalid_client",
                                     "error_description": "The OAuth client was not found."})
        try:
            await plugin.gui_command("nachfragen", {})
            check("ein echter Fehler wird gemeldet", False, "kam ohne Fehler durch")
        except apimod.YouTubeError as exc:
            check("ein echter Fehler wird gemeldet",
                  "OAuth client was not found" in str(exc), str(exc)[:70])
        globals()["FEHLER"] = None

        fertig = await plugin.gui_command("nachfragen", {})
        check("nach dem Eintippen ist man angemeldet", fertig["angemeldet"], str(fertig))
        check("und der Kanal steht fest", fertig["konto"] == "LabRaTox", str(fertig))
        check("das Token liegt nur für den Benutzer lesbar",
              oct(ytmod.TOKEN_DATEI.stat().st_mode)[-3:] == "600",
              oct(ytmod.TOKEN_DATEI.stat().st_mode)[-3:])
        check("beim Einlösen geht das Secret mit — Google verlangt es",
              letzte("/token")["rumpf"].get("client_secret") == "pruef-secret")
        check("jeder API-Aufruf trägt das Token",
              letzte("/channels")["auth"] == "Bearer zugriff-1")

        print("\n== Ein erneuertes Token landet sofort auf der Platte ==")
        # Google schickt beim Erneuern meist kein neues Refresh-Token, aber
        # ein neues Zugriffstoken und einen neuen Ablauf. Bleiben die nur im
        # Speicher, wird nach jedem Neustart unnötig erneuert — und wenn
        # Google doch eines austauscht, ist die Anmeldung verloren.
        plugin.api.erneuere()
        auf_platte = json.loads(ytmod.TOKEN_DATEI.read_text())
        check("das Zugriffstoken steht in der Datei",
              auf_platte["access_token"] == "zugriff-1", auf_platte["access_token"])
        check("das Refresh-Token bleibt erhalten",
              auf_platte["refresh_token"] == "erneuern-1", auf_platte["refresh_token"])
        check("und der Ablauf ist vermerkt", auf_platte["laeuft_ab"] > 0,
              str(auf_platte["laeuft_ab"]))

        print("\n== Was jede Aktion schickt ==")
        SENDUNG = "live"
        plugin.api.vergiss()
        await plugin._hole_stand()

        PROTOKOLL.clear()
        ctx = ctx_for("chat", {"message": "Danke fürs Zuschauen!"})
        await plugin.on_key_down("chat", ctx.settings, ctx)
        anfrage = letzte("/liveChatMessages", "POST")
        check("chat → POST /liveChatMessages", anfrage is not None)
        if anfrage:
            schnipsel = anfrage["rumpf"]["snippet"]
            check("mit der Chat-Kennung der laufenden Sendung",
                  schnipsel["liveChatId"] == "chat-1", json.dumps(schnipsel))
            check("und dem Text als textMessageEvent",
                  schnipsel["type"] == "textMessageEvent"
                  and schnipsel["textMessageDetails"]["messageText"] == "Danke fürs Zuschauen!",
                  json.dumps(schnipsel))

        PROTOKOLL.clear()
        ctx = ctx_for("ad", {"duration": 45, "confirm": False})
        await plugin.on_key_down("ad", ctx.settings, ctx)
        anfrage = letzte("/liveBroadcasts/cuepoint", "POST")
        check("ad → POST /liveBroadcasts/cuepoint", anfrage is not None)
        if anfrage:
            check("als Werbe-Cuepoint mit Dauer",
                  anfrage["rumpf"] == {"cueType": "cueTypeAd", "durationSecs": 45},
                  json.dumps(anfrage["rumpf"]))
            check("und an der laufenden Sendung",
                  anfrage["abfrage"]["id"] == "sendung-1", json.dumps(anfrage["abfrage"]))

        print("\n== Eine vorbereitete Sendung hat noch keinen offenen Chat ==")
        # Eine Sendung im Zustand „ready" hat schon eine Chat-Kennung, aber
        # der Chat nimmt nichts an: YouTube antwortet mit 404 und einem
        # leeren Rumpf — ohne ein Wort dazu, was fehlt. Gemessen an einer
        # echten Sendung am 2026-08-24. Also wird vorher geprüft.
        SENDUNG = "ready"
        globals()["SENDUNG"] = "ready"
        plugin.api.vergiss()
        await plugin._hole_stand()
        PROTOKOLL.clear()
        meldung = ""
        try:
            plugin.api.schicke_chat("Hallo")
        except apimod.YouTubeError as exc:
            meldung = str(exc)
        check("die Nachricht geht gar nicht erst raus",
              letzte("/liveChatMessages") is None,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
        check("und die Meldung sagt, woran es liegt",
              "läuft" in meldung and "ready" in meldung, meldung[:110])
        globals()["SENDUNG"] = "live"
        plugin.api.vergiss()
        await plugin._hole_stand()

        print("\n== Werbung fragt nach, weil sie sich nicht zurücknehmen lässt ==")
        PROTOKOLL.clear()
        ctx = ctx_for("ad", {"duration": 30, "confirm": True}, index=3)
        await plugin.on_key_down("ad", ctx.settings, ctx)
        check("der erste Druck schickt nichts",
              letzte("/liveBroadcasts/cuepoint") is None,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
        await plugin.on_key_down("ad", ctx.settings, ctx)
        check("der zweite löst aus", letzte("/liveBroadcasts/cuepoint") is not None)

        print("\n== Starten und Beenden richten sich nach dem Zustand ==")
        SENDUNG = "ready"
        plugin.api.vergiss()
        await plugin._hole_stand()
        ctx = ctx_for("stream", {"confirm": True}, index=4)
        check("eine vorbereitete Sendung zeigt „bereit“",
              plugin.get_state("stream", ctx.settings, ctx) == "bereit",
              str(plugin.get_state("stream", ctx.settings, ctx)))
        PROTOKOLL.clear()
        await plugin.on_key_down("stream", ctx.settings, ctx)
        anfrage = letzte("/liveBroadcasts/transition", "POST")
        check("der Druck startet sie — ohne Rückfrage",
              anfrage and anfrage["abfrage"]["broadcastStatus"] == "live",
              json.dumps(anfrage["abfrage"] if anfrage else None))
        check("und danach steht sie auf live",
              plugin.get_state("stream", ctx.settings, ctx) == "live",
              str(plugin.get_state("stream", ctx.settings, ctx)))

        PROTOKOLL.clear()
        await plugin.on_key_down("stream", ctx.settings, ctx)
        check("das Beenden fragt dagegen nach",
              letzte("/liveBroadcasts/transition") is None,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
        await plugin.on_key_down("stream", ctx.settings, ctx)
        anfrage = letzte("/liveBroadcasts/transition", "POST")
        check("der zweite Druck beendet",
              anfrage and anfrage["abfrage"]["broadcastStatus"] == "complete",
              json.dumps(anfrage["abfrage"] if anfrage else None))

        SENDUNG = ""
        plugin.api.vergiss()
        await plugin._hole_stand()
        check("ohne Sendung sagt die Taste das",
              plugin.get_state("stream", {}, ctx_for("stream", {})) == "keine")
        PROTOKOLL.clear()
        await plugin.on_key_down("stream", {}, ctx_for("stream", {}))
        check("und schickt keinen Übergang",
              letzte("/liveBroadcasts/transition") is None,
              json.dumps([e["pfad"] for e in PROTOKOLL]))

        print("\n== Das Kontingent wird nicht verbrannt ==")
        SENDUNG = "live"
        plugin.api.vergiss()
        PROTOKOLL.clear()
        # Acht Kacheln, die gleichzeitig zeichnen und ticken: Das darf keine
        # acht Abfragen ergeben.
        for i in range(8):
            c = ctx_for("viewers", {}, index=i)
            plugin.render("viewers", {}, c)
        check("das Zeichnen fragt überhaupt nicht", zaehle() == 0,
              json.dumps([e["pfad"] for e in PROTOKOLL]))

        await plugin._hole_stand()
        erste_runde = einheiten()
        for _ in range(8):
            await plugin._hole_stand()
        check("achtmal auffrischen kostet nicht mehr als einmal",
              einheiten() == erste_runde, f"{erste_runde} → {einheiten()} Einheiten")
        check("und eine Runde bleibt im einstelligen Bereich",
              erste_runde <= 3, f"{erste_runde} Einheiten")

        # Hochgerechnet auf einen Tag im eingestellten Takt.
        pro_tag = erste_runde * (86400 / plugin.takt)
        check("auf einen Tag gerechnet bleibt Luft im Kontingent",
              pro_tag < 10000, f"{round(pro_tag)} von 10000 Einheiten bei {plugin.takt:.0f} s Takt")

        print("\n== Wenn YouTube ablehnt ==")
        FEHLER = (403, {"error": {"code": 403, "message":
                                  "The user is not enabled for live streaming.",
                                  "errors": [{"reason": "liveStreamingNotEnabled"}]}})
        plugin.api.vergiss()
        try:
            plugin.api.sendung(erneut=True)
            check("die Begründung kommt durch", False, "kam ohne Fehler durch")
        except apimod.YouTubeError as exc:
            check("die Begründung kommt durch",
                  "not enabled for live streaming" in str(exc), str(exc)[:80])
            check("samt Googles Grund", "liveStreamingNotEnabled" in str(exc), str(exc)[:110])
        FEHLER = None

        print("\n== Googles Testmodus wird erklärt, nicht durchgereicht ==")
        # Wer eine App anlegt und sich anmelden will, scheitert zuerst hier:
        # Google lässt eine unüberprüfte App nur von eingetragenen
        # Testnutzern benutzen — auch nicht von der Person, die sie angelegt
        # hat. „access_denied" allein schickt einen auf die Suche im
        # falschen Programm.
        FEHLER = (403, {"error": "access_denied",
                        "error_description": "Access denied"})
        globals()["FEHLER"] = FEHLER
        try:
            plugin.api.geraetecode()
            check("der Testmodus wird benannt", False, "kam ohne Fehler durch")
        except apimod.YouTubeError as exc:
            check("der Testmodus wird benannt", "Testnutzer" in str(exc), str(exc)[:90])
            check("und der Weg dorthin steht dabei",
                  "OAuth-Zustimmungsbildschirm" in str(exc), str(exc)[:140])
        globals()["FEHLER"] = None

        print("\n== Gezeichnet wird immer ==")
        SENDUNG = "live"
        plugin.api.vergiss()
        await plugin._hole_stand()
        for aktion in ("viewers", "chat", "ad", "dashboard", "stream"):
            for art, groesse in (("key", (120, 120)), ("dial", (200, 100))):
                if art == "dial" and aktion not in ("viewers",):
                    continue
                c = ctx_for(aktion, {}, input_type=art)
                bild = plugin.render(aktion, c.settings, c)
                check(f"{aktion} als {art}", bild.size == groesse, str(bild.size))
        check("die Zuschauerzahl steht auf der Kachel", plugin.zuschauer == 1234,
              str(plugin.zuschauer))
        check("große Zahlen werden gekürzt",
              (ytmod._zahl(999), ytmod._zahl(1234), ytmod._zahl(45678)) == ("999", "1,2k", "46k"),
              str((ytmod._zahl(999), ytmod._zahl(1234), ytmod._zahl(45678))))

        print("\n== Abmelden ==")
        await plugin.gui_command("abmelden", {})
        check("das Token ist weg", not ytmod.TOKEN_DATEI.exists())
        PROTOKOLL.clear()
        await plugin.on_key_down("chat", {"message": "Hallo"}, ctx_for("chat", {}))
        check("und ein Druck schickt nichts", zaehle() == 0,
              json.dumps([e["pfad"] for e in PROTOKOLL]))
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
