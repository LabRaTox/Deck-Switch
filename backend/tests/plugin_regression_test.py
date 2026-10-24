"""Prüft Fehler in Plugins, die schon einmal da waren, damit sie wegbleiben.

Je Abschnitt ein Fall: Messwerte der Systemkacheln, Helligkeit am Dial,
Wecker auf einer unsichtbaren Seite, die Restzeit am Wecker, Signale
fremder Medienspieler und das Nachfragen nach einem Fehlschlag bei Twitch,
YouTube und Govee. Netz und D-Bus kommen nicht vor; was nach draußen
ginge, ist ersetzt und wird gezählt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/plugin_regression_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILTIN = ROOT / "backend" / "plugins"
SOURCES = ROOT / "plugin-sources"

from deckswitch.config import Appearance, Page, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []
        self._loop = None
        self.device_settings = SimpleNamespace(brightness=80)

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, message))

    def publish_plugin_status(self, plugin_id):
        pass


class FakeSound:
    def __init__(self):
        self.gespielt = []

    def play(self, pfad, *, owner, sink="", volume=100, loop=False):
        self.gespielt.append(owner)

    def stop(self, owner):
        pass


ICONS = IconService()


def plugin_aus(ordner: pathlib.Path, klasse: str, *, config=None, sound=None):
    modul = lade(ordner)
    manifest = Manifest.model_validate(json.loads((ordner / "manifest.json").read_text()))
    services = Services(
        audio=None, icons=ICONS, render=RenderService(ICONS), runtime=FakeRuntime(),
        config=config or default_config(), plugin_dir=ordner, sound=sound,
    )
    return modul, getattr(modul, klasse)(manifest, services)


def ctx_for(plugin, action, settings, *, plugin_id, index=0, input_type="key", page_id="p"):
    slot = Slot(plugin_id=plugin_id, action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id=page_id, profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=plugin.services, slot=slot,
    )


# --------------------------------------------------------------------------


def systemwerte():
    print("== Systemkacheln: Tick, Zeichnen und Beschriftung sehen denselben Wert ==")
    sysmod = nachbar(lade(BUILTIN / "system", name="pruef_system_regress"), "sysinfo")
    info = sysmod.SystemInfo()
    info.cpu_percent()
    info.network("", "down")
    # Etwas Last, damit die Auslastung sicher über null liegt.
    ende = time.monotonic() + 1.0
    while time.monotonic() < ende:
        pass
    tick = info.cpu_percent()
    zeichnen = info.cpu_percent()
    beschriftung = info.cpu_percent()
    check("die CPU zeigt nach einer Sekunde Last mehr als 0 %", tick.value > 0, tick.text)
    check("Zeichnen kurz danach zeigt denselben Wert", zeichnen.text == tick.text,
          f"{tick.text} / {zeichnen.text}")
    check("die Beschriftung auch", beschriftung.text == tick.text, beschriftung.text)
    netz_tick = info.network("", "down")
    netz_zeichnen = info.network("", "down")
    check("beim Netz genauso", netz_zeichnen.text == netz_tick.text,
          f"{netz_tick.text} / {netz_zeichnen.text}")
    time.sleep(sysmod.RATE_MIN_S + 0.05)
    check("nach dem Mindestabstand wird neu gemessen",
          info.cpu_percent() is not tick)


def helligkeit():
    print("\n== Helligkeit am Dial folgt dem Deck, nicht der Vorlage ==")
    config = default_config()
    config.device.brightness = 50
    _, plugin = plugin_aus(BUILTIN / "streamdeck", "StreamdeckPlugin", config=config)
    plugin.services.runtime.device_settings.brightness = 80
    gezeichnet = []
    render = plugin.services.render
    original = render.draw_bar
    render.draw_bar = lambda bild, wert, **k: (gezeichnet.append(wert), original(bild, wert, **k))
    ctx = ctx_for(plugin, "brightness", {}, plugin_id="streamdeck", input_type="dial")
    plugin.render("brightness", {}, ctx)
    check("der Balken steht auf 80 %", gezeichnet == [0.8], str(gezeichnet))


def _timer_mit_wecker(uhrzeit: str):
    config = default_config()
    profil = config.active_profile()
    seite = Page(name="zwei")
    seite.keys[3] = Slot(plugin_id="timer", action_id="alarm",
                         settings={"time": uhrzeit, "days": "daily", "sound": "bell"},
                         appearance=Appearance())
    profil.pages[seite.id] = seite
    sound = FakeSound()
    modul, plugin = plugin_aus(SOURCES / "timer", "TimerPlugin", config=config, sound=sound)
    return modul, plugin, sound, f"{seite.id}:key:3"


def wecker_unsichtbar():
    print("\n== Ein Wecker klingelt auch, wenn seine Seite nie zu sehen war ==")
    for _ in range(2):
        jetzt = datetime.now()
        _, plugin, sound, schluessel = _timer_mit_wecker(jetzt.strftime("%H:%M"))
        plugin._suche_wecker()
        plugin._runde()
        if datetime.now().minute == jetzt.minute:
            break
    check("der Wächter kennt den Wecker", schluessel in plugin._laeufe)
    check("und er hat geklingelt", sound.gespielt == [schluessel], str(sound.gespielt))


def wecker_restzeit():
    print("\n== Die Restzeit am Wecker wird nachgezeichnet ==")
    basis = datetime.now().replace(second=5, microsecond=0)
    modul, plugin, _, _ = _timer_mit_wecker((basis + timedelta(hours=2)).strftime("%H:%M"))
    versatz = {"min": 0}

    class Uhr(datetime):
        @classmethod
        def now(cls, tz=None):
            return basis + timedelta(minutes=versatz["min"])

    original = modul.datetime
    modul.datetime = Uhr
    try:
        settings = {"time": (basis + timedelta(hours=2)).strftime("%H:%M")}
        ctx = ctx_for(plugin, "alarm", settings, plugin_id="timer", index=5)
        runtime = plugin.services.runtime
        plugin.on_tick("alarm", settings, ctx)
        vorher = runtime.redraws
        plugin.on_tick("alarm", settings, ctx)
        check("ohne Änderung kein Neuzeichnen", runtime.redraws == vorher)
        versatz["min"] = 2
        plugin.on_tick("alarm", settings, ctx)
        check("zwei Minuten später wird neu gezeichnet", runtime.redraws == vorher + 1,
              str(runtime.redraws - vorher))
    finally:
        modul.datetime = original


def fremde_player():
    print("\n== Signale eines fremden Medienspielers ändern Spotify nicht ==")
    from dbus_next import Message, MessageType, Variant

    mpris = nachbar(lade(SOURCES / "spotify", name="pruef_spotify_regress"), "mpris")
    player = mpris.MprisPlayer("spotify")
    player._bus_name = "org.mpris.MediaPlayer2.spotify"
    player._owner = ":1.5"

    def signal(absender, titel):
        return Message(
            message_type=MessageType.SIGNAL, path=mpris.OBJECT_PATH,
            interface=mpris.PROPS_IFACE, member="PropertiesChanged", sender=absender,
            signature="sa{sv}as",
            body=[mpris.PLAYER_IFACE, {
                "PlaybackStatus": Variant("s", "Playing"),
                "Metadata": Variant("a{sv}", {"xesam:title": Variant("s", titel)}),
            }, []],
        )

    player._handle_signal(signal(":1.9", "Video im Browser"))
    check("der Browser bleibt außen vor",
          player.state.title == "" and player.state.status == "Stopped",
          f"{player.state.status} {player.state.title!r}")
    player._handle_signal(signal(":1.5", "Lied"))
    check("der eigene Player kommt an",
          player.state.title == "Lied" and player.state.playing, player.state.title)


async def nachfragen_nach_fehler():
    print("\n== Nach einem Fehlschlag wird nicht jede Sekunde neu gefragt ==")

    # Twitch
    twitchmod, twitch = plugin_aus(SOURCES / "twitch", "TwitchPlugin")
    apimod = nachbar(twitchmod, "twitch_api")
    twitch.api.anmeldung.access_token = "t"
    twitch.api.anmeldung.benutzer_id = "1"
    zaehler = {"twitch": 0, "youtube": 0, "govee": 0}

    def stream_kaputt():
        zaehler["twitch"] += 1
        raise apimod.TwitchError("nicht erreichbar")

    twitch.api.stream = stream_kaputt
    ctx = ctx_for(twitch, "status", {}, plugin_id="twitch")
    for _ in range(3):
        await twitch.on_tick("status", {}, ctx)
    check("Twitch fragt einmal", zaehler["twitch"] == 1, str(zaehler["twitch"]))
    check("und meldet einmal", len(twitch.services.runtime.meldungen) == 1,
          str(twitch.services.runtime.meldungen))

    # YouTube
    config = default_config()
    config.plugin_settings["youtube"] = {"client_id": "x", "client_secret": "y"}
    youtubemod, youtube = plugin_aus(SOURCES / "youtube", "YouTubePlugin", config=config)
    ytapi = nachbar(youtubemod, "youtube_api")
    youtube._uebernimm_konfiguration()
    youtube.api.anmeldung.access_token = "t"

    def sendung_kaputt(**_):
        zaehler["youtube"] += 1
        raise ytapi.YouTubeError("quotaExceeded")

    youtube.api.sendung = sendung_kaputt
    ctx = ctx_for(youtube, "viewers", {}, plugin_id="youtube")
    for _ in range(3):
        await youtube.on_tick("viewers", {}, ctx)
    check("YouTube fragt einmal", zaehler["youtube"] == 1, str(zaehler["youtube"]))
    check("und meldet einmal", len(youtube.services.runtime.meldungen) == 1,
          str(youtube.services.runtime.meldungen))
    youtube._gesehen = 0.0
    check("ohne sichtbare Kachel fragt der Hintergrund nicht", not youtube._sichtbar())

    # Govee
    config = default_config()
    config.plugin_settings["govee"] = {"api_key": "k"}
    goveemod, govee = plugin_aus(SOURCES / "govee", "GoveePlugin", config=config)
    goveeapi = nachbar(goveemod, "govee_api")
    govee._uebernimm_konfiguration()

    def geraet_kaputt(_schluessel):
        zaehler["govee"] += 1
        raise goveeapi.GoveeError("429")

    govee.api.geraet = geraet_kaputt
    settings = {"device": "AA:BB"}
    ctx = ctx_for(govee, "power", settings, plugin_id="govee")
    for _ in range(3):
        await govee.on_tick("power", settings, ctx)
    check("Govee fragt einmal", zaehler["govee"] == 1, str(zaehler["govee"]))
    govee._gefragt["AA:BB"] = time.monotonic() - 10 * goveemod.AUFFRISCHEN_S
    check("ein lange nicht gesehenes Gerät fällt heraus", govee._sichtbar() == [])
    status = govee.get_status()
    check("der Status wartet nicht auf Govee", status["connected"] is False, json.dumps(status))


def main() -> int:
    systemwerte()
    helligkeit()
    wecker_unsichtbar()
    wecker_restzeit()
    fremde_player()
    asyncio.run(nachfragen_nach_fehler())
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
