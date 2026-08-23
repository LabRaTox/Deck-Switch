"""Prüft die Aktion „Lautstärke setzen" gegen einen simulierten Audio-Dienst.

Läuft ohne PipeWire: Statt ``wpctl``/``pactl`` aufzurufen, schreibt der
Fake-Dienst nur mit, *was* das Plugin gesetzt hätte.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/audio_volume_set_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import json, pathlib, sys

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "audio"
sys.path.insert(0, str(PLUGIN_DIR))
from deckswitch.plugins.base import Manifest, Services, SlotContext
from deckswitch.config import Appearance, Slot, default_config
from deckswitch.services.audio import DEFAULT_SINK, VolumeState
from deckswitch.services.icons import IconService
from deckswitch.services.render import RenderService
import plugin as audiomod

FAILS = []
def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c: FAILS.append(n)


class FakeRuntime:
    registry = None
    _loop = None
    def request_redraw(self, ctx=None): pass
    def notify(self, *a, **k): pass


class FakeAudio:
    """Merkt sich Lautstärke und Stummschaltung je Ziel."""
    def __init__(self, volume=0.2, muted=False):
        self.state = VolumeState(volume, muted, True)
        self.calls = []
    def get_volume(self, target=DEFAULT_SINK):
        return self.state
    def set_volume(self, target, value):
        self.calls.append(("set_volume", target, round(value, 4)))
        self.state = VolumeState(value, self.state.muted, True)
    def change_volume(self, target, delta_percent):
        self.calls.append(("change_volume", target, delta_percent))
        neu = max(0.0, min(1.5, self.state.volume + delta_percent / 100.0))
        self.state = VolumeState(neu, self.state.muted, True)
        return self.state
    def set_mute(self, target, muted):
        self.calls.append(("set_mute", target, muted))
        self.state = VolumeState(self.state.volume, muted, True)
    def toggle_mute(self, target=DEFAULT_SINK):
        self.calls.append(("toggle_mute", target))
        self.state = VolumeState(self.state.volume, not self.state.muted, True)
        return self.state.muted
    def list_sinks(self, include_monitors=False): return []
    def list_sources(self, include_monitors=False): return []
    def list_streams(self): return []
    def get_default_sink(self): return ""


manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))


def bau(audio, settings, input_type="key", appearance=None, action="volume_set"):
    services = Services(audio=audio, icons=IconService(), render=RenderService(IconService()),
                        runtime=FakeRuntime(), config=default_config(),
                        plugin_dir=PLUGIN_DIR)
    p = audiomod.AudioPlugin(manifest, services)
    appearance = appearance or Appearance()
    slot = Slot(plugin_id="audio", action_id=action, settings=settings, appearance=appearance)
    ctx = SlotContext(action_id=action, settings=settings, appearance=slot.appearance,
                      input_type=input_type, index=0, page_id="p", profile_id="pr",
                      size=(120, 120) if input_type == "key" else (200, 100),
                      services=services, slot=slot)
    return p, ctx


print("== Manifest ==")
aktion = manifest.action("volume_set")
check("Aktion ist im Manifest", aktion is not None)
check("liegt auf Taste und Dial", aktion and sorted(aktion.inputs) == ["dial", "key"])
schluessel = [f.key for f in aktion.settings_schema] if aktion else []
check("Wertfeld vorhanden", "value" in schluessel, str(schluessel))
wert = next((f for f in aktion.settings_schema if f.key == "value"), None)
check("Wert ist eine Prozentzahl mit Grenzen",
      wert and wert.type == "number" and wert.min == 0 and wert.max == 150)

print()
print("== Druck setzt genau den eingestellten Wert ==")
for prozent, erwartet in [(0, 0.0), (35, 0.35), (100, 1.0), (150, 1.5), (500, 1.5), (-10, 0.0)]:
    audio = FakeAudio(volume=0.2)
    p, ctx = bau(audio, {"value": prozent})
    p.on_key_down("volume_set", ctx.settings, ctx)
    gesetzt = [c for c in audio.calls if c[0] == "set_volume"]
    check(f"{prozent} % → Pegel {erwartet}",
          gesetzt == [("set_volume", DEFAULT_SINK, erwartet)], str(audio.calls))

audio = FakeAudio(volume=0.2)
p, ctx = bau(audio, {})
p.on_key_down("volume_set", ctx.settings, ctx)
check("ohne Einstellung: 50 % als Vorgabe",
      ("set_volume", DEFAULT_SINK, 0.5) in audio.calls, str(audio.calls))

audio = FakeAudio(volume=0.2)
p, ctx = bau(audio, {"value": 40, "target": "alsa_output.usb"})
p.on_key_down("volume_set", ctx.settings, ctx)
check("gewähltes Gerät wird angesprochen",
      ("set_volume", "alsa_output.usb", 0.4) in audio.calls, str(audio.calls))

print()
print("== Stumm ==")
audio = FakeAudio(volume=0.2, muted=True)
p, ctx = bau(audio, {"value": 40})
p.on_key_down("volume_set", ctx.settings, ctx)
check("hebt die Stummschaltung auf", audio.state.muted is False, str(audio.calls))
check("Stummschaltung fällt vor dem Setzen",
      audio.calls[0][0] == "set_mute", str(audio.calls))

audio = FakeAudio(volume=0.2, muted=True)
p, ctx = bau(audio, {"value": 40, "unmute": False})
p.on_key_down("volume_set", ctx.settings, ctx)
check("abgeschaltet bleibt es stumm", audio.state.muted is True, str(audio.calls))
check("gesetzt wird trotzdem", ("set_volume", DEFAULT_SINK, 0.4) in audio.calls)

print()
print("== Zustand zeigt, ob der Wert anliegt ==")
faelle = [(0.4, False, "active"), (0.2, False, "inactive"), (0.4, True, "inactive"),
          (0.405, False, "active"), (0.45, False, "inactive")]
for pegel, stumm, erwartet in faelle:
    audio = FakeAudio(volume=pegel, muted=stumm)
    p, ctx = bau(audio, {"value": 40})
    check(f"Pegel {pegel}{' stumm' if stumm else ''} → {erwartet}",
          p.get_state("volume_set", ctx.settings, ctx) == erwartet)

audio = FakeAudio()
audio.get_volume = lambda target=DEFAULT_SINK: VolumeState()
p, ctx = bau(audio, {"value": 40})
check("Gerät nicht da → nicht aktiv",
      p.get_state("volume_set", ctx.settings, ctx) == "inactive")

print()
print("== Dial ==")
audio = FakeAudio(volume=0.5)
p, ctx = bau(audio, {"value": 40, "step": 3}, input_type="dial")
p.on_dial_rotate("volume_set", ctx.settings, 2, ctx)
check("Drehen ändert relativ, nicht auf den Festwert",
      ("change_volume", DEFAULT_SINK, 6) in audio.calls, str(audio.calls))
p.on_dial_push("volume_set", ctx.settings, ctx)
check("Druck springt auf den Festwert",
      ("set_volume", DEFAULT_SINK, 0.4) in audio.calls, str(audio.calls))

audio = FakeAudio(volume=0.5)
p, ctx = bau(audio, {"value": 40}, input_type="dial")
p.on_touch("volume_set", ctx.settings, 10, 10, ctx)
check("Tippen auf den Streifen setzt ebenfalls",
      ("set_volume", DEFAULT_SINK, 0.4) in audio.calls, str(audio.calls))

print()
print("== Darstellung ==")
audio = FakeAudio(volume=0.4)
p, ctx = bau(audio, {"value": 40})
bild = p.render("volume_set", ctx.settings, ctx)
check("Taste zeichnet in voller Größe", bild.size == (120, 120), str(bild.size))
check("Beschriftung ist der Zielwert",
      p.get_label("volume_set", ctx.settings, ctx) == "40%",
      str(p.get_label("volume_set", ctx.settings, ctx)))

p, ctx = bau(FakeAudio(volume=0.4), {"value": 40}, input_type="dial")
check("auf dem Streifen ist der Zielwert als solcher gekennzeichnet",
      p.get_label("volume_set", ctx.settings, ctx) == "\u00bb 40%",
      str(p.get_label("volume_set", ctx.settings, ctx)))

eigen = Appearance(label_text="Leise")
p, ctx = bau(audio, {"value": 40}, appearance=eigen)
check("eigenes Label hat Vorrang", p.get_label("volume_set", ctx.settings, ctx) is None)

p, ctx = bau(FakeAudio(volume=0.4), {"value": 40}, input_type="dial")
bild = p.render("volume_set", ctx.settings, ctx)
check("Segment zeichnet in Segmentgröße", bild.size == (200, 100), str(bild.size))

p, ctx = bau(FakeAudio(volume=0.4), {"value": 40, "show_bar": False, "show_percent": False},
             input_type="dial")
check("ohne Balken und Prozent zeichnet es trotzdem",
      p.render("volume_set", ctx.settings, ctx).size == (200, 100))

print()
print("== Bestehende Aktionen unberührt ==")
audio = FakeAudio(volume=0.3)
p, ctx = bau(audio, {}, action="volume")
p.on_key_down("volume", ctx.settings, ctx)
check("Lautstärke-Taste schaltet weiter stumm",
      audio.calls == [("toggle_mute", DEFAULT_SINK)], str(audio.calls))

audio = FakeAudio(volume=0.3)
p, ctx = bau(audio, {"step": 5}, input_type="dial", action="volume")
p.on_dial_rotate("volume", ctx.settings, -1, ctx)
check("Lautstärke-Dial dreht weiter relativ",
      audio.calls == [("change_volume", DEFAULT_SINK, -5)], str(audio.calls))

print()
if FAILS:
    print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
    sys.exit(1)
print("Alle Prüfungen bestanden.")
