"""Prüft das Govee-Plugin gegen einen nachgebauten Cloud-Dienst.

Das Plugin spricht hier wirklich HTTP, nur eben mit einem Server, der in
dieser Datei steht. Geprüft wird, was hinausgeht: Adresse, Kopfzeile,
Rumpf — und ob die Fähigkeit mit dem richtigen Typ *und* dem richtigen
Namen benannt wird. Genau daran scheitert diese API sonst: Govee nimmt
``brightness`` nur zusammen mit ``devices.capabilities.range`` an.

Zwei Dinge stehen im Mittelpunkt, weil sie im Betrieb wehtun:

* **Die Ratenbremse.** Govee erlaubt dreißig Zustandsabfragen je Minute
  und Gerät. Acht Kacheln, die jede Sekunde fragen, wären sofort gesperrt.
  Der Server hier zählt jede Anfrage mit, damit sich das messen lässt.
* **Die sofortige Rückmeldung.** Nach dem Einschalten muss die Kachel
  umspringen, ohne auf die nächste Abfrage zu warten — sonst drückt man
  ein zweites Mal und schaltet wieder aus.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/govee_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "govee"

from _pluginlader import lade, nachbar  # noqa: E402

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

goveemod = lade(PLUGIN_DIR)
apimod = nachbar(goveemod, "govee_api")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# --------------------------------------------------------------------------
# Der nachgebaute Dienst
# --------------------------------------------------------------------------

PROTOKOLL: list[dict] = []
#: Was der Dienst als Zustand meldet — je Prüfung umgestellt.
ZUSTAND = {"powerSwitch": 0, "brightness": 40, "colorRgb": 0xFF0000, "online": True}
#: Auf True gestellt antwortet der Dienst mit 429, wie bei zu vielen Anfragen.
BREMST = False
#: Steht hier etwas, antwortet der Dienst damit statt mit „success" — für
#: die Fälle, in denen Govee mit 200 antwortet und den Fehler in den Rumpf
#: schreibt.
ABLEHNUNG = None
#: Stellt die neue Schnittstelle auf „Gerät offline" — genau die Antwort,
#: die Govee für Geräte gibt, die über die alte Schnittstelle einwandfrei
#: laufen.
NEUE_SAGT_OFFLINE = False

#: Was die alte Schnittstelle über die Geräte weiß.
ALTE_GERAETE = {
    "code": 200,
    "data": {"devices": [
        {"device": "AB:CD:01", "model": "H6159", "deviceName": "Schreibtisch",
         "supportCmds": ["turn", "brightness", "color", "colorTem"]},
        {"device": "AB:CD:02", "model": "H6008", "deviceName": "Stehlampe",
         "supportCmds": ["turn"]},
    ]},
}

GERAETE = {
    "code": 200,
    "data": [
        {
            "sku": "H6159", "device": "AB:CD:01", "deviceName": "Schreibtisch",
            "capabilities": [
                {"type": "devices.capabilities.on_off", "instance": "powerSwitch"},
                {"type": "devices.capabilities.range", "instance": "brightness"},
                {"type": "devices.capabilities.color_setting", "instance": "colorRgb"},
                {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK"},
                {
                    "type": "devices.capabilities.dynamic_scene", "instance": "lightScene",
                    "parameters": {"options": [
                        {"name": "Sunrise", "value": 1}, {"name": "Aurora", "value": 2},
                    ]},
                },
            ],
        },
        {
            "sku": "H6008", "device": "AB:CD:02", "deviceName": "Stehlampe",
            "capabilities": [
                {"type": "devices.capabilities.on_off", "instance": "powerSwitch"},
            ],
        },
    ],
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
        laenge = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(laenge) if laenge else b""
        eintrag = {
            "methode": methode,
            "pfad": self.path.replace("/router/api/v1", "", 1).replace("/v1", "/alt", 1),
            "rumpf": json.loads(roh) if roh else None,
            "schluessel": self.headers.get("Govee-API-Key"),
        }
        PROTOKOLL.append(eintrag)
        return eintrag

    def do_GET(self):  # noqa: N802
        eintrag = self._merke("GET")
        if BREMST:
            self._antwort({"message": "Rate limit"}, 429)
            return
        if eintrag["pfad"].startswith("/alt/devices/state"):
            self._antwort({"code": 200, "data": {"properties": [
                {"online": True}, {"powerState": "on"}, {"brightness": 55},
                {"color": {"r": 255, "g": 0, "b": 0}},
            ]}})
            return
        if eintrag["pfad"] == "/alt/devices":
            self._antwort(ALTE_GERAETE)
            return
        self._antwort(GERAETE if eintrag["pfad"] == "/user/devices" else {"code": 200})

    def do_PUT(self):  # noqa: N802
        """Die alte Schnittstelle steuert mit PUT, nicht mit POST."""
        self._merke("PUT")
        self._antwort(ABLEHNUNG if ABLEHNUNG else {"code": 200, "message": "Success"})

    def do_POST(self):  # noqa: N802
        eintrag = self._merke("POST")
        if BREMST:
            self._antwort({"message": "Rate limit"}, 429)
            return
        if eintrag["pfad"] == "/device/control" and NEUE_SAGT_OFFLINE:
            self._antwort({"requestId": "x", "code": 400,
                           "msg": "Device is offline. Please check the Wi-Fi connection."})
            return
        if eintrag["pfad"] == "/device/state" and NEUE_SAGT_OFFLINE:
            self._antwort({"requestId": "x", "code": 400,
                           "msg": "Device is offline. Please check the Wi-Fi connection."})
            return
        if eintrag["pfad"] == "/device/state":
            self._antwort({"code": 200, "payload": {"capabilities": [
                {"instance": name, "state": {"value": wert}}
                for name, wert in ZUSTAND.items()
            ]}})
            return
        self._antwort(ABLEHNUNG if ABLEHNUNG else {"code": 200, "msg": "success"})


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def letzte(pfad=None):
    for eintrag in reversed(PROTOKOLL):
        if pfad is None or eintrag["pfad"] == pfad:
            return eintrag
    return None


def zaehle(pfad):
    return sum(1 for e in PROTOKOLL if e["pfad"] == pfad)


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
    slot = Slot(plugin_id="govee", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


SCHREIBTISCH = "H6159:AB:CD:01"


async def main() -> int:
    global BREMST
    port = freier_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    apimod.NEU_BASIS = f"http://127.0.0.1:{port}/router/api/v1"
    apimod.ALT_BASIS = f"http://127.0.0.1:{port}/v1"

    plugin = goveemod.GoveePlugin(manifest, services)
    plugin.api.schluessel = "pruef-schluessel"
    plugin.api.modus = "alt"        # die Vorgabe
    plugin.fehler = ""

    try:
        print("== Umrechnen ==")
        check("#ff8800 wird zur Govee-Zahl", apimod.hex_zu_zahl("#ff8800") == 16746496,
              str(apimod.hex_zu_zahl("#ff8800")))
        check("und wieder zurück", apimod.zahl_zu_hex(16746496) == "#ff8800")
        check("die Kurzform geht auch", apimod.zahl_zu_hex(apimod.hex_zu_zahl("#f80")) == "#ff8800")
        check("Unsinn wird abgelehnt",
              _wirft(lambda: apimod.hex_zu_zahl("blau"), apimod.GoveeError))

        print("\n== Was das Gerät kann, sagt Govee ==")
        # Beide Schnittstellen beschreiben dasselbe Gerät anders. Wichtig
        # ist, dass hinterher dieselbe Form herauskommt — sonst zeigte eine
        # gespeicherte Belegung nach dem Umschalten ins Leere.
        for modus, pfad in (("alt", "/alt/devices"), ("neu", "/user/devices")):
            plugin.api.modus = modus
            plugin.api.vergiss()
            PROTOKOLL.clear()
            geraete = plugin.api.geraete()
            check(f"Modus '{modus}': beide Geräte kommen an", len(geraete) == 2,
                  str(len(geraete)))
            check(f"Modus '{modus}': gefragt wird bei {pfad}",
                  letzte(pfad) is not None,
                  json.dumps([e["pfad"] for e in PROTOKOLL]))
            check(f"Modus '{modus}': der Schlüssel steht im Kopf",
                  letzte(pfad)["schluessel"] == "pruef-schluessel")
            eins = geraete[0]
            check(f"Modus '{modus}': der Gerätename ist derselbe",
                  eins.schluessel == SCHREIBTISCH, eins.schluessel)
            check(f"Modus '{modus}': und die Befehlsliste auch",
                  eins.kann == {"turn", "brightness", "color", "colorTem"},
                  str(sorted(eins.kann)))

        plugin.api.modus = "neu"
        plugin.api.vergiss()
        eins = plugin.api.geraete()[0]
        check("nur die neue kennt die Szenen",
              sorted(eins.szenen) == ["Aurora", "Sunrise"], json.dumps(sorted(eins.szenen)))
        check("und weiß, wie das Szenenfeld heißt",
              eins.szenen_feld == ("devices.capabilities.dynamic_scene", "lightScene"),
              str(eins.szenen_feld))

        optionen = plugin.get_dynamic_options("geraete")
        check("die Auswahlliste nennt beide", len(optionen) == 2, json.dumps(optionen))
        szenen = plugin.get_dynamic_options("szenen", {"device": SCHREIBTISCH})
        check("und die Szenen des gewählten Geräts",
              [o["value"] for o in szenen] == ["Aurora", "Sunrise"], json.dumps(szenen))

        plugin.api.modus = "alt"
        plugin.api.vergiss()
        szenen = plugin.get_dynamic_options("szenen", {"device": SCHREIBTISCH})
        check("über die alte gibt es keine Szenen, und das steht da auch",
              szenen and "neue Schnittstelle" in szenen[0]["label"], json.dumps(szenen))
        try:
            plugin.api.szene(plugin.api.geraet(SCHREIBTISCH), "Aurora")
            check("eine Szene über die alte wird abgelehnt", False, "kam durch")
        except apimod.GoveeError as exc:
            check("eine Szene über die alte wird abgelehnt",
                  "neue Schnittstelle" in str(exc), str(exc)[:70])

        print("\n== Der Schalter zwischen den Schnittstellen ==")
        for modus, erwartet in (("alt", "PUT"), ("neu", "POST"), ("beide", "POST")):
            plugin.api.modus = modus
            plugin.api.vergiss()
            PROTOKOLL.clear()
            plugin.api.schalte(plugin.api.geraet(SCHREIBTISCH), True)
            wege = [e["methode"] for e in PROTOKOLL if e["pfad"].endswith("control")]
            check(f"Modus '{modus}' schickt über {erwartet}",
                  wege and wege[0] == erwartet, str(wege))
        plugin.api.modus = "beide"
        plugin.api.vergiss()
        PROTOKOLL.clear()
        plugin.api.farbe(plugin.api.geraet(SCHREIBTISCH), 0x00FF00)
        wege = [e["methode"] for e in PROTOKOLL if e["pfad"].endswith("control")]
        check("'beide' nimmt wirklich beide Wege", wege == ["POST", "PUT"], str(wege))

        plugin.api.modus = "alt"
        plugin.api.vergiss()
        PROTOKOLL.clear()
        plugin.api.farbe(plugin.api.geraet(SCHREIBTISCH), 0x00FF00)
        anfrage = [e for e in PROTOKOLL if e["pfad"].endswith("control")][0]
        check("die alte bekommt Farben als r/g/b",
              anfrage["rumpf"]["cmd"] == {"name": "color",
                                          "value": {"r": 0, "g": 255, "b": 0}},
              json.dumps(anfrage["rumpf"]["cmd"]))
        plugin.api.modus = "neu"
        plugin.api.vergiss()
        PROTOKOLL.clear()
        plugin.api.farbe(plugin.api.geraet(SCHREIBTISCH), 0x00FF00)
        anfrage = [e for e in PROTOKOLL if e["pfad"].endswith("control")][0]
        check("die neue dieselbe Farbe als eine Zahl",
              anfrage["rumpf"]["payload"]["capability"]["value"] == 0x00FF00,
              json.dumps(anfrage["rumpf"]["payload"]["capability"]))

        print("\n== Jeder Befehl mit Typ und Namen ==")
        plugin.api.modus = "neu"
        plugin.api.vergiss()
        faelle = [
            ("power", {"device": SCHREIBTISCH, "mode": "on"},
             ("devices.capabilities.on_off", "powerSwitch", 1)),
            ("power", {"device": SCHREIBTISCH, "mode": "off"},
             ("devices.capabilities.on_off", "powerSwitch", 0)),
            ("brightness", {"device": SCHREIBTISCH, "value": 75},
             ("devices.capabilities.range", "brightness", 75)),
            ("color", {"device": SCHREIBTISCH, "color": "#ff8800"},
             ("devices.capabilities.color_setting", "colorRgb", 16746496)),
            ("temperature", {"device": SCHREIBTISCH, "kelvin": 5000},
             ("devices.capabilities.color_setting", "colorTemperatureK", 5000)),
            ("scene", {"device": SCHREIBTISCH, "scene": "Aurora"},
             ("devices.capabilities.dynamic_scene", "lightScene", 2)),
        ]
        for aktion, einstellungen, (typ, name, wert) in faelle:
            PROTOKOLL.clear()
            await plugin.on_key_down(aktion, einstellungen, ctx_for(aktion, einstellungen))
            befehl = letzte("/device/control")
            faehigkeit = (befehl or {}).get("rumpf", {}).get("payload", {}).get("capability", {})
            check(f"{aktion} → {name} = {wert}",
                  (faehigkeit.get("type"), faehigkeit.get("instance"), faehigkeit.get("value"))
                  == (typ, name, wert),
                  json.dumps(faehigkeit))

        befehl = letzte("/device/control")
        check("jeder Befehl nennt Modell und Gerät getrennt",
              befehl["rumpf"]["payload"]["sku"] == "H6159"
              and befehl["rumpf"]["payload"]["device"] == "AB:CD:01",
              json.dumps(befehl["rumpf"]["payload"]))
        check("und trägt eine Vorgangsnummer",
              bool(befehl["rumpf"].get("requestId")), str(befehl["rumpf"].get("requestId")))

        print("\n== Umschalten fragt erst nach ==")
        ZUSTAND["powerSwitch"] = 1
        plugin.api.vergiss()
        PROTOKOLL.clear()
        einstellungen = {"device": SCHREIBTISCH, "mode": "toggle"}
        await plugin.on_key_down("power", einstellungen, ctx_for("power", einstellungen))
        befehl = letzte("/device/control")
        check("ist es an, wird ausgeschaltet",
              befehl["rumpf"]["payload"]["capability"]["value"] == 0,
              json.dumps(befehl["rumpf"]["payload"]["capability"]))

        print("\n== Die Kachel springt sofort um ==")
        # Der Dienst meldet weiterhin „an" — trotzdem muss die Kachel nach
        # dem Ausschalten „aus" zeigen, ohne noch einmal zu fragen.
        ctx = ctx_for("power", einstellungen)
        check("ohne neue Abfrage steht sie auf aus",
              plugin.get_state("power", einstellungen, ctx) == "aus",
              str(plugin.get_state("power", einstellungen, ctx)))
        vorher = zaehle("/device/state")
        plugin.get_state("power", einstellungen, ctx)
        plugin.render("power", einstellungen, ctx)
        check("und das Zeichnen fragt gar nicht",
              zaehle("/device/state") == vorher,
              f"{vorher} → {zaehle('/device/state')}")

        print("\n== Govee wird nicht überrannt ==")
        plugin.api.vergiss()
        geraet = plugin.api.geraet(SCHREIBTISCH)
        vorher = zaehle("/device/state")
        for _ in range(8):
            plugin.api.zustand(geraet)
        check("acht Abfragen hintereinander sind eine Anfrage",
              zaehle("/device/state") == vorher + 1,
              f"{zaehle('/device/state') - vorher} Anfragen")

        print("\n== Govees eigene Zahlen sind nicht immer gültige Eingaben ==")
        # Gemessen am 2026-08-23: Die Schnittstelle meldet die Helligkeit als
        # 154 und weist genau diesen Wert beim Setzen als „out of range" ab —
        # sie meldet in 0–255 und nimmt 1–100. Wer den gelesenen Wert weiter-
        # dreht, landet sofort daneben.
        ZUSTAND["brightness"] = 154
        ZUSTAND["colorTemperatureK"] = 0
        plugin.api.vergiss()
        stand = plugin.api.zustand(plugin.api.geraet(SCHREIBTISCH))
        check("154 wird als 60 % gelesen", stand.helligkeit == 60, str(stand.helligkeit))
        check("und 0 Kelvin heißt „keine Weißeinstellung“, nicht null",
              stand.temperatur is None, str(stand.temperatur))

        PROTOKOLL.clear()
        ctx = ctx_for("brightness", {"device": SCHREIBTISCH, "step": 5}, input_type="dial")
        await plugin.on_dial_rotate("brightness", ctx.settings, 1, ctx)
        gesetzt = letzte("/device/control")["rumpf"]["payload"]["capability"]["value"]
        check("eine Raste weiter bleibt im erlaubten Bereich",
              1 <= gesetzt <= 100, str(gesetzt))
        check("und rechnet vom umgerechneten Wert aus", gesetzt == 65, str(gesetzt))

        PROTOKOLL.clear()
        ctx = ctx_for("temperature", {"device": SCHREIBTISCH, "kelvin": 4000},
                      input_type="dial")
        await plugin.on_dial_rotate("temperature", ctx.settings, 1, ctx)
        gesetzt = letzte("/device/control")["rumpf"]["payload"]["capability"]["value"]
        check("die Temperatur startet bei der Einstellung statt bei null",
              gesetzt == 4100, str(gesetzt))
        ZUSTAND["brightness"] = 40
        ZUSTAND["colorTemperatureK"] = 3000
        plugin.api.vergiss()

        print("\n== Wenn die neue Schnittstelle das Gerät nicht kennt ==")
        # Govee weist manche Geräte über die neue Schnittstelle als „offline"
        # ab, obwohl die alte sie einwandfrei schaltet. Gemessen an einem
        # H615C am 2026-08-23. Statt dem Benutzer zu erklären, sein
        # brennendes Licht sei offline, wird der andere Weg genommen.
        global NEUE_SAGT_OFFLINE
        NEUE_SAGT_OFFLINE = True
        plugin.api.modus = "beide"
        plugin.api.vergiss()
        PROTOKOLL.clear()
        geraet = plugin.api.geraet(SCHREIBTISCH)
        plugin.api.schalte(geraet, True)
        check("die neue Schnittstelle wurde zuerst versucht",
              letzte("/device/control") is not None)
        alt = [e for e in PROTOKOLL if e["methode"] == "PUT"]
        check("und dann die alte genommen", len(alt) == 1, str(len(alt)))
        if alt:
            check("mit deren Zuschnitt: model statt sku",
                  alt[0]["rumpf"]["model"] == "H6159"
                  and alt[0]["rumpf"]["device"] == "AB:CD:01",
                  json.dumps(alt[0]["rumpf"]))
            check("und dem Befehl als Name und Wert",
                  alt[0]["rumpf"]["cmd"] == {"name": "turn", "value": "on"},
                  json.dumps(alt[0]["rumpf"]["cmd"]))

        PROTOKOLL.clear()
        plugin.api.farbe(geraet, apimod.hex_zu_zahl("#ff8800"))
        alt = [e for e in PROTOKOLL if e["methode"] == "PUT"]
        check("Farbe geht dort als r/g/b, nicht als Zahl",
              alt and alt[0]["rumpf"]["cmd"] == {"name": "color",
                                                 "value": {"r": 255, "g": 136, "b": 0}},
              json.dumps(alt[0]["rumpf"]["cmd"]) if alt else "kein PUT")

        # Ohne Fehler nimmt „beide" trotzdem beide Wege — genau dafür ist
        # der Modus da.
        globals()["NEUE_SAGT_OFFLINE"] = False
        PROTOKOLL.clear()
        plugin.api.farbe(geraet, apimod.hex_zu_zahl("#00ff00"))
        wege = [e["methode"] for e in PROTOKOLL if e["pfad"].endswith("control")]
        check("auch ohne Fehler geht die Farbe beide Wege", wege == ["POST", "PUT"],
              str(wege))
        globals()["NEUE_SAGT_OFFLINE"] = True

        PROTOKOLL.clear()
        plugin.api.vergiss()
        stand = plugin.api.zustand(geraet)
        check("auch der Zustand kommt über den alten Weg",
              (stand.an, stand.helligkeit) == (True, 55),
              f"an={stand.an} hell={stand.helligkeit}")
        check("und seine Farbe wird umgerechnet", stand.farbe == 0xFF0000,
              hex(stand.farbe or 0))

        # Was ein Gerät gar nicht kann, geht erst gar nicht raus: Govee
        # antwortet darauf mit einer Meldung, die nach einem Fehler des
        # Benutzers klingt, obwohl schlicht die Lampe es nicht hergibt.
        stehlampe = plugin.api.geraet("H6008:AB:CD:02")
        PROTOKOLL.clear()
        meldung = ""
        try:
            plugin.api.helligkeit(stehlampe, 50)
        except apimod.GoveeError as exc:
            meldung = str(exc)
        check("was das Gerät nicht kann, wird gar nicht geschickt",
              "kann das nicht" in meldung and not PROTOKOLL, meldung[:80] or "kam durch")
        check("und die Meldung nennt, was es stattdessen kann",
              "turn" in meldung, meldung[:80])
        NEUE_SAGT_OFFLINE = False
        plugin.api.modus = "alt"
        plugin.api.vergiss()

        print("\n== Wenn Govee ablehnt ==")
        # Govee schickt seine Begründung als „msg" — nicht als „message".
        # Genau daran kam beim ersten echten Versuch nur „Code 400" an, und
        # damit ließ sich nichts anfangen.
        global ABLEHNUNG
        ABLEHNUNG = {"requestId": "x", "code": 400, "msg": "Parameter value out of range"}
        try:
            plugin.api.schalte(plugin.api.geraet(SCHREIBTISCH), True)
            check("die Begründung kommt durch", False, "kam ohne Fehler durch")
        except apimod.GoveeError as exc:
            check("die Begründung kommt durch",
                  "Parameter value out of range" in str(exc), str(exc))
            check("und dazu, was geschickt wurde", '"cmd"' in str(exc), str(exc)[:110])
        ABLEHNUNG = None

        ABLEHNUNG = {"requestId": "x", "code": 400}
        try:
            plugin.api.schalte(plugin.api.geraet(SCHREIBTISCH), True)
            check("ohne Begründung kommt die ganze Antwort", False, "kam durch")
        except apimod.GoveeError as exc:
            check("ohne Begründung kommt die ganze Antwort",
                  '"code": 400' in str(exc), str(exc))
        ABLEHNUNG = None

        print("\n== Wenn Govee bremst ==")
        BREMST = True
        plugin.api.vergiss()
        try:
            plugin.api.geraete(erneut=True)
            check("die Bremse wird gemeldet", False, "kam ohne Fehler durch")
        except apimod.GoveeError as exc:
            check("die Bremse wird als solche gemeldet", "bremst" in str(exc).lower(),
                  str(exc))
        BREMST = False

        print("\n== Ohne Schlüssel ==")
        ohne = goveemod.GoveePlugin(manifest, services)
        ohne._uebernimm_konfiguration()
        check("das Plugin sagt, was fehlt", "Schlüssel" in ohne.fehler, ohne.fehler)
        check("und der Status zeigt darauf",
              ohne.get_status()["connected"] is False, json.dumps(ohne.get_status()))
        PROTOKOLL.clear()
        await ohne.on_key_down("power", {"device": SCHREIBTISCH},
                               ctx_for("power", {"device": SCHREIBTISCH}))
        check("ein Druck schickt nichts", not PROTOKOLL,
              json.dumps([e["pfad"] for e in PROTOKOLL]))

        print("\n== Gezeichnet wird immer ==")
        for aktion in ("power", "brightness", "color", "temperature", "scene", "all"):
            for art, groesse in (("key", (120, 120)), ("dial", (200, 100))):
                if art == "dial" and aktion in ("color", "scene", "all"):
                    continue
                c = ctx_for(aktion, {"device": SCHREIBTISCH, "color": "#ff8800",
                                     "kelvin": 4000, "value": 50}, input_type=art)
                bild = plugin.render(aktion, c.settings, c)
                check(f"{aktion} als {art}", bild.size == groesse, str(bild.size))
        c = ctx_for("power", {})
        check("auch ohne eingetragenes Gerät",
              plugin.render("power", {}, c).size == (120, 120))
    finally:
        await plugin.teardown()
        server.shutdown()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


def _wirft(arbeit, art) -> bool:
    try:
        arbeit()
    except art:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


sys.exit(asyncio.run(main()))
