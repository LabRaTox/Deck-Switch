"""Prüft das Akku-Plugin: Felder lesen, Signale, Auswahl, Anzeige, Meldungen.

Kein Systembus und kein echtes headsetcontrol: UPower ist eine Attrappe, die
auf dieselben D-Bus-Aufrufe antwortet und Signale als echte
``dbus_next``-Nachrichten schickt. headsetcontrol wird durch eine Funktion
ersetzt, die festgelegte Ausgaben zurückgibt. Die Geräte hier sind
ausgedacht und tragen nur neutrale Namen.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/battery_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "battery"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from dbus_next import Message, MessageType, Variant  # noqa: E402

from deckswitch import texte as kern_texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

modul = lade(PLUGIN_DIR)
geraete_mod = nachbar(modul, "geraete")
upower_mod = nachbar(modul, "upower")
headset_mod = nachbar(modul, "headset")
olh_mod = nachbar(modul, "openlinkhub")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# --------------------------------------------------------------------------
# Attrappen
# --------------------------------------------------------------------------

BASIS = "/org/freedesktop/UPower/devices/"


def props(typ, prozent=50.0, *, zustand=2, modell="", hersteller="", serie="",
          nativ="", da=True, stufe=1, leer=0, voll=0, versorgt=False):
    return {
        "Type": typ, "Percentage": prozent, "State": zustand, "Model": modell,
        "Vendor": hersteller, "Serial": serie, "NativePath": nativ, "IsPresent": da,
        "BatteryLevel": stufe, "TimeToEmpty": leer, "TimeToFull": voll,
        "PowerSupply": versorgt,
    }


class FakeBus:
    """Antwortet wie UPower auf dem Systembus."""

    def __init__(self, geraete):
        self.geraete = dict(geraete)
        self.connected = True
        self.handler = []
        self.aufrufe = []
        self.ausfall = False
        self.match_regeln = []

    def add_message_handler(self, h):
        self.handler.append(h)

    def remove_message_handler(self, h):
        if h in self.handler:
            self.handler.remove(h)

    def disconnect(self):
        self.connected = False

    async def call(self, msg):
        self.aufrufe.append(msg.member)
        if self.ausfall:
            raise ConnectionError("Bus weg")
        if msg.member == "AddMatch":
            self.match_regeln.append(msg.body[0])
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])
        if msg.member == "EnumerateDevices":
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN,
                                   body=[list(self.geraete)])
        if msg.member == "GetAll":
            werte = self.geraete.get(msg.path)
            if werte is None:
                return SimpleNamespace(message_type=MessageType.ERROR, body=[],
                                       error_name="org.freedesktop.DBus.Error.UnknownObject")
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN,
                                   body=[{k: Variant(_sig(v), v) for k, v in werte.items()}])
        return SimpleNamespace(message_type=MessageType.ERROR, body=[], error_name="x")

    def sende(self, nachricht):
        for h in list(self.handler):
            h(nachricht)

    def eigenschaft(self, pfad, **werte):
        self.geraete[pfad].update(werte)
        self.sende(Message(
            message_type=MessageType.SIGNAL, path=pfad,
            interface="org.freedesktop.DBus.Properties", member="PropertiesChanged",
            signature="sa{sv}as",
            body=["org.freedesktop.UPower.Device",
                  {k: Variant(_sig(v), v) for k, v in werte.items()}, []],
        ))

    def dazu(self, pfad, werte):
        self.geraete[pfad] = werte
        self.sende(Message(message_type=MessageType.SIGNAL, path="/org/freedesktop/UPower",
                           interface="org.freedesktop.UPower", member="DeviceAdded",
                           signature="o", body=[pfad]))

    def weg(self, pfad):
        self.geraete.pop(pfad, None)
        self.sende(Message(message_type=MessageType.SIGNAL, path="/org/freedesktop/UPower",
                           interface="org.freedesktop.UPower", member="DeviceRemoved",
                           signature="o", body=[pfad]))


def _sig(wert):
    if isinstance(wert, bool):
        return "b"
    if isinstance(wert, float):
        return "d"
    if isinstance(wert, int):
        return "u" if wert >= 0 else "x"
    return "s"


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []
        self.status = 0
        self._loop = None

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))

    def publish_plugin_status(self, plugin_id):
        self.status += 1


def headset_ausgabe(*eintraege):
    return json.dumps({"name": "HeadsetControl", "version": "3.0.0", "device_count": len(eintraege),
                       "devices": list(eintraege)})


def headset_eintrag(status="BATTERY_AVAILABLE", level=70, produkt="Modell H"):
    return {"status": "success", "device": produkt, "vendor": "Hersteller H",
            "product": produkt, "id_vendor": "0x1234", "id_product": "0xabcd",
            "battery": {"status": status, "level": level}}


class FakeHeadset:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.befehle = []

    async def __call__(self, befehl, timeout):
        self.befehle.append(befehl)
        antwort = self.antworten.pop(0) if self.antworten else (0, headset_ausgabe())
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
icons = IconService()


def neue_dienste():
    return Services(audio=None, icons=icons, render=RenderService(icons), runtime=FakeRuntime(),
                    config=default_config(), plugin_dir=PLUGIN_DIR)


def ctx_for(services, action, settings, *, index=0, input_type="key", label=""):
    aussehen = Appearance()
    aussehen.label_text = label
    slot = Slot(plugin_id="battery", action_id=action, settings=settings, appearance=aussehen)
    return SlotContext(
        action_id=action, settings=settings, appearance=aussehen, input_type=input_type,
        index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100), services=services, slot=slot,
    )


def kein_openlinkhub(url, timeout):
    raise olh_mod.NichtErreichbar("Verbindung abgelehnt")


def olh_antwort(**geraete):
    """Antwort von /api/batteryStats, Gerät je Seriennummer als (Name, Stand, Typ)."""
    return json.dumps({"code": 200, "status": 1, "data": {
        serie: {"Device": name, "Level": stand, "DeviceType": typ}
        for serie, (name, stand, typ) in geraete.items()}}).encode()


def baue_plugin(bus, headset=None, *, programm=False, olh=None):
    services = neue_dienste()
    plugin = modul.BatteryPlugin(manifest, services)

    async def fabrik():
        if bus.ausfall:
            raise ConnectionError("kein Systembus")
        bus.connected = True
        return bus

    plugin.upower = upower_mod.UPowerQuelle(bus_fabrik=fabrik, bei_aenderung=plugin._geaendert)
    plugin.headset = headset_mod.HeadsetQuelle(
        ausfuehrer=headset or FakeHeadset([]),
        finde=lambda name: "/usr/bin/headsetcontrol" if programm else None)
    plugin.openlinkhub = olh_mod.OpenLinkHubQuelle(abholer=olh or kein_openlinkhub)
    return plugin, services


# --------------------------------------------------------------------------
# Prüfungen
# --------------------------------------------------------------------------


def pruefe_felder():
    print("== UPower-Felder lesen ==")
    g = geraete_mod.aus_upower(BASIS + "mouse_1", props(5, 42.0, modell="Modell A",
                                                         serie="AA:BB:CC:00:00:01"))
    check("Maus erkannt", g.typ == "maus", g.typ)
    check("Prozent gelesen", g.prozent == 42.0)
    check("Kennung aus der Seriennummer", g.kennung == "up:sn:aa:bb:cc:00:00:01", g.kennung)
    check("Anzeige-Display wird übergangen",
          geraete_mod.aus_upower(geraete_mod.DISPLAY_DEVICE, props(2, 80.0)) is None)
    check("Netzteil wird übergangen", geraete_mod.aus_upower(BASIS + "line_power_AC", props(1)) is None)

    laptop = geraete_mod.aus_upower(BASIS + "battery_BAT0",
                                    props(2, 77.0, nativ="BAT0", versorgt=True))
    check("Laptop-Akku erkannt", laptop.ist_laptop, laptop.typ)
    check("Laptop ohne Serie über den Kernelnamen", laptop.kennung == "up:nat:BAT0", laptop.kennung)

    ohne_serie = geraete_mod.aus_upower(BASIS + "keyboard_x",
                                        props(6, 60.0, modell="Modell B", hersteller="Firma"))
    check("ohne Serie: Typ, Hersteller und Modell",
          ohne_serie.kennung == "up:mv:tastatur|firma|modell b", ohne_serie.kennung)

    grob = geraete_mod.aus_upower(BASIS + "gaming_input_1", props(12, 0.0, stufe=7))
    check("grobe Stufe gelesen", grob.stufe == "hoch" and grob.prozent is None)
    check("grobe Stufe hat trotzdem einen Balkenwert", grob.anzeige_prozent == 80.0)
    check("Controller erkannt", grob.typ == "controller")

    laden = geraete_mod.aus_upower(BASIS + "headset_1", props(17, 30.0, zustand=1, voll=1800))
    check("Laden erkannt", laden.laedt and laden.rest_voll_s == 1800)
    fehlt = geraete_mod.aus_upower(BASIS + "mouse_2", props(5, 30.0, da=False))
    check("IsPresent=false heißt nicht verbunden", not fehlt.verbunden and not fehlt.laedt)

    zwei = geraete_mod.eindeutig([
        geraete_mod.aus_upower(BASIS + "mouse_b", props(5, 10.0, modell="Gleich")),
        geraete_mod.aus_upower(BASIS + "mouse_a", props(5, 20.0, modell="Gleich")),
    ])
    check("zwei gleiche Geräte bekommen verschiedene Kennungen",
          len({g.kennung for g in zwei}) == 2, str([g.kennung for g in zwei]))

    print("\n== Schwellen ==")
    sf = geraete_mod.stufe_fuer
    G = geraete_mod.Geraet
    check("über der Warnung ok", sf(G("a", "t", prozent=50.0), 30, 15) == "ok")
    check("auf der Warnung gelb", sf(G("a", "t", prozent=30.0), 30, 15) == "warn")
    check("unter kritisch rot", sf(G("a", "t", prozent=10.0), 30, 15) == "krit")
    check("grob kritisch ist rot", sf(G("a", "t", stufe="kritisch"), 30, 15) == "krit")
    check("nicht verbunden ist grau", sf(G("a", "t", prozent=10.0, verbunden=False), 30, 15) == "weg")
    check("kritisch nie über Warnung", modul.schwellen({"warn": 20, "critical": 40}) == (20.0, 20.0))


def pruefe_headset_lesen():
    print("\n== headsetcontrol lesen ==")
    g = headset_mod.lies_json(headset_ausgabe(headset_eintrag()))
    check("ein Gerät aus der JSON-Ausgabe", len(g) == 1)
    check("Stand und Kennung", g[0].prozent == 70.0 and g[0].kennung == "hc:0x1234:0xabcd",
          g[0].kennung)
    laden = headset_mod.lies_json(headset_ausgabe(headset_eintrag("BATTERY_CHARGING", -1)))[0]
    check("Laden ohne Stand", laden.laedt and laden.prozent is None)
    aus = headset_mod.lies_json(headset_ausgabe(headset_eintrag("BATTERY_UNAVAILABLE", -1)))[0]
    check("ohne Akkuwert nicht verbunden", not aus.verbunden)
    check("Kurzform: Zahl", headset_mod.lies_kurz("55\n")[0].prozent == 55.0)
    check("Kurzform: -1 lädt", headset_mod.lies_kurz("-1")[0].laedt)
    check("Kurzform: -2 fehlt", not headset_mod.lies_kurz("-2")[0].verbunden)
    try:
        headset_mod.lies_json("Usage: headsetcontrol ...")
        check("Text statt JSON wird erkannt", False)
    except ValueError:
        check("Text statt JSON wird erkannt", True)


async def pruefe_headset_quelle():
    print("\n== headsetcontrol als Quelle ==")
    ohne = FakeHeadset([])
    q = headset_mod.HeadsetQuelle(ausfuehrer=ohne, finde=lambda n: None)
    check("ohne Programm leer", await q.auffrischen() == {})
    check("ohne Programm wird nichts gestartet", ohne.befehle == [])

    neu = FakeHeadset([(0, headset_ausgabe(headset_eintrag()))])
    q = headset_mod.HeadsetQuelle(ausfuehrer=neu, finde=lambda n: "/usr/bin/" + n)
    await q.auffrischen()
    check("JSON-Aufruf mit -b -o json", neu.befehle[0][1:] == ["-b", "-o", "json"],
          str(neu.befehle))
    check("Gerät übernommen", len(q.geraete) == 1)

    alt = FakeHeadset([(1, ""), (0, "64\n"), (0, "63\n")])
    q = headset_mod.HeadsetQuelle(ausfuehrer=alt, finde=lambda n: "/usr/bin/" + n)
    await q.auffrischen()
    await q.auffrischen()
    check("ältere Fassung: weiter mit -b -c",
          [b[1:] for b in alt.befehle] == [["-b", "-o", "json"], ["-b", "-c"], ["-b", "-c"]],
          str(alt.befehle))
    check("Stand aus der Kurzform", next(iter(q.geraete.values())).prozent == 63.0)

    haengt = FakeHeadset([headset_mod.HeadsetFehler("keine Antwort nach 5 s")])
    q = headset_mod.HeadsetQuelle(ausfuehrer=haengt, finde=lambda n: "/usr/bin/" + n)
    try:
        await q.auffrischen()
        check("Zeitüberschreitung wird gemeldet", False)
    except headset_mod.HeadsetFehler:
        check("Zeitüberschreitung wird gemeldet", True)

    # Das echte ``ausfuehren`` hat ein Timeout. Statt eines Programms
    # antwortet ein Prozess-Ersatz, der nie fertig wird.
    class HaengenderProzess:
        returncode = None

        def __init__(self):
            self.getoetet = False

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            self.getoetet = True

        async def wait(self):
            return -9

    ersatz = HaengenderProzess()
    gestartet = []

    async def starte(*befehl, **_):
        gestartet.append(befehl)
        return ersatz

    echt = headset_mod.asyncio.create_subprocess_exec
    headset_mod.asyncio.create_subprocess_exec = starte
    try:
        await headset_mod.ausfuehren(["headsetcontrol", "-b", "-o", "json"], 0.1)
        check("ausfuehren bricht nach dem Timeout ab", False)
    except headset_mod.HeadsetFehler:
        check("ausfuehren bricht nach dem Timeout ab", True)
    finally:
        headset_mod.asyncio.create_subprocess_exec = echt
    check("und beendet den hängenden Prozess", ersatz.getoetet)
    check("ohne Shell, als Liste", gestartet == [("headsetcontrol", "-b", "-o", "json")])


async def pruefe_upower_quelle():
    print("\n== UPower über die Bus-Attrappe ==")
    bus = FakeBus({
        BASIS + "DisplayDevice": props(2, 0.0),
        BASIS + "mouse_dev_1": props(5, 40.0, modell="Modell A", serie="SN1"),
        BASIS + "line_power_AC": props(1),
    })
    aenderungen = []

    async def fabrik():
        return bus

    q = upower_mod.UPowerQuelle(bus_fabrik=fabrik, bei_aenderung=lambda: aenderungen.append(1))
    await q.auffrischen()
    check("nur das Gerät mit Akku", list(q.geraete) == ["up:sn:sn1"], str(list(q.geraete)))
    check("Signale abonniert", len(bus.match_regeln) == 2 and
          any("PropertiesChanged" in r for r in bus.match_regeln))

    bus.eigenschaft(BASIS + "mouse_dev_1", Percentage=35.0)
    check("PropertiesChanged ändert den Stand", q.geraete["up:sn:sn1"].prozent == 35.0)
    check("und meldet die Änderung", len(aenderungen) == 1)

    bus.eigenschaft(BASIS + "mouse_dev_1", UpdateTime=12345)
    check("unsichtbare Felder melden nichts", len(aenderungen) == 1)

    bus.weg(BASIS + "mouse_dev_1")
    check("DeviceRemoved nimmt es heraus", q.geraete == {})

    bus.dazu(BASIS + "mouse_dev_7", props(5, 33.0, modell="Modell A", serie="SN1"))
    await asyncio.sleep(0.01)
    check("DeviceAdded unter neuem Pfad, dieselbe Kennung",
          "up:sn:sn1" in q.geraete and q.geraete["up:sn:sn1"].pfad.endswith("mouse_dev_7"))

    bus.ausfall = True
    try:
        await q.auffrischen()
        check("Ausfall wird zu UPowerFehler", False)
    except upower_mod.UPowerFehler:
        check("Ausfall wird zu UPowerFehler", True)
    await q.schliessen()
    check("schließen trennt", not bus.connected and bus.handler == [])


async def pruefe_plugin():
    print("\n== Plugin: gefragt wird nur bei sichtbarer Kachel ==")
    modul.TAKT_S = 0.02
    bus = FakeBus({
        BASIS + "mouse_m": props(5, 64.0, modell="Modell A", serie="SN-M"),
        BASIS + "battery_BAT0": props(2, 12.0, nativ="BAT0", versorgt=True, leer=7200),
        BASIS + "keyboard_k": props(6, 25.0, modell="Modell B", serie="SN-K", zustand=1),
    })
    kopfhoerer = FakeHeadset([(0, headset_ausgabe(headset_eintrag(level=50)))] * 20)
    plugin, services = baue_plugin(bus, kopfhoerer, programm=True)
    await plugin.setup()
    try:
        await asyncio.sleep(0.15)
        check("ohne Tick kein Aufruf an UPower", bus.aufrufe == [], str(bus.aufrufe))
        check("ohne Tick kein headsetcontrol", kopfhoerer.befehle == [])

        maus = ctx_for(services, "level", {"device": "up:sn:sn-m"}, index=1)
        await plugin.on_tick("level", maus.settings, maus)
        await asyncio.sleep(0.15)
        check("nach dem Tick wird gefragt", "EnumerateDevices" in bus.aufrufe)
        check("headsetcontrol auch", len(kopfhoerer.befehle) == 1, str(kopfhoerer.befehle))
        anzahl = len(bus.aufrufe)
        await asyncio.sleep(0.15)
        check("danach erst wieder nach dem Abstand", len(bus.aufrufe) == anzahl)

        print("\n== Plugin: Anzeige ==")
        vorher = len(bus.aufrufe)
        a = plugin.ansicht("level", maus.settings, maus)
        bild = plugin.render("level", maus.settings, maus)
        plugin.get_status()
        check("render und Status fragen nicht", len(bus.aufrufe) == vorher)
        check("Prozent auf der Taste", a.gross == "64%", a.gross)
        check("Name aus dem Modell", a.titel == "Modell A", a.titel)
        check("Balken passt", abs(a.balken - 0.64) < 1e-6)
        check("Farbe ok", a.stufe == "ok")
        check("Taste 120×120", bild.size == (120, 120))
        dial = ctx_for(services, "level", {"device": "up:sn:sn-m"}, index=2, input_type="dial")
        check("Segment 200×100", plugin.render("level", dial.settings, dial).size == (200, 100))

        mit_label = ctx_for(services, "level", {"device": "up:sn:sn-m"}, index=3, label="Links")
        check("Beschriftung ersetzt den Namen",
              plugin.ansicht("level", mit_label.settings, mit_label).titel == "Links")

        tastatur = ctx_for(services, "level", {"device": "up:sn:sn-k"}, index=4)
        t = plugin.ansicht("level", tastatur.settings, tastatur)
        check("Laden zeigt den Blitz", t.laedt)
        check("Stand 25 ist gelb", t.stufe == "warn", t.stufe)
        rot = ctx_for(services, "level", {"device": "up:sn:sn-k", "critical": 30}, index=5)
        check("eigene Schwelle macht ihn rot", plugin.ansicht("level", rot.settings, rot).stufe == "krit")

        laptop = ctx_for(services, "level", {"device": "up:nat:BAT0"}, index=6)
        lt = plugin.ansicht("level", laptop.settings, laptop)
        check("Restzeit unter dem Stand", "2h 00m" in lt.klein, lt.klein)

        ohne = ctx_for(services, "level", {}, index=7)
        check("ohne Gerät ein Hinweis", plugin.ansicht("level", {}, ohne).gross == "---")

        print("\n== Plugin: Auswahl übersteht Neuverbinden ==")
        bus.weg(BASIS + "mouse_m")
        weg = plugin.ansicht("level", maus.settings, maus)
        check("getrennt: nicht verbunden", weg.klein == plugin.t("kachel.nicht_verbunden"), weg.klein)
        check("der Name bleibt", weg.titel == "Modell A", weg.titel)
        optionen = await plugin.get_dynamic_options("geraete", {"device": "up:sn:sn-m"})
        eintrag = next((o for o in optionen if o["value"] == "up:sn:sn-m"), None)
        check("Auswahlliste behält das getrennte Gerät",
              eintrag is not None and "Modell A" in eintrag["label"], str(eintrag))
        bus.dazu(BASIS + "mouse_m_neu", props(5, 63.0, modell="Modell A", serie="SN-M"))
        await asyncio.sleep(0.02)
        zurueck = plugin.ansicht("level", maus.settings, maus)
        check("wieder da unter neuem Pfad", zurueck.gross == "63%", zurueck.gross)

        print("\n== Plugin: schwächster Akku ==")
        schwach = ctx_for(services, "weakest", {"include_laptop": True}, index=8)
        s = plugin.ansicht("weakest", schwach.settings, schwach)
        check("mit Laptop: der Laptop", s.gross == "12%", s.gross)
        ohne_lt = ctx_for(services, "weakest", {"include_laptop": False}, index=9)
        s = plugin.ansicht("weakest", ohne_lt.settings, ohne_lt)
        check("ohne Laptop: die Tastatur", s.gross == "25%" and s.titel == "Modell B",
              f"{s.gross} {s.titel}")

        print("\n== Plugin: Blättern am Dial ==")
        blatt = ctx_for(services, "browse", {}, index=10, input_type="dial")
        a = plugin.ansicht("browse", {}, blatt)
        check("vier Geräte zum Blättern", a.rechts.endswith("/4"), a.rechts)
        erstes = a.titel
        await plugin.on_dial_rotate("browse", {}, 1, blatt)
        check("Drehen blättert", plugin.ansicht("browse", {}, blatt).titel != erstes)
        await plugin.on_dial_rotate("browse", {}, -1, blatt)
        check("zurückdrehen", plugin.ansicht("browse", {}, blatt).titel == erstes)
        await plugin.on_dial_push("browse", {}, blatt)
        check("Druck springt zum schwächsten", plugin.ansicht("browse", {}, blatt).gross == "12%")
        check("headsetcontrol-Gerät ist dabei",
              any(g.quelle == "headsetcontrol" for g in plugin._sortiert()))

        print("\n== Plugin: Meldung bei kritisch, nur einmal ==")
        meldet = ctx_for(services, "level", {"device": "up:sn:sn-m", "notify": True}, index=11)
        await plugin.on_tick("level", meldet.settings, meldet)
        bus.eigenschaft(BASIS + "mouse_m_neu", Percentage=9.0)
        bus.eigenschaft(BASIS + "mouse_m_neu", Percentage=8.0)
        warnungen = [m for m in services.runtime.meldungen if m[0] == "warning"]
        check("genau eine Meldung", len(warnungen) == 1, str(warnungen))
        check("Meldung nennt Gerät und Stand",
              warnungen and "Modell A" in warnungen[0][1] and "8%" not in warnungen[0][1]
              and "9%" in warnungen[0][1], str(warnungen))
        bus.eigenschaft(BASIS + "mouse_m_neu", State=1)
        bus.eigenschaft(BASIS + "mouse_m_neu", State=2, Percentage=7.0)
        warnungen = [m for m in services.runtime.meldungen if m[0] == "warning"]
        check("nach dem Laden kommt sie wieder", len(warnungen) == 2, str(warnungen))
        ohne_meldung = [m for m in services.runtime.meldungen if "Modell B" in m[1]]
        check("ohne Häkchen keine Meldung", ohne_meldung == [])

        print("\n== Plugin: Status ==")
        st = plugin.get_status()
        check("verbunden mit Anzahl", st["connected"] and "4" in st["detail"], str(st))
        check("headsetcontrol erwähnt", "headsetcontrol" in st["detail"])
    finally:
        await plugin.teardown()


async def pruefe_ausfall():
    print("\n== Plugin: UPower fehlt, Backoff und eine Meldung ==")
    modul.TAKT_S = 0.02
    bus = FakeBus({})
    bus.ausfall = True
    plugin, services = baue_plugin(bus)
    await plugin.setup()
    try:
        c = ctx_for(services, "level", {"device": "up:sn:x"})
        for _ in range(5):
            await plugin.on_tick("level", c.settings, c)
            await asyncio.sleep(0.05)
        plan = plugin._upower_plan
        check("Fehler vermerkt", bool(plan.fehler), plan.fehler)
        check("Pause wächst nicht bei jedem Takt", plan.pause == modul.PAUSE_START_S * 2,
              str(plan.pause))
        infos = [m for m in services.runtime.meldungen if m[0] == "info"]
        check("Meldung genau einmal", len(infos) == 1, str(infos))
        a = plugin.ansicht("level", c.settings, c)
        check("Kachel sagt kein UPower", a.klein == plugin.t("kachel.kein_upower"), a.klein)
        st = plugin.get_status()
        check("Status nicht verbunden", st["connected"] is False)
        # Nach der Pause klappt es wieder: Meldung zurückgesetzt.
        bus.ausfall = False
        bus.geraete[BASIS + "mouse_x"] = props(5, 50.0, serie="X")
        plan.naechste = 0.0
        await plugin._frage_faellige()
        check("nach Erholung kein Fehler", plan.fehler == "" and plan.pause == modul.PAUSE_START_S)
        check("Gerät da", plugin.ansicht("level", c.settings, c).gross == "50%")
    finally:
        await plugin.teardown()


def pruefe_texte():
    print("\n== Texte ==")
    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text())
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text())
    check("beide Sprachen haben dieselben Schlüssel", de.keys() == en.keys(),
          str(set(de) ^ set(en)))
    import re
    platz = re.compile(r"\{(\w+)\}")
    gleich = all(set(platz.findall(de[k])) == set(platz.findall(en[k])) for k in de)
    check("dieselben Platzhalter", gleich)
    check("kein Gedankenstrich", not any("—" in v for v in [*de.values(), *en.values()]))
    roh = (PLUGIN_DIR / "manifest.json").read_text()
    check("kein Gedankenstrich im Manifest", "—" not in roh)

    quelltext = "".join(p.read_text() for p in PLUGIN_DIR.glob("*.py") if p.name != "screenshots.py")
    benutzt = set(re.findall(r"""t\(\s*["']([a-z_]+\.[a-z_]+)["']""", quelltext))
    benutzt |= {f"typ.{t}" for t in geraete_mod.TYPEN.values()} | {"typ.laptop", "typ.sonstiges"}
    benutzt |= {f"stufe.{s}" for s in geraete_mod.STUFEN.values()}
    fehlt = sorted(k for k in benutzt if k not in de)
    check("jeder benutzte Schlüssel steht in de.json", not fehlt, str(fehlt))

    kern_texte.verbinde_sprache(lambda: "en")
    plugin, _ = baue_plugin(FakeBus({}))
    check("englisch umschaltbar", plugin.t("kachel.nicht_verbunden") == "not connected")
    kern_texte.verbinde_sprache(lambda: "de")


async def pruefe_openlinkhub():
    print("\n== OpenLinkHub ==")
    geraete = olh_mod.lies(olh_antwort(A=("Modell M", 40, 1), B=("Modell H", 62, 2),
                                       C=("Modell T", 100, 0), D=("Modell X", 7, 9)))
    nach = {g.kennung: g for g in geraete}
    check("Maus, Headset und Tastatur nach DeviceType",
          [nach[k].typ for k in ("olh:A", "olh:B", "olh:C")] == ["maus", "headset", "tastatur"],
          str([g.typ for g in geraete]))
    check("ein unbekannter Typ wird „sonstiges“", nach["olh:D"].typ == "sonstiges")
    check("Stand und Name kommen an",
          (nach["olh:A"].prozent, nach["olh:A"].modell) == (40.0, "Modell M"))
    check("ohne Ladeangabe gilt das Gerät nicht als ladend", not nach["olh:A"].laedt)

    q = olh_mod.OpenLinkHubQuelle(abholer=kein_openlinkhub)
    check("ohne OpenLinkHub still leer", q.auffrischen() == {} and not q.vorhanden)
    q = olh_mod.OpenLinkHubQuelle(abholer=lambda u, t: olh_antwort(A=("Modell M", 40, 1)))
    check("mit OpenLinkHub ein Gerät", list(q.auffrischen()) == ["olh:A"] and q.vorhanden)
    q = olh_mod.OpenLinkHubQuelle(abholer=lambda u, t: b"<html>")
    try:
        q.auffrischen()
        unverstanden = False
    except olh_mod.OpenLinkHubFehler:
        unverstanden = True
    check("eine fremde Antwort ist ein Fehler, keine leere Liste", unverstanden)

    import socket
    with socket.socket() as frei:
        frei.bind(("127.0.0.1", 0))
        port = frei.getsockname()[1]
    try:
        olh_mod.abholen(f"http://127.0.0.1:{port}/api/batteryStats", 2.0)
        abgelehnt = False
    except olh_mod.NichtErreichbar:
        abgelehnt = True
    check("ein geschlossener Port heißt: kein OpenLinkHub", abgelehnt)

    print("\n== OpenLinkHub im Plugin ==")
    modul.TAKT_S = 0.02
    bus = FakeBus({BASIS + "mouse_m": props(5, 64.0, modell="Modell A", serie="SN-M")})
    antwort = olh_antwort(SN1=("Modell C", 40, 1), SN2=("Modell A", 64, 1))
    plugin, services = baue_plugin(bus, olh=lambda u, t: antwort)
    await plugin.setup()
    try:
        maus = ctx_for(services, "level", {"device": "olh:SN1"}, index=1)
        await plugin.on_tick("level", maus.settings, maus)
        await asyncio.sleep(0.2)
        alle = plugin.geraete()
        check("das Corsair-Gerät steht in der Liste", "olh:SN1" in alle, str(sorted(alle)))
        check("ein Gerät, das UPower schon kennt, zählt nur einmal", "olh:SN2" not in alle)
        ansicht = plugin.ansicht("level", maus.settings, maus)
        check("die Taste zeigt Name und Stand", (ansicht.titel, ansicht.gross) == ("Modell C", "40%"),
              f"{ansicht.titel} · {ansicht.gross}")
        check("der Status nennt OpenLinkHub", "OpenLinkHub" in plugin.get_status()["detail"],
              plugin.get_status()["detail"])
        optionen = await plugin.get_dynamic_options("geraete")
        check("und die Auswahlliste bietet es an",
              any(o["value"] == "olh:SN1" for o in optionen), str(optionen))
    finally:
        await plugin.teardown()


async def pruefe_nach_abbau():
    print("\n== Nach dem Abbau ==")
    modul.TAKT_S = 0.02
    bus = FakeBus({BASIS + "mouse_m": props(5, 64.0, modell="Modell A", serie="SN-M")})
    bus.ausfall = True
    plugin, services = baue_plugin(bus)
    await plugin.setup()
    await plugin.teardown()
    vorher = list(services.runtime.meldungen)
    plugin.get_status()
    await plugin._frage_faellige()
    await asyncio.sleep(0.1)
    check("nach teardown wird nichts mehr gefragt", bus.aufrufe == [], str(bus.aufrufe))
    check("und nichts mehr gemeldet", services.runtime.meldungen == vorher,
          str(services.runtime.meldungen[len(vorher):]))
    plugin._melde_einmal("upower", "spaete Meldung")
    check("auch eine Antwort, die noch unterwegs war, meldet nichts",
          services.runtime.meldungen == vorher)


def main() -> int:
    kern_texte.verbinde_sprache(lambda: "de")
    pruefe_felder()
    pruefe_headset_lesen()
    asyncio.run(pruefe_headset_quelle())
    asyncio.run(pruefe_upower_quelle())
    asyncio.run(pruefe_plugin())
    asyncio.run(pruefe_ausfall())
    asyncio.run(pruefe_openlinkhub())
    asyncio.run(pruefe_nach_abbau())
    pruefe_texte()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
