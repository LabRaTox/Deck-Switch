"""Prüft das Speed-Test-Plugin.

Es geht nichts ins Netz. Statt eines Messwerkzeugs laufen kleine Skripte als
echte Prozesse, damit Abbruch und Timeout wirklich Prozesse beenden müssen.
``daten/speedtest/direkt.json`` ist die echte Ausgabe eines Laufs. Die Beispiele
für librespeed-cli und Ookla folgen deren Quelltext und Dokumentation, gemessen
sind sie nicht.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/speedtest_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import importlib.util
import json
import os
import pathlib
import stat
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "speedtest"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import texte  # noqa: E402
from deckswitch.config import Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

modul = lade(PLUGIN_DIR)
mess = nachbar(modul, "messung")
texte.verbinde_sprache(lambda: "de")

DATEN = pathlib.Path(__file__).parent / "daten" / "speedtest"
AUSGABE_DIREKT = (DATEN / "direkt.json").read_text(encoding="utf-8")
AUSGABE_LIBRE = json.dumps([{"timestamp": "2026-01-01T00:00:00Z", "ping": 12.5, "jitter": 1.0,
                             "upload": 40.5, "download": 95.25, "bytes_sent": 1,
                             "bytes_received": 2, "server": {"name": "x", "url": "y"}}])
AUSGABE_OOKLA = "\n".join([
    json.dumps({"type": "testStart"}),
    json.dumps({"type": "result", "ping": {"jitter": 1.0, "latency": 9.5},
                "download": {"bandwidth": 12500000, "bytes": 1},
                "upload": {"bandwidth": 2500000, "bytes": 1}}),
])

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class Laufzeit:
    def __init__(self):
        self.meldungen = []
        self.gespeichert = 0

    def request_redraw(self, ctx=None):
        pass

    def notify(self, stufe, text, **extra):
        self.meldungen.append(str(text))

    def save_config(self):
        self.gespeichert += 1


def plugin_neu(tool=None):
    manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text("utf-8")))
    icons = IconService(None)
    laufzeit = Laufzeit()
    dienste = Services(audio=None, icons=icons, render=RenderService(icons), runtime=laufzeit,
                       config=default_config(), plugin_dir=PLUGIN_DIR)
    plugin = modul.SpeedtestPlugin(manifest, dienste)
    if tool:
        modul.finde = lambda wahl: tool
    return plugin, dienste, laufzeit


def ctx_fuer(dienste, art="key", show="all"):
    einstellungen = {"show": show}
    slot = Slot(plugin_id="speedtest", action_id="test", settings=einstellungen)
    return SlotContext(action_id="test", settings=einstellungen, appearance=slot.appearance,
                       input_type=art, index=0, page_id="p", profile_id="pr",
                       size=(120, 120) if art == "key" else (200, 100), services=dienste,
                       slot=slot)


def skript(ordner, name, inhalt):
    pfad = pathlib.Path(ordner) / name
    pfad.write_text("#!/bin/sh\n" + inhalt, encoding="utf-8")
    pfad.chmod(pfad.stat().st_mode | stat.S_IEXEC)
    return str(pfad)


def lebt(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as datei:
            return datei.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def lies_pids(pfad):
    return [int(z) for z in pathlib.Path(pfad).read_text().split()]


def pruefe_lesen():
    print("== Ausgaben lesen ==")
    e = mess.lies("direkt", AUSGABE_DIREKT)
    check("direkt: Mbit/s bleiben", round(e.down, 1) == 1022.9 and round(e.up, 1) == 52.5)
    check("direkt: Ping", round(e.ping, 1) == 14.0)
    e = mess.lies("librespeed", AUSGABE_LIBRE)
    check("librespeed: Mbit/s bleiben", (e.down, e.up, e.ping) == (95.25, 40.5, 12.5))
    e = mess.lies("ookla", AUSGABE_OOKLA)
    check("ookla: Byte/s werden Mbit/s", (e.down, e.up, e.ping) == (100.0, 20.0, 9.5))
    for name, roh in (("direkt", "kaputt"), ("direkt", "{}"), ("librespeed", "[]"),
                      ("ookla", '{"type":"log"}'),
                      ("direkt", '{"download":"x","upload":1,"ping":1}')):
        try:
            mess.lies(name, roh)
            check(f"unlesbar: {roh[:20]}", False)
        except mess.MessFehler as exc:
            check(f"unlesbar: {roh[:20]}", "lesbares" in str(exc))


def pruefe_richtung():
    print("== Eine Richtung fehlt ==")
    for roh in ('{"download":11.1,"upload":0.0,"ping":151.7}',
                '{"download":0,"upload":1.0,"ping":10}'):
        try:
            mess.lies("direkt", roh)
            check(f"abgelehnt: {roh[:24]}", False)
        except mess.MessFehler as exc:
            check(f"abgelehnt: {roh[:24]}", "nicht messen" in str(exc))


def pruefe_finden():
    print("== Werkzeug finden ==")
    with tempfile.TemporaryDirectory() as ordner:
        alt_pfad, alt_sys = os.environ["PATH"], list(sys.path)
        os.environ["PATH"] = ordner + ":/usr/bin"
        sys.path[:] = [ordner]
        try:
            check("Vorgabe ist die eingebaute Messung", mess.finde()[0] == "direkt")
            check("alte Einstellung fällt auf die Vorgabe", mess.finde("auto")[0] == "direkt")
            befehl = mess.finde("direkt")[1]
            check("eingebaut läuft isoliert als Datei",
                  befehl[:2] == [sys.executable, "-I"] and befehl[2].endswith("direkt.py"))
            check("die Datei liegt im Plugin", pathlib.Path(befehl[2]).is_file())
            skript(ordner, "speedtest", "echo 'speedtest-cli 2.1.3'\n")
            check("speedtest von speedtest-cli gilt nicht als Ookla", mess._ookla() is None)
            skript(ordner, "speedtest", "echo 'Speedtest by Ookla 1.2.0'\n")
            check("Ookla wird erkannt", mess.finde("ookla")[0] == "ookla")
            skript(ordner, "librespeed-cli", "exit 0\n")
            check("feste Wahl gilt", mess.finde("librespeed")[0] == "librespeed")
            for datei in pathlib.Path(ordner).iterdir():
                datei.unlink()
            os.environ["PATH"] = ordner
            try:
                mess.finde("ookla")
                check("fehlendes Werkzeug", False)
            except mess.MessFehler as exc:
                check("fehlendes Werkzeug wird genannt", "ookla" in str(exc))
        finally:
            os.environ["PATH"] = alt_pfad
            sys.path[:] = alt_sys


async def warte_auf(bedingung, sekunden=3.0):
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return True
        await asyncio.sleep(0.02)
    return bedingung()


async def pruefe_messen():
    print("== Messung läuft durch ==")
    with tempfile.TemporaryDirectory() as ordner:
        ausgabe = pathlib.Path(ordner) / "a.json"
        ausgabe.write_text(AUSGABE_DIREKT)
        echo = skript(ordner, "gut", f"cat {ausgabe}\n")
        plugin, dienste, laufzeit = plugin_neu(("direkt", [echo]))
        c = ctx_fuer(dienste)
        await plugin.on_key_down("test", c.settings, c)
        check("Druck startet", plugin.laeuft and plugin.get_state("test", c.settings, c) == "laeuft")
        plugin.render("test", c.settings, c)
        await plugin._messung
        check("Ergebnis steht bereit", round(plugin._letzte.down, 1) == 1022.9)
        check("Ergebnis wird gespeichert", laufzeit.gespeichert == 1 and
              dienste.config.plugin_settings["speedtest"]["letzte_messung"]["up"] > 41)
        for art in ("key", "dial"):
            for show in ("all", "down", "up", "ping"):
                k = ctx_fuer(dienste, art, show)
                bild = plugin.render("test", k.settings, k)
                check(f"Kachel {art}/{show}", bild.size == k.size)

        zweites, _, _ = plugin_neu(("direkt", [echo]))
        zweites.services.config.plugin_settings.update(dienste.config.plugin_settings)
        await zweites.setup()
        check("Ergebnis überlebt den Neustart", round(zweites._letzte.down, 1) == 1022.9)
        await zweites.teardown()

        konfig = plugin.plugin_config
        konfig.pop("letzte_messung")
        plugin.on_plugin_config_changed(konfig)
        check("Formular löscht das Ergebnis nicht", "letzte_messung" in konfig)

        schlecht = skript(ordner, "schlecht", "echo 'ERROR: Unable to connect' >&2\nexit 3\n")
        plugin2, dienste2, laufzeit2 = plugin_neu(("direkt", [schlecht]))
        c2 = ctx_fuer(dienste2)
        await plugin2.on_key_down("test", c2.settings, c2)
        await plugin2._messung
        check("Fehler kommt an", any("Unable to connect" in m for m in laufzeit2.meldungen),
              str(laufzeit2.meldungen))
        check("Zustand Fehler", plugin2.get_state("test", c2.settings, c2) == "fehler")
        plugin2.render("test", c2.settings, c2)


async def pruefe_abbruch():
    print("== Abbruch ==")
    with tempfile.TemporaryDirectory() as ordner:
        pids = pathlib.Path(ordner) / "pids"
        # Ignoriert SIGTERM und hat einen Kindprozess: der härteste Fall.
        zaeh = skript(ordner, "zaeh", (
            "trap '' TERM\n"
            f"sleep 60 &\necho $! >> {pids}\necho $$ >> {pids}\n"
            "while :; do sleep 1; done\n"))
        plugin, dienste, _ = plugin_neu(("direkt", [zaeh]))
        c = ctx_fuer(dienste)
        await plugin.on_key_down("test", c.settings, c)
        await warte_auf(lambda: pids.exists() and len(lies_pids(pids)) == 2)
        alle = lies_pids(pids)
        check("Werkzeug und Kind laufen", all(lebt(p) for p in alle), str(alle))
        await plugin.on_key_down("test", c.settings, c)
        check("Zweiter Druck bricht ab", plugin._bricht_ab)
        await plugin.on_key_down("test", c.settings, c)
        try:
            await plugin._messung
        except asyncio.CancelledError:
            pass
        check("kein Prozess bleibt", await warte_auf(lambda: not any(lebt(p) for p in alle)))
        check("Abbruch ist kein Fehler", plugin.get_state("test", c.settings, c) == "bereit")
        check("Abbruch meldet nichts", not plugin._fehler)

        pids.unlink()
        await plugin.on_key_down("test", c.settings, c)
        await warte_auf(lambda: pids.exists() and len(lies_pids(pids)) == 2)
        alle = lies_pids(pids)
        await plugin.teardown()
        check("teardown lässt keinen Prozess zurück",
              await warte_auf(lambda: not any(lebt(p) for p in alle)))

        pids.unlink()
        echt_messe = mess.messe
        modul.messe = lambda name, befehl: echt_messe(name, befehl, timeout=0.3)
        plugin3, dienste3, laufzeit3 = plugin_neu(("direkt", [zaeh]))
        c3 = ctx_fuer(dienste3)
        await plugin3.on_key_down("test", c3.settings, c3)
        await plugin3._messung
        modul.messe = echt_messe
        check("Timeout wird gemeldet", any("abgebrochen" in m for m in laufzeit3.meldungen))
        alle = lies_pids(pids)
        check("Timeout lässt keinen Prozess zurück",
              await warte_auf(lambda: not any(lebt(p) for p in alle)))


async def pruefe_plan():
    print("== Geplante Messung ==")
    with tempfile.TemporaryDirectory() as ordner:
        gut = skript(ordner, "gut", "echo '[]'\n")
        plugin, dienste, _ = plugin_neu(("librespeed", [gut]))
        check("Vorgabe aus", plugin._runde() is None)
        plugin.plugin_config["repeat_hours"] = 1
        check("ohne sichtbare Kachel nichts", plugin._runde() is None)
        c = ctx_fuer(dienste)
        plugin.on_tick("test", c.settings, c)
        aufgabe = plugin._runde()
        check("sichtbar und fällig startet", aufgabe is not None)
        await aufgabe
        check("nach einem Fehler Pause", plugin._runde() is None)
        plugin._naechster_versuch = 0.0
        plugin._fehler = ""
        plugin._letzte = mess.Ergebnis(1, 1, 1, "x", time.time() - 600)
        check("frische Messung bleibt", plugin._runde() is None)
        plugin._letzte.zeit = time.time() - 3700
        aufgabe = plugin._runde()
        check("alte Messung wird fällig", aufgabe is not None)
        await aufgabe


async def pruefe_anzeige():
    print("== Anzeige ==")
    plugin, dienste, _ = plugin_neu()
    c = ctx_fuer(dienste, "dial")
    plugin.on_dial_rotate("test", c.settings, 1, c)
    check("Drehen wechselt", plugin._anzeige(c.settings, c) == "down")
    plugin.on_dial_rotate("test", c.settings, -1, c)
    plugin.on_dial_rotate("test", c.settings, -1, c)
    check("Drehen läuft im Kreis", plugin._anzeige(c.settings, c) == "ping")
    plugin.on_touch("test", c.settings, 1, 1, c)
    check("Tippen wechselt", plugin._anzeige(c.settings, c) == "all")
    plugin._letzte = mess.Ergebnis(1, 1, 1, "x", time.time() - 7300)
    check("Alter in Stunden", plugin._alter() == "vor 2 h")
    plugin._letzte.zeit = time.time() - 10
    check("Alter ganz frisch", plugin._alter() == "gerade eben")
    check("Komma im Deutschen", plugin._zahl(66.61) == "66,6")
    check("ab 100 ohne Stelle", plugin._zahl(940.4) == "940")


def pruefe_direkt():
    print("== Eingebaute Messung ==")
    spec = importlib.util.spec_from_file_location("direkt_pruefung", PLUGIN_DIR / "direkt.py")
    direkt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(direkt)

    def schub_dann_ruhe(zahl, ende, fehler):
        zahl[0] += 10_000_000
        while time.monotonic() < ende:
            time.sleep(0.01)
            zahl[0] += 1250
        raise direkt.Schluss

    wert = direkt.rate(schub_dann_ruhe, verbindungen=1, anlauf=0.2, messen=0.5)
    check("der Anlauf zählt nicht mit", 0.4 < wert < 1.2, f"{wert:.2f} Mbit/s")

    def abgewiesen(zahl, ende, fehler):
        fehler.append("host: HTTP 429")

    try:
        direkt.rate(abgewiesen, verbindungen=2, anlauf=0.1, messen=0.2)
        check("keine Daten sind ein Fehler", False)
    except OSError as exc:
        check("keine Daten nennen den Grund", "429" in str(exc), str(exc))

    def erst_abgewiesen(zahl, ende, fehler):
        if not fehler:
            raise OSError("kurz weg")
        schub_dann_ruhe(zahl, ende, fehler)

    alt = direkt.PAUSE_S
    direkt.PAUSE_S = 0.01
    wert = direkt.rate(erst_abgewiesen, verbindungen=1, anlauf=0.1, messen=0.3)
    direkt.PAUSE_S = alt
    check("eine Verbindung darf neu anlaufen", wert > 0, f"{wert:.2f} Mbit/s")

    zahl = [0]
    rumpf = direkt.Rumpf(100_000, zahl, time.monotonic() + 5)
    while rumpf.read(65536):
        pass
    check("der Rumpf endet bei seiner Größe", zahl[0] == 100_000)
    rumpf = direkt.Rumpf(100_000, [0], time.monotonic() - 1)
    try:
        rumpf.read()
        check("der Rumpf reißt ab", False)
    except direkt.Schluss:
        check("der Rumpf reißt mit der Messzeit ab", True)

    alt = direkt.verbindungszeit
    zeiten = {"fsn1": 15.0, "nbg1": 12.0, "hil": 120.0}

    def zeit(host):
        standort = host.split("-")[0]
        if standort not in zeiten:
            raise OSError(host)
        return zeiten[standort]

    direkt.verbindungszeit = zeit
    check("der nächste Standort gewinnt", direkt.naechster_standort() == "nbg1-speed.hetzner.com")
    check("Ping ist die kürzeste Zeit", direkt.ping("nbg1-speed.hetzner.com", 3) == 12.0)
    zeiten.clear()
    try:
        direkt.naechster_standort()
        check("kein Standort", False)
    except OSError:
        check("kein Standort ist ein Fehler", True)
    direkt.verbindungszeit = alt


def pruefe_manifest():
    print("== Manifest ==")
    roh = json.loads((PLUGIN_DIR / "manifest.json").read_text("utf-8"))
    check("erste Fassung ohne changelog", "changelog" not in roh)
    check("keine Abhängigkeit", "dependencies" not in roh)
    check("speedtest-cli ist nicht mehr wählbar", "speedtest-cli" not in json.dumps(roh))
    check("kein Gedankenstrich", "—" not in json.dumps(roh, ensure_ascii=False))
    de = set(json.loads((PLUGIN_DIR / "locales/de.json").read_text("utf-8")))
    en = set(json.loads((PLUGIN_DIR / "locales/en.json").read_text("utf-8")))
    check("Sprachen vollständig", de == en, str(de ^ en))


pruefe_lesen()
pruefe_direkt()
pruefe_richtung()
pruefe_finden()
asyncio.run(pruefe_messen())
asyncio.run(pruefe_abbruch())
asyncio.run(pruefe_plan())
asyncio.run(pruefe_anzeige())
pruefe_manifest()

print()
print("FEHLER: " + ", ".join(FAILS) if FAILS else "Alles grün.")
sys.exit(1 if FAILS else 0)
