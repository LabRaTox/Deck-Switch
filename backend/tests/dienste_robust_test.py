"""Prüft Ton, Soundboard, Overlay, Pegel und Sitzung in Randfällen.

Kein Aufruf hier schaltet den Ausgang um, spielt einen Klang ab oder
startet ein Overlay: ``pactl``, ``pw-play``, ``parec`` und ``qml6`` sind
durch Attrappen ersetzt. Die Gerätedaten beim Umschalten haben den Aufbau,
den ``pactl -f json list`` auf einer PipeWire-Sitzung mit EasyEffects und
Loopback-Geräten liefert.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/dienste_robust_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from deckswitch import texte
from deckswitch.services import audio as A
from deckswitch.services import overlay as O
from deckswitch.services import pegel as pg
from deckswitch.services import session as sess
from deckswitch.services import sound as S

FAILS = []


def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c:
        FAILS.append(n)


# ==========================================================================
print("Ausgang wechseln: welche Streams umziehen")

SINKS = [
    {"index": 43, "name": "game_sink",
     "properties": {"node.virtual": "true", "node.link-group": "loopback-1-29",
                    "node.group": "loopback-1-29"}},
    {"index": 93, "name": "alsa_output.lautsprecher", "properties": {}},
    {"index": 87, "name": "alsa_output.kopfhoerer", "properties": {}},
    {"index": 171, "name": "easyeffects_sink",
     "properties": {"node.virtual": "true", "node.link-group": "ee_sink_group"}},
]
STREAMS = [
    # Rückleitung des Loopbacks game_sink: läuft in den EasyEffects-Eingang.
    {"index": 42, "sink": 171,
     "properties": {"node.name": "game_sink.output", "node.virtual": "true",
                    "node.link-group": "loopback-1-29", "node.group": "loopback-1-29"}},
    # Ein gewöhnliches Programm auf dem Lautsprecher.
    {"index": 500, "sink": 93, "properties": {"application.name": "Firefox"}},
    # Ein Programm, das jemand gezielt auf die Kopfhörer gelegt hat.
    {"index": 501, "sink": 87, "properties": {"application.name": "Discord"}},
    # Ein Mitschnitt.
    {"index": 502, "sink": 93, "properties": {"stream.monitor": "true"}},
    # Die Ausgabe von EasyEffects selbst.
    {"index": 503, "sink": 93,
     "properties": {"application.id": "com.github.wwmm.easyeffects"}},
]


def umschalten(vorher: str, ziel: str, *, streams=STREAMS) -> list[list[str]]:
    dienst = A.AudioService()
    dienst.has_pactl = True
    befehle = []

    def run(befehl):
        befehle.append(befehl)
        if befehl[:3] == ["pactl", "-f", "json"]:
            return json.dumps(streams if befehl[-1] == "sink-inputs" else SINKS)
        if befehl[:2] == ["pactl", "get-default-sink"]:
            return vorher + "\n"
        return ""

    dienst._run = run
    dienst.switch_output(ziel)
    check(f"  {vorher} → {ziel}: Standardausgang gesetzt",
          ["pactl", "set-default-sink", ziel] in befehle)
    return [b[2] for b in befehle if b[1] == "move-sink-input"]


bewegt = umschalten("easyeffects_sink", "game_sink")
check("die Rückleitung des Loopbacks zieht nicht in ihr eigenes Gerät", "42" not in bewegt, str(bewegt))
bewegt = umschalten("alsa_output.lautsprecher", "easyeffects_sink")
check("ein gewöhnliches Programm zieht mit", "500" in bewegt, str(bewegt))
check("was gezielt woanders lag, bleibt", "501" not in bewegt, str(bewegt))
check("Mitschnitte bleiben", "502" not in bewegt, str(bewegt))
check("die Ausgabe von EasyEffects läuft nicht in sich selbst", "503" not in bewegt, str(bewegt))
bewegt = umschalten("", "alsa_output.kopfhoerer",
                    streams=[{"index": 600, "sink": 93, "properties": {}},
                             {"index": 601, "sink": 87, "properties": {}}])
check("unbekannter alter Ausgang: gewöhnliche Streams ziehen mit", bewegt == ["600"], str(bewegt))

print("\nUnübersetzte Ausgabe von pactl und wpctl")
gesehen = {}


def run_mit_env(befehl, **kwargs):
    gesehen.update(kwargs.get("env") or {})
    gesehen["_gesetzt"] = "env" in kwargs
    return subprocess.CompletedProcess(befehl, 0, "Volume: 0.40\n", "")


with mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8", "LANGUAGE": "de"}), \
     mock.patch.object(A.subprocess, "run", side_effect=run_mit_env):
    dienst = A.AudioService()
    dienst.has_wpctl = True
    dienst.get_volume(A.DEFAULT_SINK)
check("Aufrufe laufen mit LC_ALL=C.UTF-8", gesehen.get("LC_ALL") == "C.UTF-8", str(gesehen.get("LC_ALL")))
check("LANGUAGE geht nicht vor", "LANGUAGE" not in gesehen)
popen_env = {}


def popen(befehl, **kwargs):
    popen_env.update(kwargs.get("env") or {})
    raise FileNotFoundError(befehl[0])


with mock.patch.object(A.subprocess, "Popen", side_effect=popen):
    dienst = A.AudioService()
    dienst._watch()
check("pactl subscribe ebenso", popen_env.get("LC_ALL") == "C.UTF-8", str(popen_env.get("LC_ALL")))

# ==========================================================================
print("\nSoundboard: Lautstärke aus den Einstellungen")
from sound import plugin as sound_plugin  # noqa: E402

check("0 bleibt 0", sound_plugin._lautstaerke(0) == 0)
check("\"0\" bleibt 0", sound_plugin._lautstaerke("0") == 0)
check("fehlend wird 100", sound_plugin._lautstaerke(None) == 100 and sound_plugin._lautstaerke("") == 100)
check("Unsinn wird 100", sound_plugin._lautstaerke("laut") == 100)
check("nach oben begrenzt", sound_plugin._lautstaerke(400) == 150)

aufrufe = []
plugin = sound_plugin.SoundPlugin.__new__(sound_plugin.SoundPlugin)
plugin.services = SimpleNamespace(sound=SimpleNamespace(play=lambda p, **k: aufrufe.append(k)))
plugin.notify_error = lambda text: aufrufe.append(("fehler", text))
plugin._activate("play", {"path": "/x.wav", "volume": 0},
                 SimpleNamespace(key="k", request_redraw=lambda: None))
check("eine Taste mit 0 % spielt stumm", aufrufe and aufrufe[0].get("volume") == 0, str(aufrufe))

print("\nSoundboard: Zweitweg mit Lautstärke und Ziel")
datei = Path("/klang.mp3")
with mock.patch.object(S.shutil, "which", lambda p: "/usr/bin/mpv" if p == "mpv" else None):
    argv, env = S.fallback_command(datei, "alsa_output.kopfhoerer", 30)
check("mpv bekommt die Lautstärke", "--volume=30" in argv, str(argv))
check("mpv bekommt das Ziel", "--audio-device=pipewire/alsa_output.kopfhoerer" in argv)
with mock.patch.object(S.shutil, "which", lambda p: "/usr/bin/ffplay" if p == "ffplay" else None):
    argv, env = S.fallback_command(datei, "alsa_output.kopfhoerer", 130)
check("ffplay bekommt die Lautstärke, höchstens 100", argv[argv.index("-volume") + 1] == "100", str(argv))
check("ffplay bekommt das Ziel über die Umgebung",
      env and env.get("PIPEWIRE_NODE") == "alsa_output.kopfhoerer"
      and env.get("PULSE_SINK") == "alsa_output.kopfhoerer")
with mock.patch.object(S.shutil, "which", lambda p: "/usr/bin/ffplay" if p == "ffplay" else None):
    argv, env = S.fallback_command(datei, "", 0)
check("ohne Ziel bleibt die Umgebung unverändert", env is None and argv[argv.index("-volume") + 1] == "0")

print("\nSoundboard: eine leere Datei in Schleife")
starts = []


class Sofort:
    """Ein Player, der sofort fertig ist, wie bei einer leeren WAV."""

    def __init__(self, befehl, **_):
        starts.append(time.monotonic())
        self.returncode = None

    def communicate(self):
        self.returncode = 0
        return b"", b""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


leer = Path(os.environ["XDG_DATA_HOME"]) / "leer.wav"
leer.parent.mkdir(parents=True, exist_ok=True)
leer.write_bytes(b"RIFF$\x00\x00\x00WAVEfmt " + b"\x00" * 24)
with mock.patch.object(S.shutil, "which", return_value="/usr/bin/pw-play"), \
     mock.patch.object(S.subprocess, "Popen", Sofort):
    dienst = S.SoundService()
    dienst.play(str(leer), owner="k", loop=True)
    time.sleep(1.6)
    dienst.stop("k")
    anzahl = len(starts)
    time.sleep(0.3)
check("die Schleife startet höchstens ein paar Mal", 2 <= anzahl <= 5, f"{anzahl} Starts in 1,6 s")
check("nach dem Stopp startet nichts mehr", len(starts) == anzahl)

# ==========================================================================
print("\nOverlay: schneller Doppeldruck")


class Qml:
    gestartet = []

    def __init__(self, befehl, **_):
        Qml.gestartet.append(self)
        self.beendet = False

    def poll(self):
        return 0 if self.beendet else None

    def terminate(self):
        self.beendet = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.beendet = True


binding = SimpleNamespace(columns=3, rows=2, dials=0, key_size=72, overlay_x=10, overlay_y=10,
                          is_overlay=True)
deck = SimpleNamespace(binding=binding, label="Overlay", _mark_all_dirty=lambda: None)
runtime = SimpleNamespace(decks={"d": deck}, session=None,
                          config=SimpleNamespace(app=SimpleNamespace(port=8770)))


async def doppeldruck():
    overlay = O.OverlayService(runtime)

    async def langsame_position(_deck, _at):
        await asyncio.sleep(0.2)
        return (10, 10)

    with mock.patch.object(overlay, "available", return_value=(True, "")), \
         mock.patch.object(overlay, "_position", langsame_position), \
         mock.patch.object(O.subprocess, "Popen", Qml), \
         mock.patch.object(O, "ANLAUF_S", 0.05), \
         mock.patch("deckswitch.services.session.finde_qml", return_value="qml6"):
        await asyncio.gather(overlay.show("d"), overlay.show("d"))
    return overlay


overlay = asyncio.run(doppeldruck())
laufend = [q for q in Qml.gestartet if not q.beendet]
check("am Ende läuft genau ein Overlay", len(laufend) == 1, f"{len(laufend)} von {len(Qml.gestartet)}")
check("und das gehört dem Dienst", overlay._prozesse.get("d") is (laufend[0] if laufend else None))

# ==========================================================================
print("\nPegel: ein ruhender Ausgang liefert gar nichts")


class StummesParec:
    """Wie parec an einem schlafenden Ausgang: read() kehrt nie zurück."""

    def __init__(self, befehl, **_):
        self.ende = threading.Event()
        self.stdout = self

    def read(self, n):
        self.ende.wait()
        return b""

    def terminate(self):
        self.ende.set()

    def wait(self, timeout=None):
        return 0

    def close(self):
        pass


kachel = SimpleNamespace(key="seite:dial:0")
with mock.patch.object(pg.subprocess, "Popen", StummesParec), \
     mock.patch.object(pg.shutil, "which", return_value="/usr/bin/parec"), \
     mock.patch.object(pg, "MELDUNG_GILT_S", 0.3), mock.patch.object(pg, "WAECHTER_S", 0.1), \
     mock.patch.object(pg, "NEUSTART_S", 0.05):
    messer = pg.Pegelmesser(lambda: "ausgang", lambda _c: None)
    messer.lesen("@DEFAULT_AUDIO_SINK@", True, kachel)
    time.sleep(1.2)
    rest = [t.name for t in threading.enumerate() if t.name.startswith("pegel-")]
check("ohne Kachel endet die Messung trotzdem", not messer._messungen and not rest, str(rest))

# ==========================================================================
print("\nSitzung: der laufende Compositor steuert die Fenster")


def erkenne(umgebung, bus, pfad):
    vorhanden = set(pfad)

    async def lauf():
        caps = sess.SessionCapabilities()
        with mock.patch.dict(os.environ, umgebung, clear=False), \
             mock.patch.object(sess.shutil, "which",
                               lambda p: f"/usr/bin/{p}" if p in vorhanden else None), \
             mock.patch.object(sess, "_bus_names", mock.AsyncMock(return_value=bus)), \
             mock.patch.object(sess, "_uinput_usable", lambda: (True, "")), \
             mock.patch.object(sess, "_portal_backend_fuer", lambda *_: False):
            await caps.detect()
        return caps

    return asyncio.run(lauf())


ohne = {k: "" for k in ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK")}
hypr = erkenne({**ohne, "XDG_CURRENT_DESKTOP": "Hyprland", "XDG_SESSION_TYPE": "wayland",
                "HYPRLAND_INSTANCE_SIGNATURE": "abc"},
               bus={"org.kde.kglobalaccel"}, pfad=["hyprctl"])
check("Hyprland mit kglobalaccel am Bus nimmt hyprctl",
      hypr.caps[sess.WINDOW_CONTROL].provider == "hyprland", hypr.caps[sess.WINDOW_CONTROL].provider)
sway = erkenne({**ohne, "XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland",
                "SWAYSOCK": "/run/sway.sock"},
               bus={"org.kde.kglobalaccel"}, pfad=["swaymsg"])
check("Sway ebenso mit swaymsg", sway.caps[sess.WINDOW_CONTROL].provider == "sway")
plasma = erkenne({**ohne, "XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"},
                 bus={"org.kde.kglobalaccel"}, pfad=[])
check("Plasma bleibt bei kglobalaccel", plasma.caps[sess.WINDOW_CONTROL].provider == "kglobalaccel")
unbekannt = erkenne({**ohne, "XDG_CURRENT_DESKTOP": "", "XDG_SESSION_TYPE": "wayland"},
                    bus={"org.kde.kglobalaccel"}, pfad=[])
check("ohne erkannten Desktop zählt kglobalaccel weiter",
      unbekannt.caps[sess.WINDOW_CONTROL].provider == "kglobalaccel")

print("\nSitzung: Begründungen folgen der Sprache")
try:
    texte.verbinde_sprache(lambda: "de")
    ohne_bus = erkenne({**ohne, "XDG_CURRENT_DESKTOP": "KDE"}, bus=None, pfad=[])
    deutsch = ohne_bus.reason_for(sess.WINDOW_CONTROL)
    texte.verbinde_sprache(lambda: "en")
    englisch = ohne_bus.reason_for(sess.WINDOW_CONTROL)
finally:
    texte.verbinde_sprache(lambda: texte.VORGABE)
check("reason_for übersetzt beim Lesen", deutsch and englisch and deutsch != englisch,
      f"{deutsch!r} / {englisch!r}")

print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("Alle Prüfungen bestanden.")
