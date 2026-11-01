"""Prüft das Plugin Instant Replay gegen eine Attrappe des Rekorders.

Die Attrappe ist ein eigener Prozess namens ``gpu-screen-recorder``. Sie
spricht das JSON-Protokoll aus der Man-Seite über den Socket von ``-ipc``,
reagiert auf ``SIGINT`` und ``SIGUSR1`` und kann abstürzen. Geprüft wird also
die echte Prozessführung. Aufgenommen wird nichts.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/instant_replay_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import pathlib
import stat
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "instant-replay"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.abhaengigkeiten import angegeben  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

modul = lade(PLUGIN_DIR)
rek = nachbar(modul, "rekorder")

texte.verbinde_sprache(lambda: "de")

FAILS = []

ATTRAPPE = """#!{python}
import json, os, signal, socket, sys, threading, time
args = sys.argv[1:]
if args == ["--help"]:
    print({hilfe!r}); sys.exit(0)
if args == ["--list-monitors"]:
    print("DP-1|2560x1440\\nHDMI-A-1|1920x1080"); sys.exit(0)
open(os.environ["ARGS_DATEI"], "w").write(json.dumps(args))
art = os.environ.get("ART", "gut")
if art == "fehler":
    print("gsr warning: egal", file=sys.stderr)
    print("gsr error: failed to load opengl", file=sys.stderr)
    print("usage: gpu-screen-recorder [...]", file=sys.stderr)
    sys.exit(1)
if art == "stumm":
    sys.exit(3)
pfad = args[args.index("-ipc") + 1]
signale = os.environ["SIGNAL_DATEI"]
def stopp(*a):
    if art == "stur":
        return
    try: os.unlink(pfad)
    except OSError: pass
    os._exit(0)
signal.signal(signal.SIGINT, stopp)
signal.signal(signal.SIGUSR1, lambda *a: open(signale, "a").write("USR1\\n"))
time.sleep(float(os.environ.get("ANLAUF", "0")))
s = socket.socket(socket.AF_UNIX); s.bind(pfad); s.listen(4)
if art == "taub":
    while True: time.sleep(1)
def bediene(c):
    z = c.makefile("r").readline()
    a = json.loads(z)
    if a["name"] == "stop":
        c.sendall(b'{{"id":0,"result":"ok"}}\\n'); os.unlink(pfad); os._exit(0)
    if art == "absage":
        c.sendall(json.dumps({{"id": a["id"], "result": "error", "data": "kein Puffer"}}).encode() + b"\\n")
    else:
        d = (a.get("data") or {{}}).get("seconds", "alles")
        c.sendall(json.dumps({{"id": a["id"], "result": "ok", "data": "/v/Replay_%s.mp4" % d}}).encode() + b"\\n")
    c.close()
    if art == "absturz":
        print("gsr error: encoder lost", file=sys.stderr); os._exit(5)
while True:
    c, _ = s.accept()
    threading.Thread(target=bediene, args=(c,), daemon=True).start()
"""


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []
        self.status = 0

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))

    def publish_plugin_status(self, plugin_id):
        self.status += 1


class Umgebung:
    def __init__(self, hilfe="usage: gpu-screen-recorder [-ipc <socket_path>]"):
        self.ordner = pathlib.Path(tempfile.mkdtemp(prefix="replay"))
        programm = self.ordner / "gpu-screen-recorder"
        programm.write_text(ATTRAPPE.format(python=sys.executable, hilfe=hilfe))
        programm.chmod(programm.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = f"{self.ordner}{os.pathsep}{ALT_PATH}"
        os.environ["XDG_RUNTIME_DIR"] = str(self.ordner)
        os.environ["ARGS_DATEI"] = str(self.ordner / "args")
        os.environ["SIGNAL_DATEI"] = str(self.ordner / "signale")
        os.environ.pop("ART", None)
        os.environ.pop("ANLAUF", None)


ALT_PATH = os.environ["PATH"]


def baue(umgebung, einstellungen=None):
    manifest = Manifest.model_validate(
        json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8")))

    class KeineSymbole:
        def __getattr__(self, name):
            return lambda *a, **k: None

    runtime = FakeRuntime()
    config = default_config()
    config.plugin_settings["instant-replay"] = {
        "folder": str(umgebung.ordner / "clips" / "tief"), **(einstellungen or {})}
    icons = KeineSymbole()
    dienste = Services(audio=None, icons=icons, render=None, runtime=runtime,
                       config=config, plugin_dir=PLUGIN_DIR)
    return modul.InstantReplayPlugin(manifest, dienste), runtime


def belegung(plugin, action_id, einstellungen=None):
    return SlotContext(
        action_id=action_id, settings=dict(einstellungen or {}), appearance=Appearance(),
        input_type="key", index=0, page_id="p", profile_id="q", size=(120, 120),
        services=plugin.services, slot=Slot(plugin_id="instant-replay", action_id=action_id), scratch={},
    )


async def bis(bedingung, frist=5.0):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        await asyncio.sleep(0.02)
    return bedingung()


def lebt(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return not pathlib.Path(f"/proc/{pid}/stat").read_text().split(") ")[-1].startswith("Z")


# -- Reine Funktionen --------------------------------------------------------


def test_argumente():
    print("Befehlszeile")
    socket = pathlib.Path("/run/x.sock")
    os.environ["WAYLAND_DISPLAY"] = "wayland-1"
    a = rek.argumente({"folder": "/v"}, socket)
    wert = lambda schalter, liste=a: liste[liste.index(schalter) + 1]
    check("Wayland nimmt das Portal", wert("-w") == "portal", a)
    check("Portal merkt sich die Freigabe", wert("-restore-portal-session") == "yes")
    check("Vorgaben", (wert("-f"), wert("-r"), wert("-q"), wert("-bm"), wert("-a"), wert("-k"))
          == ("60", "60", "40000", "cbr", "default_output", "auto"))
    check("Ziel und Socket", wert("-o") == "/v" and wert("-ipc") == str(socket))
    del os.environ["WAYLAND_DISPLAY"]
    b = rek.argumente({"audio": "none", "source": "auto"}, socket)
    check("Ohne Wayland erster Monitor", wert("-w", b) == "screen")
    check("Nur beim Portal -restore", "-restore-portal-session" not in b)
    check("Kein Ton heißt kein -a", "-a" not in b)
    c = rek.argumente({"source": "DP-1", "buffer": 1, "fps": 9999, "codec": "murks",
                       "audio": "murks", "bitrate": "x"}, socket)
    check("Monitor wird durchgereicht", wert("-w", c) == "DP-1")
    check("Grenzen", wert("-r", c) == "5" and wert("-f", c) == "240" and wert("-q", c) == "40000")
    check("Unbekannte Werte fallen weg", wert("-k", c) == "auto" and "-a" not in c)
    check("Ordner ~ wird aufgelöst", not str(rek.ziel({})).startswith("~"))


def test_grund():
    print("Grund aus stderr")
    check("letzte Fehlerzeile", rek.grund_aus(
        ["gsr warning: x", "gsr error: failed to load opengl", "usage: gpu"])
        == "failed to load opengl")
    check("ohne Vorsatz die letzte Zeile", rek.grund_aus(["bla", "blub", "usage: x"]) == "blub")
    check("leer bleibt leer", rek.grund_aus(["", "usage: x"]) == "")


# -- Prozess -----------------------------------------------------------------


async def test_lauf():
    print("Start, Speichern, Stopp")
    u = Umgebung()
    plugin, runtime = baue(u, {"buffer": 60})
    await plugin.setup()
    check("Ohne Autostart läuft nichts", plugin._rekorder.zustand == "aus")
    an = belegung(plugin, "toggle")
    clip = belegung(plugin, "save", {"seconds": 30})
    check("Vor dem Start zeigt die Taste aus", plugin.get_state("save", clip.settings, clip) == "aus")
    await plugin.on_key_down("save", clip.settings, clip)
    check("Speichern ohne Lauf meldet das",
          any("läuft nicht" in m for _, m in runtime.meldungen), runtime.meldungen)
    runtime.meldungen.clear()
    clip.scratch.clear()

    os.environ["ANLAUF"] = "0.3"
    await plugin.on_key_down("toggle", {}, an)
    check("Erst startet er", plugin.get_state("toggle", {}, an) == "startet")
    check("Status nennt das Warten", plugin.get_status()["connected"] is False)
    check("Läuft nach dem Socket", await bis(lambda: plugin._rekorder.zustand == "laeuft"))
    check("Status verbunden", plugin.get_status()["connected"] is True, plugin.get_status())
    check("Zielordner angelegt", (u.ordner / "clips" / "tief").is_dir())
    argv = json.loads((u.ordner / "args").read_text())
    check("Socket liegt im Laufzeitordner", argv[argv.index("-ipc") + 1].startswith(str(u.ordner)))
    pid = plugin._rekorder._prozess.pid

    check("Bereit zeigt die Länge", plugin.get_label("save", clip.settings, clip) == "30 s")
    await plugin.on_key_down("save", clip.settings, clip)
    check("Bestätigung auf der Taste", plugin.get_state("save", clip.settings, clip) == "gespeichert")
    check("Text dazu", plugin.get_label("save", clip.settings, clip) == "gespeichert")
    check("Keine Fehlermeldung", not runtime.meldungen, runtime.meldungen)
    check("Pfad kommt zurück",
          await plugin._rekorder.speichern(30) == "/v/Replay_30.mp4")
    check("Ohne Sekunden der ganze Puffer",
          await plugin._rekorder.speichern(0) == "/v/Replay_alles.mp4")

    clip.scratch["ergebnis"] = ("gespeichert", time.monotonic() - 10)
    check("Bestätigung läuft ab", plugin.get_state("save", clip.settings, clip) == "bereit")

    await plugin.on_key_down("toggle", {}, an)
    check("Aus nach dem Stoppen", plugin.get_state("toggle", {}, an) == "aus")
    check("Prozess ist weg", not lebt(pid))
    check("Socket ist weg", not plugin._rekorder.socket.exists())
    check("Gewollter Stopp ist kein Fehler", not runtime.meldungen, runtime.meldungen)
    check("Status leer", plugin.get_status() is None)
    await plugin.teardown()


async def test_laengen():
    print("Clip-Länge")
    u = Umgebung()
    plugin, _ = baue(u, {"buffer": 60})
    c = belegung(plugin, "save", {"seconds": 300})
    check("Länger als der Puffer wird der ganze", plugin._laenge(c.settings, c) == 0)
    plugin.on_dial_rotate("save", c.settings, -1, c)
    check("Vom ganzen Puffer zurück auf 30", plugin._laenge(c.settings, c) == 30, c.scratch)
    plugin.on_dial_rotate("save", c.settings, -1, c)
    plugin.on_dial_rotate("save", c.settings, -1, c)
    plugin.on_dial_rotate("save", c.settings, -1, c)
    plugin.on_dial_rotate("save", c.settings, -1, c)
    check("Unten ist bei 10 Schluss", plugin._laenge(c.settings, c) == 10)
    for _ in range(8):
        plugin.on_dial_rotate("save", c.settings, 1, c)
    check("Oben ist der ganze Puffer", plugin._laenge(c.settings, c) == 0)
    plugin.on_dial_rotate("toggle", {}, 1, c)
    check("Das Einschalten dreht nichts", plugin._laenge(c.settings, c) == 0)


async def test_fehler():
    print("Fehlerfälle")
    u = Umgebung()
    os.environ["ART"] = "fehler"
    plugin, runtime = baue(u)
    an = belegung(plugin, "toggle")
    await plugin.on_key_down("toggle", {}, an)
    check("Scheitern wird Zustand", await bis(lambda: plugin._rekorder.zustand == "fehler"))
    check("Grund aus stderr gemeldet",
          any("failed to load opengl" in m for lv, m in runtime.meldungen if lv == "error"),
          runtime.meldungen)
    check("Status nennt den Grund", "opengl" in plugin.get_status()["detail"])
    check("Taste zeigt Fehler", plugin.get_state("toggle", {}, an) == "fehler")

    runtime.meldungen.clear()
    os.environ["ART"] = "stumm"
    await plugin.on_key_down("toggle", {}, an)
    check("Neuer Versuch nach Fehler", await bis(lambda: runtime.meldungen))
    check("Ohne stderr nennt die Meldung den Code", "Code 3" in runtime.meldungen[0][1], runtime.meldungen)
    await plugin.teardown()

    print("Absturz im Lauf")
    u = Umgebung()
    os.environ["ART"] = "absturz"
    plugin, runtime = baue(u)
    await plugin._starten()
    await bis(lambda: plugin._rekorder.zustand == "laeuft")
    clip = belegung(plugin, "save")
    await plugin.on_key_down("save", {}, clip)
    check("Absturz erkannt", await bis(lambda: plugin._rekorder.zustand == "fehler"))
    check("Grund gemeldet", any("encoder lost" in m for _, m in runtime.meldungen), runtime.meldungen)
    check("Toter Socket wird entfernt", not plugin._rekorder.socket.exists())
    await plugin.teardown()

    print("Absage und Notweg")
    u = Umgebung()
    os.environ["ART"] = "absage"
    plugin, runtime = baue(u)
    await plugin._starten()
    await bis(lambda: plugin._rekorder.zustand == "laeuft")
    clip = belegung(plugin, "save")
    await plugin.on_key_down("save", {}, clip)
    check("Absage erreicht die Taste", plugin.get_state("save", {}, clip) == "fehler")
    check("Absage nennt den Grund", any("kein Puffer" in m for _, m in runtime.meldungen))
    await plugin.teardown()

    u = Umgebung()
    os.environ["ART"] = "taub"
    plugin, runtime = baue(u)
    await plugin._starten()
    await bis(lambda: plugin._rekorder.zustand == "laeuft")
    plugin._rekorder.socket.unlink()
    plugin._rekorder.socket.write_text("")
    pfad = await plugin._rekorder.speichern(10)
    check("Ohne Socket speichert das Signal", pfad == "")
    check("SIGUSR1 kam an", await bis(lambda: (u.ordner / "signale").exists()))
    await plugin.teardown()

    print("Fehlendes Programm und alte Fassung")
    u = Umgebung()
    (u.ordner / "gpu-screen-recorder").unlink()
    os.environ["PATH"] = str(u.ordner)
    plugin, runtime = baue(u)
    await plugin._starten()
    check("Programm fehlt", any("nicht installiert" in m for _, m in runtime.meldungen), runtime.meldungen)
    check("Auswahl bleibt nutzbar", [o["value"] for o in plugin.get_dynamic_options("quellen")]
          == ["auto", "portal", "screen"])

    u = Umgebung(hilfe="usage: gpu-screen-recorder [-w x]")
    plugin, runtime = baue(u)
    await plugin._starten()
    check("Alte Fassung", any("-ipc" in m for _, m in runtime.meldungen), runtime.meldungen)

    u = Umgebung()
    (u.ordner / "datei").write_text("")
    plugin, runtime = baue(u, {"folder": str(u.ordner / "datei" / "unter")})
    await plugin._starten()
    check("Zielordner geht nicht", any("Zielordner" in m for _, m in runtime.meldungen), runtime.meldungen)
    check("Dann startet nichts", plugin._rekorder.zustand == "aus")


async def test_aufraeumen():
    print("Keine Waisen")
    u = Umgebung()
    plugin, runtime = baue(u, {"autostart": True})
    await plugin.setup()
    check("Autostart startet", await bis(lambda: plugin._rekorder.zustand == "laeuft"))
    pid = plugin._rekorder._prozess.pid
    await plugin.teardown()
    check("Teardown beendet den Prozess", not lebt(pid))

    u = Umgebung()
    os.environ["ART"] = "stur"
    plugin, _ = baue(u)
    await plugin._starten()
    await bis(lambda: plugin._rekorder.zustand == "laeuft")
    pid = plugin._rekorder._prozess.pid
    rek.STOPP_S, alt = 0.3, rek.STOPP_S
    await plugin.teardown()
    rek.STOPP_S = alt
    check("Sturer Prozess wird getötet", not lebt(pid))

    print("Übrig gebliebener Rekorder")
    u = Umgebung()
    erster, _ = baue(u)
    await erster._starten()
    await bis(lambda: erster._rekorder.zustand == "laeuft")
    pid = erster._rekorder._prozess.pid
    # Wie nach einem Absturz des Backends: Der Prozess läuft ohne Besitzer weiter.
    erster._rekorder._gewollt = True
    zweiter, runtime = baue(u)
    await zweiter._starten()
    check("Der alte wird beendet", await bis(lambda: not lebt(pid)))
    check("Der neue läuft", await bis(lambda: zweiter._rekorder.zustand == "laeuft"), runtime.meldungen)
    await zweiter.teardown()
    await erster.teardown()


async def test_monitore():
    print("Quellen")
    Umgebung()
    plugin, _ = baue(Umgebung())
    werte = [o["value"] for o in plugin.get_dynamic_options("quellen")]
    check("Monitore aus der Liste", werte == ["auto", "portal", "screen", "DP-1", "HDMI-A-1"], werte)
    check("Fremde Quelle bleibt leer", plugin.get_dynamic_options("x") == [])


def test_manifest():
    print("Manifest")
    roh = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    check("Erste Fassung ohne changelog", "changelog" not in roh and roh["version"] == "1.0.0")
    check("Braucht die App mit Abhängigkeiten", roh["min_app_version"] == "1.4.1")
    check("Abhängigkeit gültig", angegeben(roh["dependencies"])["system"]
          == [{"arch": "gpu-screen-recorder"}])
    alles = json.dumps(roh, ensure_ascii=False)
    check("Kein langer Strich", "—" not in alles)
    for sprache in ("de", "en"):
        inhalt = json.loads((PLUGIN_DIR / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        for aktion in roh["actions"]:
            for zustand in aktion["states"]:
                check(f"{sprache}: Text für {zustand['id']}",
                      f"kachel.{zustand['id']}" in inhalt or zustand["id"] == "bereit")


async def alles():
    await test_lauf()
    await test_laengen()
    await test_fehler()
    await test_aufraeumen()
    await test_monitore()


test_argumente()
test_grund()
test_manifest()
asyncio.run(alles())
os.environ["PATH"] = ALT_PATH
print()
if FAILS:
    print(f"{len(FAILS)} Prüfungen fehlgeschlagen: {FAILS}")
    sys.exit(1)
print("Alles grün.")
