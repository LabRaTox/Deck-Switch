"""Prüft alle OBS-Aktionen gegen einen simulierten obs-websocket-Server."""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, json, pathlib, sys
sys.path.insert(0, "/home/labratox/Projekte/StreamDeck/backend/plugins/obs")
from deckswitch.plugins.base import Manifest, Services, SlotContext
from deckswitch.config import Appearance, Slot, default_config
import plugin as obsmod

FAILS=[]
def check(n,c,d=""):
    print(("  ✔ " if c else "  ✘ ")+n+(f"  ({d})" if d else ""))
    if not c: FAILS.append(n)

RESPONSES = {
    "GetSceneItemId": {"sceneItemId": 7},
    "GetSceneItemEnabled": {"sceneItemEnabled": False},
    "ToggleInputMute": {"inputMuted": True},
    "GetSourceFilter": {"filterEnabled": False},
    "GetMediaInputStatus": {"mediaState": "OBS_MEDIA_STATE_PLAYING"},
    "SaveSourceScreenshot": {},
    "CreateRecordChapter": {},
}

class FakeRuntime:
    registry=None
    _loop=None
    def request_redraw(self, ctx=None): pass
    def notify(self, *a, **k): pass

manifest = Manifest.model_validate(json.loads(
    pathlib.Path("/home/labratox/Projekte/StreamDeck/backend/plugins/obs/manifest.json").read_text()))

class Probe(obsmod.ObsPlugin):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sent=[]
        self.connected=True
    async def _call(self, request, data=None):
        self.sent.append((request, data or {}))
        return RESPONSES.get(request, {})
    async def _connect(self): pass

services = Services(audio=None, icons=None, render=None, runtime=FakeRuntime(),
                    config=default_config(), plugin_dir=pathlib.Path("."))

def ctx_for(action, settings):
    slot=Slot(plugin_id="obs", action_id=action, settings=settings, appearance=Appearance())
    return SlotContext(action_id=action, settings=settings, appearance=slot.appearance,
                       input_type="key", index=0, page_id="p", profile_id="pr",
                       size=(120,120), services=services, slot=slot)

CASES = [
    ("record",           {},                                        "ToggleRecord"),
    ("stream",           {"confirm": False},                        "ToggleStream"),
    ("replay_buffer",    {},                                        "ToggleReplayBuffer"),
    ("scene_collection", {"collection": "Gaming"},                  "SetCurrentSceneCollection"),
    ("scene",            {"scene": "Intro"},                        "SetCurrentProgramScene"),
    ("scene",            {"scene": "Intro", "preview": True},       "SetCurrentPreviewScene"),
    ("source",           {"scene": "Main", "source": "Cam"},        "SetSceneItemEnabled"),
    ("mute",             {"input": "Mic"},                          "ToggleInputMute"),
    ("media",            {"input": "Clip", "action": "restart"},    "TriggerMediaInputAction"),
    ("studio_mode",      {},                                        "SetStudioModeEnabled"),
    ("filter",           {"source": "Cam", "filter": "Chroma"},     "SetSourceFilterEnabled"),
    ("screenshot",       {"format": "png"},                         "SaveSourceScreenshot"),
    ("transition",       {"transition": "Fade"},                    "SetCurrentSceneTransition"),
    ("virtual_cam",      {},                                        "ToggleVirtualCam"),
]

async def main():
    print("== Jede Aktion sendet den richtigen Request ==")
    for action, settings, expected in CASES:
        p=Probe(manifest, services)
        p.current_scene="Main"; p.replay_active=True; p.recording=True; p.studio_mode=False
        p.plugin_config["screenshot_dir"]="/tmp/sd-shots"
        await p._activate(action, settings, ctx_for(action, settings))
        names=[r for r,_ in p.sent]
        label=f"{action}" + (" (Vorschau)" if settings.get("preview") else "")
        check(f"{label:<22} → {expected}", expected in names, str(names))

    print("\n== Zustandsabhängige Aktionen ==")
    p=Probe(manifest, services); p.recording=True; p.record_paused=False
    await p._activate("record_pause", {}, ctx_for("record_pause", {}))
    check("Pause nur bei laufender Aufnahme", "ToggleRecordPause" in [r for r,_ in p.sent])

    p=Probe(manifest, services); p.recording=False
    await p._activate("record_pause", {}, ctx_for("record_pause", {}))
    check("ohne Aufnahme keine Pause", p.sent==[], str(p.sent))

    p=Probe(manifest, services); p.replay_active=False
    await p._activate("save_replay", {}, ctx_for("save_replay", {}))
    check("Replay nur bei aktivem Puffer", p.sent==[], str(p.sent))

    p=Probe(manifest, services); p.replay_active=True
    await p._activate("save_replay", {}, ctx_for("save_replay", {}))
    check("mit Puffer wird gespeichert", "SaveReplayBuffer" in [r for r,_ in p.sent])

    p=Probe(manifest, services); p.studio_mode=False
    await p._activate("preview_scene", {}, ctx_for("preview_scene", {}))
    check("ohne Studio-Modus kein Übergang", p.sent==[], str(p.sent))

    p=Probe(manifest, services); p.studio_mode=True
    await p._activate("preview_scene", {}, ctx_for("preview_scene", {}))
    check("mit Studio-Modus wird umgeschaltet",
          "TriggerStudioModeTransition" in [r for r,_ in p.sent])

    p=Probe(manifest, services); p.recording=False
    await p._activate("chapter_marker", {}, ctx_for("chapter_marker", {}))
    check("Kapitelmarke nur während Aufnahme", p.sent==[], str(p.sent))

    p=Probe(manifest, services); p.recording=True
    await p._activate("chapter_marker", {"name":"Boss"}, ctx_for("chapter_marker", {"name":"Boss"}))
    sent=dict((r,d) for r,d in p.sent)
    check("Kapitelmarke mit Namen", sent.get("CreateRecordChapter")=={"chapterName":"Boss"}, str(p.sent))

    print("\n== Push-to-Talk ==")
    p=Probe(manifest, services)
    c=ctx_for("mute", {"input":"Mic","mode":"push_to_talk"})
    await p.on_key_down("mute", c.settings, c)
    await p.on_key_up("mute", c.settings, c)
    muted=[d.get("inputMuted") for r,d in p.sent if r=="SetInputMute"]
    check("Drücken öffnet, Loslassen schließt", muted==[False,True], str(muted))

    print("\n== Medien: Abspielen/Pause wechselt ==")
    p=Probe(manifest, services); p._media_states["Clip"]="OBS_MEDIA_STATE_PLAYING"
    await p._activate("media", {"input":"Clip","action":"play_pause"},
                      ctx_for("media", {"input":"Clip","action":"play_pause"}))
    act=[d.get("mediaAction") for r,d in p.sent if r=="TriggerMediaInputAction"]
    check("läuft → Pause", act==["OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"], str(act))
    p=Probe(manifest, services); p._media_states["Clip"]="OBS_MEDIA_STATE_PAUSED"
    await p._activate("media", {"input":"Clip","action":"play_pause"},
                      ctx_for("media", {"input":"Clip","action":"play_pause"}))
    act=[d.get("mediaAction") for r,d in p.sent if r=="TriggerMediaInputAction"]
    check("pausiert → Abspielen", act==["OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"], str(act))

    print("\n== Bestätigung beim Stoppen ==")
    p=Probe(manifest, services); p.streaming=True
    c=ctx_for("stream", {"confirm":True})
    await p._activate("stream", c.settings, c)
    check("erster Druck stoppt nicht", p.sent==[], str(p.sent))
    await p._activate("stream", c.settings, c)
    check("zweiter Druck stoppt", "ToggleStream" in [r for r,_ in p.sent])

    print("\n== Zustände ==")
    p=Probe(manifest, services)
    p.recording=True; p.record_paused=True
    check("Aufnahme pausiert", p.get_state("record", {}, ctx_for("record", {}))=="paused")
    p.connected=False
    check("ohne Verbindung 'offline'", p.get_state("scene", {}, ctx_for("scene", {}))=="offline")

    print()
    print("FEHLGESCHLAGEN: "+", ".join(FAILS) if FAILS else "Alle Prüfungen bestanden.")
    sys.exit(1 if FAILS else 0)

asyncio.run(main())
