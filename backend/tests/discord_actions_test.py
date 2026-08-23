"""Prüft die Discord-Aktionen gegen eine simulierte RPC-Verbindung.

Läuft ohne laufenden Discord-Client: Statt echter Kommandos wird nur
mitgeschrieben, *was* das Plugin senden würde.

Aufruf:

    cd backend
    ../.venv/bin/python tests/discord_actions_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, json, pathlib, sys, tempfile
# Vom Ort dieser Datei aus, nicht von einem festen Pfad: Sonst läuft
# die Suite nur in genau einem Arbeitsverzeichnis eines einzigen
# Rechners.
# Discord ist kein eingebautes Plugin mehr, sondern eines zum Nachinstallieren:
# Die Quelle liegt seit 2026-08-23 unter ``plugin-sources/`` neben dem Backend.
PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "discord"
sys.path.insert(0, str(PLUGIN_DIR))
from PIL import Image
from deckswitch.plugins.base import Manifest, Services, SlotContext
from deckswitch.config import Appearance, IconRef, Slot, default_config
from deckswitch.services.icons import IconService
from deckswitch.services.render import RenderService
import plugin as dcmod

TMP = tempfile.mkdtemp(prefix="discord-test-")

FAILS=[]
def check(n,c,d=""):
    print(("  ✔ " if c else "  ✘ ")+n+(f"  ({d})" if d else ""))
    if not c: FAILS.append(n)

class FakeRuntime:
    registry=None
    _loop=None
    def request_redraw(self, ctx=None): pass
    def notify(self, *a, **k): pass

manifest = Manifest.model_validate(json.loads(
    (PLUGIN_DIR / "manifest.json").read_text()))

class Probe(dcmod.DiscordPlugin):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sent=[]
        self.authenticated=True
    async def _command(self, cmd, args):
        self.sent.append((cmd, args))
        return {}

services = Services(audio=None, icons=None, render=RenderService(IconService()),
                    runtime=FakeRuntime(), config=default_config(),
                    plugin_dir=pathlib.Path("."))

def ctx_for(action, settings, input_type="key", appearance=None):
    appearance = appearance or Appearance()
    slot=Slot(plugin_id="discord", action_id=action, settings=settings, appearance=appearance)
    return SlotContext(action_id=action, settings=settings, appearance=slot.appearance,
                       input_type=input_type, index=0, page_id="p", profile_id="pr",
                       size=(120,120), services=services, slot=slot)

def fresh():
    return Probe(manifest, services)


async def main():
    print("== Jede Aktion sendet das richtige Kommando ==")
    cases = [
        ("mute",         {},                       "SET_VOICE_SETTINGS"),
        ("deafen",       {},                       "SET_VOICE_SETTINGS"),
        ("channel",      {"channel_id": "123"},    "SELECT_VOICE_CHANNEL"),
        ("leave",        {},                       "SELECT_VOICE_CHANNEL"),
        ("text_channel", {"channel_id": "456"},    "SELECT_TEXT_CHANNEL"),
    ]
    for action, settings, expected in cases:
        p = fresh()
        await p._activate(action, settings, ctx_for(action, settings))
        got = p.sent[0][0] if p.sent else "— nichts gesendet —"
        check(f"{action} → {expected}", got == expected, got)

    print("\n== Textkanal ==")
    p = fresh()
    await p._activate("text_channel", {"channel_id": "456"}, ctx_for("text_channel", {"channel_id": "456"}))
    check("richtige Kanal-ID", p.sent[0][1] == {"channel_id": "456"}, str(p.sent[0][1]))

    p = fresh()
    errors=[]
    p.notify_error = lambda m: errors.append(m)
    await p._activate("text_channel", {}, ctx_for("text_channel", {}))
    check("ohne Kanal: Fehlermeldung statt Kommando", not p.sent and errors, errors[0] if errors else "")

    p = fresh()
    p.text_channels=[{"id":"456","name":"allgemein","guild":"Server"}]
    label = p.get_label("text_channel", {"channel_id":"456"}, ctx_for("text_channel", {"channel_id":"456"}))
    check("Beschriftung mit Raute", label == "#allgemein", repr(label))

    p = fresh()
    p.text_channels=[{"id":"456","name":"allgemein","guild":"Server"}]
    p.channels=[{"id":"789","name":"Lounge","guild":"Server"}]
    check("Auswahlliste Textkanäle",
          p.get_dynamic_options("text_channels") == [{"value":"456","label":"Server › #allgemein"}],
          str(p.get_dynamic_options("text_channels")))
    check("Auswahlliste Sprachkanäle unverändert",
          p.get_dynamic_options("voice_channels") == [{"value":"789","label":"Server › Lounge"}],
          str(p.get_dynamic_options("voice_channels")))

    print("\n== Halte-Modi der Mute-Taste ==")
    # Erwartung je Modus: (mute-Wert beim Drücken, mute-Wert beim Loslassen)
    for mode, down, up in [("push_to_talk", False, True), ("push_to_mute", True, False)]:
        p = fresh()
        settings={"mode": mode}
        ctx=ctx_for("mute", settings)
        await p.on_key_down("mute", settings, ctx)
        await p.on_key_up("mute", settings, ctx)
        sent=[args.get("mute") for _, args in p.sent]
        check(f"{mode}: drücken={down}, loslassen={up}", sent == [down, up], str(sent))

    p = fresh()
    settings={"mode": "toggle"}
    ctx=ctx_for("mute", settings)
    await p.on_key_down("mute", settings, ctx)
    await p.on_key_up("mute", settings, ctx)
    check("toggle: nur ein Kommando beim Drücken", len(p.sent) == 1, f"{len(p.sent)} Kommandos")

    print("\n== Alte Belegungen laufen weiter ==")
    # Vor der Umstellung hieß die Einstellung `push_to_talk` (bool).
    p = fresh()
    settings={"push_to_talk": True}
    ctx=ctx_for("mute", settings)
    await p.on_key_down("mute", settings, ctx)
    await p.on_key_up("mute", settings, ctx)
    sent=[args.get("mute") for _, args in p.sent]
    check("altes push_to_talk=True wirkt wie Push-to-Talk", sent == [False, True], str(sent))

    p = fresh()
    settings={"push_to_talk": False}
    ctx=ctx_for("mute", settings)
    await p.on_key_down("mute", settings, ctx)
    check("altes push_to_talk=False schaltet um", len(p.sent) == 1, f"{len(p.sent)} Kommandos")

    p = fresh()
    settings={"push_to_talk": True, "mode": "push_to_mute"}
    ctx=ctx_for("mute", settings)
    await p.on_key_down("mute", settings, ctx)
    check("neues mode schlägt das alte Häkchen", p.sent[0][1].get("mute") is True, str(p.sent))

    print("\n== Zustände ==")
    p = fresh()
    check("Textkanal hat keinen Aktiv-Zustand",
          p.get_state("text_channel", {}, ctx_for("text_channel", {})) == "default")
    p.authenticated=False
    check("ohne Discord 'offline'",
          p.get_state("text_channel", {}, ctx_for("text_channel", {})) == "offline")

    print("\n== Serverlogo als Icon ==")
    check("CDN-URL wird auf PNG fester Größe normiert",
          dcmod._guild_icon_source(
              "https://cdn.discordapp.com/icons/1/abc.webp?size=32")
          == f"https://cdn.discordapp.com/icons/1/abc.png?size={dcmod.GUILD_ICON_PX}")

    logo = pathlib.Path(TMP) / "logo.png"
    Image.new("RGBA", (256, 256), (255, 0, 0, 255)).save(logo)

    p = fresh()
    p.channels=[{"id":"789","name":"Lounge","guild":"Server","guild_id":"g1"}]
    p.guild_icons={"g1": logo}
    settings={"channel_id":"789"}

    icon = p._guild_icon("channel", settings, ctx_for("channel", settings), "inactive")
    expected_px = services.render.icon_px((120,120), Appearance().icon_size)
    check("Kanaltaste bekommt das Logo des Servers",
          icon is not None and icon.size == (expected_px, expected_px),
          str(icon.size if icon else None))
    check("Logo ist rund beschnitten",
          icon is not None and icon.getpixel((0, 0))[3] == 0 and
          icon.getpixel((expected_px//2, expected_px//2))[3] == 255)

    off={"channel_id":"789","guild_icon":False}
    check("abgeschaltet bleibt es beim normalen Icon",
          p._guild_icon("channel", off, ctx_for("channel", off), "inactive") is None)

    custom=Appearance(icon_by_state={"default": IconRef(kind="iconset", name="star")})
    check("eigenes Icon hat Vorrang",
          p._guild_icon("channel", settings,
                        ctx_for("channel", settings, appearance=custom), "inactive") is None)

    check("Server ohne Logo: kein Bild",
          fresh()._guild_icon("channel", settings, ctx_for("channel", settings), "inactive") is None)

    check("Mute-Taste bleibt unberührt",
          p._guild_icon("mute", {}, ctx_for("mute", {}), "default") is None)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(asyncio.run(main()))
