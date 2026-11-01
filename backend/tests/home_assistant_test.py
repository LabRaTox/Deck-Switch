"""Prüft das Plugin Home Assistant: REST, Live-Zustand, Kacheln.

Netz gibt es hier keines. Die Antworten unter ``daten/home-assistant/`` hat
eine echte Instanz mit Demo-Integration geliefert, HTTP und WebSocket sind
Attrappen, die so antworten wie sie.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/home_assistant_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import sys
import time
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "home-assistant"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

mod = lade(PLUGIN_DIR)
api = nachbar(mod, "ha.api")
live = nachbar(mod, "ha.live")
HaFehler = nachbar(mod, "ha.texte").HaFehler
TokenFehler = nachbar(mod, "ha.texte").TokenFehler

texte.verbinde_sprache(lambda: "de")

DATEN = pathlib.Path(__file__).resolve().parent / "daten" / "home-assistant"
STATES = json.loads((DATEN / "states.json").read_text(encoding="utf-8"))
SERVICES = json.loads((DATEN / "services.json").read_text(encoding="utf-8"))
WS = json.loads((DATEN / "websocket.json").read_text(encoding="utf-8"))

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def wirft(funktion, *args, art=HaFehler):
    try:
        funktion(*args)
    except art as exc:
        return str(exc)
    return None


# -- Attrappen ---------------------------------------------------------------


class Server:
    """Antwortet wie die REST-API, mit den aufgezeichneten Daten."""

    def __init__(self, stand=None):
        self.anfragen = []
        self.stand = stand or {}

    def __call__(self, methode, url, rumpf, kopf, timeout, kontext):
        pfad = url.split("://", 1)[1].split("/", 1)[1]
        self.anfragen.append((methode, pfad, json.loads(rumpf) if rumpf else None, kopf))
        if kopf.get("Authorization") != "Bearer gut":
            return 401, b"401: Unauthorized"
        if pfad == "api/states":
            return 200, json.dumps(STATES).encode()
        if pfad == "api/services":
            return 200, json.dumps(SERVICES).encode()
        if pfad.startswith("api/states/"):
            eid = pfad.removeprefix("api/states/")
            if eid in self.stand:
                return 200, json.dumps({"entity_id": eid, "state": self.stand[eid],
                                        "attributes": {}}).encode()
            return 404, b'{"message":"Entity not found."}'
        if pfad == "api/services/weather/get_forecasts":
            return 400, b'{"message":"Service call requires responses but caller did not ' \
                b'ask for responses. Add ?return_response to query parameters."}'
        if pfad == "api/services/light/gibtsnicht":
            return 400, b"400: Bad Request"
        return 200, b"[]"

    def befehle(self):
        return [(a[1], a[2]) for a in self.anfragen if a[0] == "POST"]


class FakeWs:
    """Eine Gegenstelle nach dem Protokoll der WebSocket-API."""

    def __init__(self, antworten=None, anmeldung="auth_ok"):
        self.gesendet = []
        self.anmeldung = anmeldung
        self.warteschlange = asyncio.Queue()
        self.warteschlange.put_nowait(json.dumps({"type": "auth_required",
                                                  "ha_version": "2026.10.4"}))
        self.antworten = antworten or {}
        self.zu = False
        self.ende = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        self.zu = True

    async def send(self, roh):
        nachricht = json.loads(roh)
        self.gesendet.append(nachricht)
        if nachricht["type"] == "auth":
            self.warteschlange.put_nowait(json.dumps({"type": self.anmeldung,
                                                      "ha_version": "2026.10.4"}))
        if nachricht["type"] == "subscribe_entities":
            n = nachricht["id"]
            self.warteschlange.put_nowait(json.dumps({"id": n, "type": "result",
                                                      "success": True, "result": None}))
            bekannt = {e: {"s": "on", "a": {"friendly_name": e}}
                       for e in nachricht["entity_ids"] if "gibtsnicht" not in e}
            self.warteschlange.put_nowait(json.dumps({"id": n, "type": "event",
                                                      "event": {"a": bekannt}}))

    async def recv(self):
        if self.ende is not None:
            raise self.ende
        return await self.warteschlange.get()

    def schicke(self, abo, ereignis):
        self.warteschlange.put_nowait(json.dumps({"id": abo, "type": "event",
                                                  "event": ereignis}))


class Verbinder:
    def __init__(self, *gegenstellen):
        self.gegenstellen = list(gegenstellen)
        self.aufrufe = []

    def __call__(self, url, **optionen):
        self.aufrufe.append((url, optionen))
        if not self.gegenstellen:
            raise OSError("keine Verbindung")
        gegenstelle = self.gegenstellen.pop(0)
        if isinstance(gegenstelle, Exception):
            raise gegenstelle
        return gegenstelle


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))

    def publish_plugin_status(self, plugin_id):
        pass


class KeinIconset:
    id = "iconset-tabler"
    is_iconset = True
    icons_path = pathlib.Path("/nicht/da")


class Registry:
    def get(self, plugin_id):
        return KeinIconset

    iconsets = [KeinIconset]


def baue(konfig=None, oeffne=None):
    manifest_dict = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    config = default_config()
    config.plugin_settings["home-assistant"] = konfig if konfig is not None else {
        "url": "http://ha:8123", "token": "gut"}
    icons = IconService(Registry())
    dienste = Services(audio=None, icons=icons, render=RenderService(icons),
                       runtime=FakeRuntime(), config=config, plugin_dir=PLUGIN_DIR)
    plugin = mod.HomeAssistantPlugin(Manifest.model_validate(manifest_dict), dienste)
    plugin._api = api.HomeAssistant("http://ha:8123", "gut", oeffne=oeffne or Server())
    plugin._live = live.Live(plugin._api, plugin._wunsch, plugin._live_aenderung)
    return plugin, dienste


def ctx_fuer(dienste, action_id, settings, art="key"):
    aussehen = Appearance()
    slot = Slot(plugin_id="home-assistant", action_id=action_id, settings=settings,
                appearance=aussehen)
    return SlotContext(action_id=action_id, settings=settings, appearance=aussehen,
                       input_type=art, index=0, page_id="p", profile_id="p",
                       size=(120, 120) if art == "key" else (200, 100), services=dienste,
                       slot=slot)


def stand_aus_aufnahme(plugin, geladen=()):
    plugin._live.stand = {z["entity_id"]: {"state": z["state"], "attributes": z["attributes"]}
                          for z in STATES}
    plugin._live.geladen = set(geladen)


async def warte(bedingung, sekunden=2.0):
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return True
        await asyncio.sleep(0.005)
    return False


# -- REST --------------------------------------------------------------------


def pruefe_adresse():
    print("Adresse")
    check("Nur Host", api.adresse_lesen("homeassistant.local:8123") ==
          "http://homeassistant.local:8123")
    check("Schrägstrich und /api fallen weg",
          api.adresse_lesen("https://ha.example/api/") == "https://ha.example")
    check("Unterpfad bleibt", api.adresse_lesen("http://h/ha/") == "http://h/ha")
    check("Leer bleibt leer", api.adresse_lesen("  ") == "")
    check("Fremdes Schema", wirft(api.adresse_lesen, "ftp://x") is not None)
    check("WebSocket", api.HomeAssistant("http://h:1", "t").ws_url == "ws://h:1/api/websocket")
    check("WebSocket mit TLS", api.HomeAssistant("https://h", "t").ws_url ==
          "wss://h/api/websocket")
    check("Ohne Token nicht eingerichtet", not api.HomeAssistant("http://h", "").eingerichtet)


def pruefe_rest():
    print("REST")
    server = Server()
    ha = api.HomeAssistant("http://ha:8123", "gut", oeffne=server)
    check("Zustände aus der Aufnahme", len(ha.zustaende()) == len(STATES))
    check("Token im Kopf", server.anfragen[0][3]["Authorization"] == "Bearer gut")
    dienste = ha.dienste()
    check("Dienste als domain.dienst", "light.turn_on" in dienste and dienste == sorted(dienste))

    falsch = api.HomeAssistant("http://ha:8123", "falsch", oeffne=server)
    check("401 ist ein Tokenfehler", wirft(falsch.zustaende, art=TokenFehler) is not None)

    ha.dienst("weather.get_forecasts", {"type": "daily"})
    pfade = [b[0] for b in server.befehle()]
    check("Pflichtantwort: zweiter Versuch mit return_response",
          pfade[-2:] == ["api/services/weather/get_forecasts",
                         "api/services/weather/get_forecasts?return_response"], pfade)
    check("Unbekannter Dienst gemeldet", "gibtsnicht" in wirft(ha.dienst, "light.gibtsnicht"))
    vorher = len(server.anfragen)
    check("Pfadtrick abgelehnt", wirft(ha.dienst, "light/../../x.y") is not None)
    check("Entität mit Pfad abgelehnt", wirft(ha.zustand, "../config") is not None)
    check("Nichts davon ging hinaus", len(server.anfragen) == vorher)

    def weg(*a):
        raise urllib.error.URLError("refused")

    check("Nicht erreichbar", "refused" in wirft(
        api.HomeAssistant("http://h", "t", oeffne=weg).zustaende))

    nicht_eingerichtet = api.HomeAssistant()
    check("Ohne Einrichtung kein Aufruf", wirft(nicht_eingerichtet.zustaende) is not None)


def pruefe_schalten():
    print("Schalten")
    server = Server({"lock.zu": "locked", "lock.auf": "unlocked", "lock.klemmt": "unavailable"})
    ha = api.HomeAssistant("http://ha:8123", "gut", oeffne=server)
    ha.schalte("light.bed_light")
    check("Licht über toggle", server.befehle()[-1] ==
          ("api/services/homeassistant/toggle", {"entity_id": "light.bed_light"}))
    ha.schalte("lock.zu")
    check("Zu wird auf", server.befehle()[-1][0] == "api/services/lock/unlock")
    ha.schalte("lock.auf")
    check("Auf wird zu", server.befehle()[-1][0] == "api/services/lock/lock")
    vorher = len(server.befehle())
    check("Schloss ohne klaren Stand bleibt", wirft(ha.schalte, "lock.klemmt") is not None)
    check("Kein Befehl dabei", len(server.befehle()) == vorher)
    ha.schalte("scene.abend")
    check("Szene wird aktiviert", server.befehle()[-1][0] == "api/services/scene/turn_on")
    ha.schalte("button.push")
    check("Schaltfläche wird gedrückt", server.befehle()[-1][0] == "api/services/button/press")


# -- Live --------------------------------------------------------------------


def pruefe_ereignisse():
    print("Ereignisse (aufgezeichnet)")
    stand = {}
    for nachricht in WS:
        if nachricht.get("type") == "event":
            live.wende_an(stand, nachricht["event"])
    licht = stand["light.bed_light"]
    check("Aufnahme endet mit aus", licht["state"] == "off")
    check("Attribute mit null bleiben null", licht["attributes"]["brightness"] is None)
    check("Name bleibt", licht["attributes"]["friendly_name"] == "Bed Light")
    live.wende_an(stand, {"c": {"light.bed_light": {"-": {"a": ["effect_list"]}}}})
    check("Attribut entfällt", "effect_list" not in licht["attributes"])
    live.wende_an(stand, {"c": {"nicht.da": {"+": {"s": "on"}}}})
    check("Änderung ohne Stand wird ignoriert", "nicht.da" not in stand)
    live.wende_an(stand, {"r": ["light.bed_light"]})
    check("Entfernt", "light.bed_light" not in stand)


async def pruefe_live():
    print("Live")
    wunsch = {"w": {"light.a", "light.gibtsnicht"}}
    ws = FakeWs()
    verbinder = Verbinder(ws)
    aenderungen = []
    ha = api.HomeAssistant("http://ha:8123", "gut")
    verbindung = live.Live(ha, lambda: wunsch["w"], lambda: aenderungen.append(1),
                           verbinde=verbinder)
    task = asyncio.create_task(verbindung.laufe())
    check("Verbindet und lädt", await warte(lambda: "light.a" in verbindung.stand))
    check("Version aus der Anmeldung", verbindung.version == "2026.10.4")
    check("Token in der Anmeldung", ws.gesendet[0] == {"type": "auth", "access_token": "gut"})
    abo = ws.gesendet[1]
    check("Nur die gewünschten Entitäten", abo["entity_ids"] == ["light.a", "light.gibtsnicht"])
    check("Fehlende gilt als geladen", "light.gibtsnicht" in verbindung.geladen)

    ws.schicke(abo["id"], {"c": {"light.a": {"+": {"s": "off"}}}})
    check("Änderung kommt an", await warte(lambda: verbindung.stand["light.a"]["state"] == "off"))
    ws.schicke(abo["id"], {"a": {"light.neu": {"s": "on", "a": {}}}})
    check("Später Neue löscht nichts", await warte(lambda: "light.neu" in verbindung.stand)
          and "light.a" in verbindung.stand)

    wunsch["w"] = {"light.b"}
    check("Neue Liste, neues Abo", await warte(lambda: "light.b" in verbindung.stand, 3))
    arten = [n["type"] for n in ws.gesendet]
    check("Altes Abo beendet", "unsubscribe_events" in arten)
    check("Alte Entität vergessen", "light.a" not in verbindung.stand)

    wunsch["w"] = None
    check("Ohne Wunsch ruht die Verbindung", await warte(lambda: ws.zu, 3))
    check("Keine Dauerverbindung", not verbindung.verbunden)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    print("Live: Token")
    alt_start = live.BACKOFF_START_S
    live.BACKOFF_START_S = 0.01
    falsch = FakeWs(anmeldung="auth_invalid")
    verbinder = Verbinder(falsch, FakeWs())
    verbindung = live.Live(ha, lambda: set(), lambda: None, verbinde=verbinder)
    task = asyncio.create_task(verbindung.laufe())
    check("Fehler gemeldet", await warte(lambda: bool(verbindung.fehler)))
    await asyncio.sleep(0.05)
    check("Kein weiterer Versuch", len(verbinder.aufrufe) == 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    print("Live: Abbruch")
    wackel = FakeWs()
    gut = FakeWs()
    verbinder = Verbinder(OSError("weg"), wackel, gut)
    verbindung = live.Live(ha, lambda: {"light.a"}, lambda: None, verbinde=verbinder)
    task = asyncio.create_task(verbindung.laufe())
    check("Nach dem Fehler zweiter Versuch", await warte(lambda: "light.a" in verbindung.stand))
    wackel.ende = OSError("abgerissen")
    wackel.schicke(1, {})
    check("Nach dem Abriss wieder da", await warte(lambda: bool(gut.gesendet)
                                                   and verbindung.verbunden, 3))
    check("Fehler wieder leer", await warte(lambda: verbindung.fehler == ""))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    live.BACKOFF_START_S = alt_start


# -- Plugin ------------------------------------------------------------------


async def pruefe_plugin():
    print("Plugin: Sichtbarkeit und Status")
    plugin, dienste = baue()
    ctx = ctx_fuer(dienste, "toggle", {"entity": "switch.ac"})
    check("Ohne Kachel kein Wunsch", plugin._wunsch() is None)
    plugin.on_tick("toggle", ctx.settings, ctx)
    check("Tick meldet die Entität", plugin._wunsch() == {"switch.ac"})
    plugin._gesehen["switch.ac"] -= mod.SICHTBAR_S + 1
    check("Nach der Frist vergessen", plugin._wunsch() is None)
    plugin.get_status()
    check("Plugin-Liste hält die Verbindung ohne Abo", plugin._wunsch() == set())
    plugin._live.version = "2026.10.4"
    check("Status", plugin.get_status()["connected"] and
          "2026.10.4" in plugin.get_status()["detail"])
    plugin._live.fehler = "kaputt"
    check("Status mit Fehler", plugin.get_status() == {"connected": False, "detail": "kaputt"})
    plugin._live_aenderung()
    plugin._live_aenderung()
    check("Dieselbe Meldung nur einmal", len(dienste.runtime.meldungen) == 1)
    leer, _ = baue({})
    leer._api = api.HomeAssistant()
    check("Ohne Einrichtung kein Status", leer.get_status() is None)

    print("Plugin: Listen")
    server = Server()
    plugin, dienste = baue(oeffne=server)
    alle = plugin.get_dynamic_options("alle", {})
    check("Alle Entitäten", len(alle) == len(STATES))
    werte = [o["value"] for o in plugin.get_dynamic_options("schaltbar", {})]
    check("Schaltbar nennt Licht, Schloss, Szene ist möglich",
          "light.bed_light" in werte and "lock.front_door" in werte)
    check("Schaltbar lässt Sensoren weg", not any(w.startswith("sensor.") for w in werte))
    lichter = plugin.get_dynamic_options("lichter", {})
    check("Nur Lichter", all(o["value"].startswith("light.") for o in lichter) and lichter)
    anzahl = len([a for a in server.anfragen if a[1] == "api/states"])
    check("Listen werden gemerkt", anzahl == 1, anzahl)
    check("Dienste", {"value": "light.turn_on", "label": "light.turn_on"}
          in plugin.get_dynamic_options("dienste", {}))
    weg, _ = baue(oeffne=lambda *a: (_ for _ in ()).throw(OSError("weg")))
    check("Ohne Verbindung bleibt die Wahl",
          weg.get_dynamic_options("alle", {"entity": "light.x"})[0]["value"] == "light.x")

    print("Plugin: Tasten")
    server = Server()
    plugin, dienste = baue(oeffne=server)
    stand_aus_aufnahme(plugin)
    ctx = ctx_fuer(dienste, "toggle", {"entity": "switch.decorative_lights"})
    check("An", plugin.get_state("toggle", ctx.settings, ctx) == "an")
    check("Name aus Home Assistant", plugin.get_label("toggle", ctx.settings, ctx) ==
          "Decorative Lights")
    ctx.appearance.label_text = "Eigen"
    check("Eigene Beschriftung geht vor", plugin.get_label("toggle", ctx.settings, ctx) is None)
    await plugin.on_key_down("toggle", ctx.settings, ctx)
    check("Druck schaltet", server.befehle()[-1][0] == "api/services/homeassistant/toggle")
    check("Bestätigung gesetzt", plugin._antwort(ctx) is True)
    ctx.scratch["antwort"] = (True, time.monotonic() - 1)
    plugin.on_tick("toggle", ctx.settings, ctx)
    check("Bestätigung läuft ab", "antwort" not in ctx.scratch)
    aus = ctx_fuer(dienste, "toggle", {"entity": "switch.ac"})
    check("Aus", plugin.get_state("toggle", aus.settings, aus) == "aus")
    plugin._live.stand["climate.ecobee"]["state"] = "heat_cool"
    klima = ctx_fuer(dienste, "toggle", {"entity": "climate.ecobee"})
    check("Heizen und Kühlen zählt als an", plugin.get_state("toggle", klima.settings, klima) == "an")
    plugin._live.stand["switch.ac"]["state"] = "unavailable"
    check("Nicht verfügbar", plugin.get_state("toggle", aus.settings, aus) == "nicht_da")
    knopf = ctx_fuer(dienste, "toggle", {"entity": "button.push"})
    check("Schaltfläche mit Zustand unknown bleibt bedienbar",
          plugin.get_state("toggle", knopf.settings, knopf) == "aus")

    print("Plugin: Dienst")
    einstellungen = {"service": "light.turn_on", "entity": "light.bed_light",
                     "data": '{"brightness_pct": 50}'}
    ctx = ctx_fuer(dienste, "service", einstellungen)
    await plugin.on_key_down("service", einstellungen, ctx)
    check("Daten und Entität gehen mit", server.befehle()[-1] ==
          ("api/services/light/turn_on", {"brightness_pct": 50, "entity_id": "light.bed_light"}))
    vorher = len(server.befehle())
    for kaputt in ('{"a":', "[1]"):
        ctx = ctx_fuer(dienste, "service", {"service": "light.turn_on", "data": kaputt})
        await plugin.on_key_down("service", ctx.settings, ctx)
        check(f"{kaputt} wird abgelehnt", plugin._antwort(ctx) is False)
    check("Kaputte Daten gehen nicht hinaus", len(server.befehle()) == vorher)
    check("Fehler sichtbar", dienste.runtime.meldungen[-1][0] == "error")

    print("Plugin: Dimmen")
    server = Server()
    plugin, dienste = baue(oeffne=server)
    stand_aus_aufnahme(plugin)
    einstellungen = {"entity": "light.ceiling_lights", "step": 5}
    ctx = ctx_fuer(dienste, "dimmer", einstellungen, "dial")
    check("Helligkeit aus der Aufnahme", plugin._helligkeit("light.ceiling_lights") == 71)
    await plugin.on_dial_rotate("dimmer", einstellungen, -2, ctx)
    check("Zwei Rasten", plugin._helligkeit("light.ceiling_lights") == 61)
    await asyncio.gather(*plugin._nebenher)
    check("Befehl geht hinaus", server.befehle()[-1] == (
        "api/services/light/turn_on",
        {"entity_id": "light.ceiling_lights", "brightness_pct": 61}))
    await plugin.on_dial_rotate("dimmer", einstellungen, -100, ctx)
    await asyncio.gather(*plugin._nebenher)
    check("Unten bei 0", server.befehle()[-1][1]["brightness_pct"] == 0)
    await plugin.on_dial_rotate("dimmer", einstellungen, 100, ctx)
    await asyncio.gather(*plugin._nebenher)
    check("Oben bei 100", server.befehle()[-1][1]["brightness_pct"] == 100)
    plugin._dimmen["light.ceiling_lights"].bis = 0
    check("Danach zählt der Stand von Home Assistant",
          plugin._helligkeit("light.ceiling_lights") == 71)

    print("Plugin: Dimmen unter Last")
    gesendet = []

    class Langsam(Server):
        def __call__(self, methode, url, rumpf, *a):
            if methode == "POST":
                gesendet.append(json.loads(rumpf)["brightness_pct"])
                while not schleife_frei[0]:
                    time.sleep(0.002)
            return 200, b"[]"

    schleife_frei = [False]
    plugin, dienste = baue(oeffne=Langsam())
    stand_aus_aufnahme(plugin)
    ctx = ctx_fuer(dienste, "dimmer", einstellungen, "dial")
    await plugin.on_dial_rotate("dimmer", einstellungen, -1, ctx)
    await warte(lambda: gesendet)
    for _ in range(5):
        await plugin.on_dial_rotate("dimmer", einstellungen, -1, ctx)
    schleife_frei[0] = True
    await asyncio.gather(*plugin._nebenher)
    check("Dazwischen entfällt, das Ende kommt an",
          gesendet == [66, 41], gesendet)

    plugin, dienste = baue()
    stand_aus_aufnahme(plugin)
    plugin._live.stand["light.x"] = {"state": "on",
                                     "attributes": {"supported_color_modes": ["onoff"]}}
    ctx = ctx_fuer(dienste, "dimmer", {"entity": "light.x"}, "dial")
    await plugin.on_dial_rotate("dimmer", ctx.settings, 1, ctx)
    check("Nur an und aus: kein Dimmen", not plugin._dimmen)

    print("Plugin: Anzeige")
    plugin, dienste = baue()
    stand_aus_aufnahme(plugin)
    wert = {"entity": "sensor.outside_temperature"}
    check("Wert mit Einheit und Komma", plugin._anzeige_wert(wert, wert["entity"]) ==
          ("15,6", "°C"))
    check("Runden", plugin._anzeige_wert({**wert, "decimals": 0}, wert["entity"])[0] == "16")
    texte.verbinde_sprache(lambda: "en")
    check("Punkt auf Englisch", plugin._anzeige_wert(wert, wert["entity"])[0] == "15.6")
    check("An auf Englisch", plugin._text_wert("on") == "on")
    texte.verbinde_sprache(lambda: "de")
    check("Attribut ohne Einheit", plugin._anzeige_wert(
        {"entity": "light.ceiling_lights", "attribute": "brightness"},
        "light.ceiling_lights") == ("180", ""))
    check("Text unverändert", plugin._text_wert("sunny") == "sunny")
    check("An wird übersetzt", plugin._text_wert("on") == "an")
    check("Datum ist keine Zahl", not mod._ist_zahl("2026-11-01"))

    print("Plugin: Kacheln")
    def verboten(*a):
        raise AssertionError("Netz beim Zeichnen")

    plugin, dienste = baue(oeffne=verboten)
    for action_id, einstellung in (("toggle", {"entity": "switch.ac"}),
                                   ("toggle", {"entity": "button.push"}),
                                   ("state", {"entity": "sensor.outside_humidity"}),
                                   ("state", {"entity": "light.ceiling_lights",
                                              "attribute": "rgb_color"}),
                                   ("service", {"service": "light.turn_on"}),
                                   ("dimmer", {"entity": "light.ceiling_lights"})):
        for art in ("dial",) if action_id == "dimmer" else ("key", "dial"):
            for fall in ("laedt", "stand", "fehler", "fehlt"):
                stand_aus_aufnahme(plugin) if fall == "stand" else None
                plugin._live.stand = plugin._live.stand if fall == "stand" else {}
                plugin._live.geladen = {einstellung.get("entity")} if fall == "fehlt" else set()
                plugin._live.fehler = "weg" if fall == "fehler" else ""
                ctx = ctx_fuer(dienste, action_id, einstellung, art)
                bild = plugin.render(action_id, einstellung, ctx)
                if bild.size != ctx.size:
                    check(f"{action_id}/{art}/{fall}", False, bild.size)
    check("Alle Kacheln zeichnen, ohne Netz", True)
    plugin._live.fehler = ""
    plugin._live.stand = {}
    plugin._live.geladen = {"light.gibtsnicht"}
    check("Nicht gefunden", plugin._problem("light.gibtsnicht")[1] == "nicht gefunden")
    check("Lädt", plugin._problem("light.anderes")[1] == "lädt")
    check("Keine Entität", plugin._problem("")[1] == "keine Entität")
    neu, _ = baue({"url": "ftp://x", "token": "t"})
    await neu._neustart()
    check("Falsche Adresse", neu._problem("light.a")[1] == "Adresse prüfen")
    await neu.teardown()

    print("Plugin: Lebenszyklus")
    plugin, dienste = baue({"url": "http://ha:1", "token": "t"})
    await plugin.setup()
    check("Schleife läuft", plugin._live_task is not None and not plugin._live_task.done())
    await plugin.teardown()
    check("Schleife beendet", plugin._live_task is None)


def pruefe_manifest():
    print("Manifest und Texte")
    roh = (PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(roh)
    Manifest.model_validate(manifest)
    check("Erste Fassung ohne changelog", manifest["version"] == "1.0.0" and
          "changelog" not in manifest)
    check("Kein Gedankenstrich", "—" not in roh)
    check("Kategorie", manifest["category"] == "smarthome")
    check("websockets ist genannt", any(p.startswith("websockets")
                                        for p in manifest["dependencies"]["python"]))
    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text(encoding="utf-8"))
    check("Beide Sprachen gleich", set(de) == set(en), set(de) ^ set(en))
    check("Kein Gedankenstrich in Texten", not any("—" in t for t in (*de.values(), *en.values())))
    quelle = "".join(p.read_text(encoding="utf-8") for p in PLUGIN_DIR.rglob("*.py")
                     if p.name != "screenshots.py")
    import re
    fehlend = [s for s in re.findall(r'(?:self\.t|text)\("([a-z_.]+)"', quelle) if s not in de]
    check("Alle genutzten Texte da", not fehlend, fehlend)


pruefe_adresse()
pruefe_rest()
pruefe_schalten()
pruefe_ereignisse()
asyncio.run(pruefe_live())
asyncio.run(pruefe_plugin())
pruefe_manifest()

print()
if FAILS:
    print(f"{len(FAILS)} FEHLGESCHLAGEN: {FAILS}")
    sys.exit(1)
print("Alles grün.")
