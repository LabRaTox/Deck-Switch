"""Prüft das Steam-Plugin: VDF lesen, Bibliotheken finden, Bilder, Starten, Anzeige.

Gelesen wird ein nachgebauter Steam-Ordner in einem Wegwerfverzeichnis. Die
Dateien darin haben genau den Aufbau, den Steam unter Linux schreibt, nur
mit neutralen Namen und Nummern. Gestartet wird nichts: Der Prozessaufruf
ist eine Attrappe, die sich die Befehlszeile merkt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/steam_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "steam"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from PIL import Image  # noqa: E402

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

steammod = lade(PLUGIN_DIR)
sd = nachbar(steammod, "steam_daten")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# --------------------------------------------------------------------------
# Beispieldateien im Aufbau, den Steam auf diesem Rechner schreibt
# --------------------------------------------------------------------------

LIBRARYFOLDERS = """"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"{eins}"
\t\t"label"\t\t""
\t\t"contentid"\t\t"1111111111111111111"
\t\t"totalsize"\t\t"0"
\t\t"update_clean_bytes_tally"\t\t"2147632526"
\t\t"time_last_update_verified"\t\t"1791834419"
\t\t"apps"
\t\t{
\t\t\t"9001"\t\t"321906993"
\t\t\t"9002"\t\t"1537142909"
\t\t}
\t}
\t"1"
\t{
\t\t"path"\t\t"{zwei}"
\t\t"label"\t\t""
\t\t"contentid"\t\t"2222222222222222222"
\t\t"totalsize"\t\t"1838857322496"
\t\t"apps"
\t\t{
\t\t\t"1001"\t\t"432632418"
\t\t\t"1002"\t\t"33471534235"
\t\t}
\t}
}
"""

LIBRARYFOLDERS_ALT = """"LibraryFolders"
{
\t"TimeNextStatsReport"\t\t"1500000000"
\t"ContentStatsID"\t\t"-123"
\t"1"\t\t"{zwei}"
}
"""


def appmanifest(appid, name, flags=4, zuletzt=0):
    return f""""AppState"
{{
\t"appid"\t\t"{appid}"
\t"Universe"\t\t"1"
\t"name"\t\t"{name}"
\t"StateFlags"\t\t"{flags}"
\t"installdir"\t\t"{name}"
\t"LastUpdated"\t\t"1783582061"
\t"LastPlayed"\t\t"{zuletzt}"
\t"SizeOnDisk"\t\t"321906993"
\t"buildid"\t\t"24098430"
\t"InstalledDepots"
\t{{
\t\t"{appid}1"
\t\t{{
\t\t\t"manifest"\t\t"8124929965194586177"
\t\t\t"size"\t\t"19265607"
\t\t}}
\t}}
\t"UserConfig"
\t{{
\t\t"language"\t\t"german"
\t}}
}}
"""


REGISTRY = """"Registry"
{
\t"HKLM"
\t{
\t\t"Software"
\t\t{
\t\t\t"Valve"
\t\t\t{
\t\t\t\t"Steam"
\t\t\t\t{
\t\t\t\t\t"SteamPID"\t\t"6128"
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\t"HKCU"
\t{
\t\t"Software"
\t\t{
\t\t\t"Valve"
\t\t\t{
\t\t\t\t"Steam"
\t\t\t\t{
\t\t\t\t\t"language"\t\t"german"
\t\t\t\t\t"SourceModInstallPath"\t\t"/home/nutzer/.local/share/Steam/steamapps\\\\sourcemods"
\t\t\t\t\t"AutoLoginUser"\t\t"nutzer"
{laufend}\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
"""


def schreibe(pfad: pathlib.Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8")


def bild(pfad: pathlib.Path, groesse, farbe) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", groesse, farbe).save(pfad)


ROT = (220, 30, 30)
BLAU = (30, 60, 220)


def baue_steam(home: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Ein Steam wie auf diesem Rechner: nativer Ordner, Verweis, zweite Bibliothek."""
    steam = home / ".local" / "share" / "Steam"
    zweite = home / "spiele"
    (home / ".steam").mkdir(parents=True)
    (steam / "steamapps").mkdir(parents=True)
    os.symlink(steam, home / ".steam" / "steam")
    os.symlink(steam, home / ".steam" / "root")
    schreibe(steam / "steamapps" / "libraryfolders.vdf",
             LIBRARYFOLDERS.replace("{eins}", str(steam)).replace("{zwei}", str(zweite)))
    a = steam / "steamapps"
    schreibe(a / "appmanifest_9001.acf", appmanifest(9001, "Proton Experimental"))
    schreibe(a / "appmanifest_9002.acf", appmanifest(9002, "Steam Linux Runtime 9.0"))
    schreibe(a / "appmanifest_1628350.acf", appmanifest(1628350, "Laufzeit"))
    b = zweite / "steamapps"
    schreibe(b / "appmanifest_1001.acf", appmanifest(1001, "Testspiel Eins", zuletzt=100))
    schreibe(b / "appmanifest_1002.acf", appmanifest(1002, "Testspiel Zwei", flags=518,
                                                     zuletzt=300))
    schreibe(b / "appmanifest_1003.acf", appmanifest(1003, "Testspiel Drei", zuletzt=200))
    schreibe(b / "appmanifest_1004.acf", appmanifest(1004, "Halb geladen", flags=1026))
    schreibe(b / "appmanifest_1005.acf", appmanifest(1005, "", zuletzt=0))
    schreibe(home / ".steam" / "registry.vdf", REGISTRY.replace("{laufend}", ""))

    cache = steam / "appcache" / "librarycache"
    # Heutiger Aufbau: Unterordner mit Prüfsummen-Namen
    bild(cache / "1001" / ("a" * 40) / "library_capsule.jpg", (60, 90), ROT)
    bild(cache / "1001" / ("b" * 40) / "library_header.jpg", (92, 43), BLAU)
    bild(cache / "1001" / ("c" * 40 + ".jpg"), (32, 32), (0, 255, 0))
    # Vorheriger Aufbau: direkt im Ordner der App
    bild(cache / "1002" / "library_600x900.jpg", (60, 90), ROT)
    # Nur ein Banner, in übersetzter Fassung
    bild(cache / "1003" / "header_german.jpg", (92, 43), BLAU)
    # Ältester Aufbau: flach
    bild(cache / "1005_library_600x900.jpg", (60, 90), ROT)
    return steam, zweite


# --------------------------------------------------------------------------
# Attrappen
# --------------------------------------------------------------------------


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


class Aufrufe:
    """Steht anstelle von ``steam_daten.starte`` und merkt sich die Befehle."""

    def __init__(self):
        self.befehle = []
        self.fehler = None

    def __call__(self, befehl, popen=None, timeout=None):
        self.befehle.append(list(befehl))
        if self.fehler is not None:
            raise self.fehler


class FakeProzess:
    def __init__(self, verhalten):
        self.verhalten = verhalten
        self.gewartet = []

    def wait(self, timeout=None):
        self.gewartet.append(timeout)
        if self.verhalten == "dauert" and timeout is not None:
            raise subprocess.TimeoutExpired("steam", timeout)
        return 1 if self.verhalten == "fehler" else 0


def pruefe_vdf(tmp: pathlib.Path):
    print("== VDF lesen ==")
    daten = sd.lies_vdf(LIBRARYFOLDERS.replace("{eins}", "/a").replace("{zwei}", "/b"))
    check("Bibliothek 1 hat ihren Pfad", sd.hole(daten, "libraryfolders", "1", "path") == "/b")
    check("verschachtelte Blöcke", sd.hole(daten, "libraryfolders", "0", "apps", "9002")
          == "1537142909")
    check("Schlüssel ohne Rücksicht auf Groß und Klein",
          sd.hole(daten, "LibraryFolders", "0", "PATH") == "/a")
    check("Fehlendes ergibt None", sd.hole(daten, "libraryfolders", "7", "path") is None)

    reg = sd.lies_vdf(REGISTRY.replace("{laufend}", ""))
    check("doppelter Rückstrich wird zu einem",
          sd.hole(reg, "Registry", "HKCU", "Software", "Valve", "Steam", "SourceModInstallPath")
          == "/home/nutzer/.local/share/Steam/steamapps\\sourcemods")

    acf = sd.lies_vdf(appmanifest(1001, "Testspiel Eins", zuletzt=100))
    check("appmanifest: Name", sd.hole(acf, "AppState", "name") == "Testspiel Eins")
    check("appmanifest: Depot-Block stört nicht",
          sd.hole(acf, "AppState", "InstalledDepots", "10011", "size") == "19265607")

    sonder = sd.lies_vdf(
        '// Kommentar\n"wurzel"\n{\n  "zitat" "sagt \\"hallo\\""\n'
        '  ohne_anfuehrung wert\n  "nur_windows" "x" [$WIN32]\n  "doppelt" "1"\n'
        '  "doppelt" "2"\n  "leer" ""\n}\n')
    w = sd.hole(sonder, "wurzel")
    check("Anführungszeichen im Wert", w.get("zitat") == 'sagt "hallo"', repr(w.get("zitat")))
    check("Wörter ohne Anführung", w.get("ohne_anfuehrung") == "wert")
    check("Bedingung wird übergangen", w.get("nur_windows") == "x")
    check("doppelter Schlüssel: der letzte gilt", w.get("doppelt") == "2")
    check("leerer Wert bleibt leer", w.get("leer") == "")

    abgeschnitten = sd.lies_vdf(appmanifest(1001, "Testspiel Eins")[:120])
    check("abgeschnittene Datei liefert, was da ist",
          sd.hole(abgeschnitten, "AppState", "appid") == "1001")
    check("Unsinn wirft nicht", isinstance(sd.lies_vdf("}}}{{\"a"), dict))
    check("BOM am Anfang", sd.hole(sd.lies_vdf('﻿"a" { "b" "c" }'), "a", "b") == "c")


def pruefe_bibliothek(home: pathlib.Path, steam: pathlib.Path, zweite: pathlib.Path):
    print("\n== Steam und Bibliotheken finden ==")
    orte = sd.finde_steam(home)
    check("ein Steam-Ordner, trotz zweier Verweise", len(orte) == 1, str(orte))
    check("es ist der native", orte and orte[0].pfad == steam.resolve() and not orte[0].flatpak)

    biblio = sd.bibliotheken(orte[0])
    check("beide Bibliotheken", biblio == [steam.resolve(), zweite.resolve()], str(biblio))

    alt = home / "alt" / "Steam"
    (alt / "steamapps").mkdir(parents=True)
    schreibe(alt / "steamapps" / "libraryfolders.vdf",
             LIBRARYFOLDERS_ALT.replace("{zwei}", str(zweite)))
    biblio_alt = sd.bibliotheken(sd.SteamOrt(alt, False))
    check("alte Fassung von libraryfolders.vdf", biblio_alt == [alt.resolve(), zweite.resolve()],
          str(biblio_alt))
    check("eigener Ordner aus den Einstellungen wird gefunden",
          any(o.pfad == alt.resolve() for o in sd.finde_steam(home, str(alt))))

    spiele = sd.finde_spiele(orte)
    check("Proton, Laufzeit und halb geladene fehlen",
          sorted(spiele) == ["1001", "1002", "1003", "1005"], str(sorted(spiele)))
    check("ein Spiel mit ausstehendem Update zählt", "1002" in spiele)
    check("Laufzeit am Namen erkannt", "9002" not in spiele)
    check("Name und letzter Start", spiele["1001"].name == "Testspiel Eins"
          and spiele["1001"].zuletzt == 100)
    check("Bibliothek ist die zweite", spiele["1001"].bibliothek == zweite.resolve())

    print("\n== Flatpak ==")
    fp_home = home / "fp"
    fp_steam = fp_home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
    (fp_steam / "steamapps").mkdir(parents=True)
    schreibe(fp_steam / "steamapps" / "appmanifest_1001.acf", appmanifest(1001, "Testspiel Eins"))
    fp_orte = sd.finde_steam(fp_home)
    check("Flatpak-Ordner gefunden und markiert",
          len(fp_orte) == 1 and fp_orte[0].flatpak, str(fp_orte))
    check("Spiele darin tragen die Marke", sd.finde_spiele(fp_orte)["1001"].flatpak)

    print("\n== Bilder ==")
    b = sd.finde_bild(orte, "1001", "cover")
    check("Cover im Prüfsummen-Unterordner", b is not None and b.name == "library_capsule.jpg",
          str(b))
    b = sd.finde_bild(orte, "1001", "header")
    check("Banner im Prüfsummen-Unterordner", b is not None and b.name == "library_header.jpg")
    b = sd.finde_bild(orte, "1002", "cover")
    check("Cover direkt im App-Ordner", b is not None and b.name == "library_600x900.jpg")
    b = sd.finde_bild(orte, "1002", "header")
    check("fehlt das Banner, kommt das Cover", b is not None and b.name == "library_600x900.jpg")
    b = sd.finde_bild(orte, "1003", "cover")
    check("übersetzte Fassung als Ersatz", b is not None and b.name == "header_german.jpg", str(b))
    b = sd.finde_bild(orte, "1005", "cover")
    check("flacher alter Aufbau", b is not None and b.name == "1005_library_600x900.jpg")
    check("ohne Bild None", sd.finde_bild(orte, "4242", "cover") is None)
    check("keine Pfadspielereien", sd.finde_bild(orte, "../1001", "cover") is None)
    return orte


def pruefe_laufend(tmp: pathlib.Path, home: pathlib.Path, orte):
    print("\n== Laufende Spiele ==")
    proc = tmp / "proc"
    for pid, argv in (
        ("100", ["/usr/bin/bash"]),
        ("200", ["/x/ubuntu12_32/reaper", "SteamLaunch", "AppId=1001", "--", "/x/spiel"]),
        ("300", ["/x/reaper", "SteamLaunch", "AppId=0", "--", "x"]),
        ("400", ["/x/programm", "AppId=1003"]),
    ):
        schreibe(proc / pid / "cmdline", "")
        (proc / pid / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (proc / "self").mkdir()
    (proc / "500").mkdir()  # ohne cmdline, wie ein Prozess, der gerade endet
    laufend = sd.laufende_spiele(proc)
    check("reaper mit SteamLaunch AppId zählt", laufend == {"1001"}, str(laufend))
    check("fehlendes /proc ergibt None", sd.laufende_spiele(tmp / "gibtsnicht") is None)

    check("registry.vdf ohne RunningAppID ergibt nichts",
          sd.laufend_laut_registry(orte, home) == set())
    schreibe(home / ".steam" / "registry.vdf",
             REGISTRY.replace("{laufend}", '\t\t\t\t\t"RunningAppID"\t\t"1003"\n'))
    check("RunningAppID wird gelesen", sd.laufend_laut_registry(orte, home) == {"1003"})
    schreibe(home / ".steam" / "registry.vdf",
             REGISTRY.replace("{laufend}", '\t\t\t\t\t"RunningAppID"\t\t"0"\n'))
    check("RunningAppID 0 heißt nichts", sd.laufend_laut_registry(orte, home) == set())


def pruefe_start():
    print("\n== Startbefehl ==")
    beide = {"steam": "/usr/bin/steam", "flatpak": "/usr/bin/flatpak"}.get
    nur_fp = {"flatpak": "/usr/bin/flatpak"}.get
    nichts = {}.get
    url = "steam://rungameid/1001"
    check("automatisch mit steam", sd.startbefehl(url, "auto", beide) == ["/usr/bin/steam", url])
    check("automatisch ohne steam nimmt Flatpak",
          sd.startbefehl(url, "auto", nur_fp)
          == ["/usr/bin/flatpak", "run", "com.valvesoftware.Steam", url])
    check("ausdrücklich Flatpak", sd.startbefehl(url, "flatpak", beide)[1:3]
          == ["run", "com.valvesoftware.Steam"])
    for weg, quelle, schluessel in (("native", nur_fp, "fehler.steam_fehlt"),
                                    ("flatpak", {"steam": "/s"}.get, "fehler.flatpak_fehlt"),
                                    ("auto", nichts, "fehler.kein_startweg")):
        try:
            sd.startbefehl(url, weg, quelle)
            check(f"{weg} ohne Programm wirft", False)
        except sd.StartFehler as exc:
            check(f"{weg} ohne Programm wirft {schluessel}", exc.schluessel == schluessel)

    print("\n== Aufruf, ohne etwas zu starten ==")
    gesehen = {}

    def popen(verhalten):
        def erzeuge(befehl, **kw):
            gesehen["befehl"] = befehl
            gesehen["kw"] = kw
            gesehen["prozess"] = FakeProzess(verhalten)
            return gesehen["prozess"]
        return erzeuge

    sd.starte(["steam", url], popen=popen("ok"), timeout=0.5)
    check("Befehl wird so übergeben", gesehen["befehl"] == ["steam", url])
    check("losgelöst in eigener Sitzung", gesehen["kw"].get("start_new_session") is True)
    check("Ausgaben gehen ins Leere", gesehen["kw"].get("stdout") == subprocess.DEVNULL)
    check("mit Timeout gewartet", gesehen["prozess"].gewartet == [0.5])

    try:
        sd.starte(["steam", url], popen=popen("fehler"), timeout=0.5)
        check("Fehlercode wird gemeldet", False)
    except sd.StartFehler as exc:
        check("Fehlercode wird gemeldet", exc.schluessel == "fehler.start_code"
              and exc.werte == {"code": 1})

    sd.starte(["steam", url], popen=popen("dauert"), timeout=0.01)
    check("wird es selbst zum Client, ist das kein Fehler", True)

    def kaputt(befehl, **kw):
        raise FileNotFoundError("steam")
    try:
        sd.starte(["steam", url], popen=kaputt)
        check("fehlendes Programm wird gemeldet", False)
    except sd.StartFehler as exc:
        check("fehlendes Programm wird gemeldet", exc.schluessel == "fehler.start")


def mache_plugin(steam_dir="", which=None):
    manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
    config = default_config()
    if steam_dir:
        config.plugin_settings["steam"] = {"steam_dir": steam_dir}
    icons = IconService()
    dienste = Services(audio=None, icons=icons, render=RenderService(icons),
                       runtime=FakeRuntime(), config=config, plugin_dir=PLUGIN_DIR)
    return steammod.SteamPlugin(manifest, dienste)


def ctx_for(plugin, action, settings, *, index=0, input_type="key", label=""):
    aussehen = Appearance()
    aussehen.label_text = label
    slot = Slot(plugin_id="steam", action_id=action, settings=settings, appearance=aussehen)
    return SlotContext(
        action_id=action, settings=settings, appearance=aussehen,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=plugin.services, slot=slot,
    )


def nah(farbe, ziel, toleranz=40):
    return all(abs(a - b) <= toleranz for a, b in zip(farbe[:3], ziel[:3]))


async def pruefe_plugin(home: pathlib.Path, proc_fake):
    texte.verbinde_sprache(lambda: "de")
    aufrufe = Aufrufe()
    sd.starte = aufrufe
    sd.shutil = types.SimpleNamespace(which={"steam": "/usr/bin/steam",
                                             "flatpak": "/usr/bin/flatpak"}.get)
    laufend = set()
    blicke = [0]

    def fake_laufend(proc=None):
        blicke[0] += 1
        return set(laufend)
    sd.laufende_spiele = fake_laufend

    plugin = mache_plugin()
    rt = plugin.services.runtime

    print("\n== Status und Auswahlliste ==")
    check("vor dem ersten Lesen: lädt", plugin.get_status()["detail"] == plugin.t("status.laedt"))
    await plugin._runde()
    check("ohne sichtbare Kachel wird nicht nach laufenden Spielen gesehen", blicke[0] == 0)
    status = plugin.get_status()
    check("Status nennt die Spiele", status == {"connected": True,
                                                "detail": "4 Spiele installiert"}, str(status))
    check("Status wurde gemeldet", rt.status == 1)
    optionen = plugin.get_dynamic_options("spiele")
    check("Liste nach Namen, ohne Namen mit App-ID",
          [o["label"] for o in optionen] == ["App 1005", "Testspiel Drei", "Testspiel Eins",
                                             "Testspiel Zwei"], str(optionen))
    check("Werte sind App-IDs", optionen[2]["value"] == "1001")
    check("unbekannte Quelle ist leer", plugin.get_dynamic_options("quatsch") == [])

    print("\n== Taste „Spiel starten“ ==")
    s = {"game": "1001", "artwork": "cover"}
    c = ctx_for(plugin, "launch", s)
    vorher = plugin.render("launch", s, c)
    check("ohne geladenes Bild das Standardbild", vorher.size == (120, 120))
    check("Label ist der Spielname", plugin.get_label("launch", s, c) == "Testspiel Eins")
    check("eigene Beschriftung gewinnt",
          plugin.get_label("launch", s, ctx_for(plugin, "launch", s, label="X")) is None)

    plugin.on_tick("launch", s, c)
    await plugin._runde()
    check("sichtbar: es wird nach laufenden Spielen gesehen", blicke[0] == 1)
    check("das Cover wurde geladen", plugin._bilder.get(("1001", "cover")) is not None)
    kachel = plugin.render("launch", s, c)
    check("das Cover füllt die Taste", nah(kachel.getpixel((60, 60)), ROT),
          str(kachel.getpixel((60, 60))))
    check("Zustand bereit", plugin.get_state("launch", s, c) == "ready")

    s_banner = {"game": "1001", "artwork": "header"}
    c_banner = ctx_for(plugin, "launch", s_banner, index=1)
    plugin.on_tick("launch", s_banner, c_banner)
    await plugin._runde()
    banner = plugin.render("launch", s_banner, c_banner)
    check("das Banner liegt in der Mitte", nah(banner.getpixel((60, 60)), BLAU),
          str(banner.getpixel((60, 60))))
    check("darüber und darunter nicht", not nah(banner.getpixel((60, 4)), BLAU))

    s_symbol = {"game": "1001", "artwork": "symbol"}
    symbol = plugin.render("launch", s_symbol, ctx_for(plugin, "launch", s_symbol))
    check("„nur Symbol“ zeigt kein Cover", not nah(symbol.getpixel((60, 60)), ROT))

    print("\n== Starten ==")
    await plugin.on_key_down("launch", s, c)
    check("steam bekommt die Adresse",
          aufrufe.befehle[-1] == ["/usr/bin/steam", "steam://rungameid/1001"],
          str(aufrufe.befehle[-1:]))
    check("danach zeigt die Taste „startet“", plugin._zustand("1001") == "starting")
    startet = plugin.render("launch", s, c)
    check("mit gelbem Rand", nah(startet.getpixel((1, 60)), (245, 158, 11)),
          str(startet.getpixel((1, 60))))

    laufend.add("1001")
    plugin._naechster_lauf = 0
    rt.redraws = 0
    await plugin._runde()
    check("läuft es, steht es so da", plugin.get_state("launch", s, c) == "running")
    check("und die Anzeige wurde angestoßen", rt.redraws >= 1)
    laeuft = plugin.render("launch", s, c)
    check("mit grünem Rand", nah(laeuft.getpixel((2, 60)), (34, 197, 94)),
          str(laeuft.getpixel((2, 60))))
    laufend.clear()
    plugin._naechster_lauf = 0
    await plugin._runde()
    check("beendet ist es wieder bereit", plugin.get_state("launch", s, c) == "ready")

    print("\n== Fehler und Meldungen ==")
    leer = {"game": ""}
    await plugin.on_key_down("launch", leer, ctx_for(plugin, "launch", leer))
    await plugin.on_key_down("launch", leer, ctx_for(plugin, "launch", leer))
    fehler = [m for m in rt.meldungen if m[0] == "error"]
    check("ohne Spiel eine Meldung, beim zweiten Mal keine neue", len(fehler) == 1, str(fehler))
    check("die Meldung ist übersetzt", fehler and fehler[0][1] == plugin.t("fehler.kein_spiel"))
    check("ohne Spiel wird nichts aufgerufen", len(aufrufe.befehle) == 1)

    aufrufe.fehler = sd.StartFehler("fehler.start_code", code=3)
    await plugin.on_key_down("launch", s, c)
    await plugin.on_key_down("launch", s, c)
    fehler = [m for m in rt.meldungen if m[0] == "error"]
    check("Startfehler einmal gemeldet", len(fehler) == 2 and "3" in fehler[1][1], str(fehler))
    aufrufe.fehler = None
    await plugin.on_key_down("launch", s, c)
    aufrufe.fehler = sd.StartFehler("fehler.start_code", code=3)
    await plugin.on_key_down("launch", s, c)
    aufrufe.fehler = None
    fehler = [m for m in rt.meldungen if m[0] == "error"]
    check("nach einem Erfolg darf er wieder kommen", len(fehler) == 3, str(len(fehler)))

    plugin._fehlschlag(RuntimeError("Platte weg"))
    plugin._fehlschlag(RuntimeError("Platte weg"))
    check("Backoff wächst", plugin._backoff == 2 * steammod.BACKOFF_MIN_S, str(plugin._backoff))
    fehler = [m for m in rt.meldungen if m[0] == "error"]
    check("dieselbe Hintergrundmeldung nur einmal", len(fehler) == 4, str(len(fehler)))
    blicke_vorher = blicke[0]
    plugin.on_tick("launch", s, c)
    plugin._naechster_lauf = 0
    await plugin._runde()
    check("während der Pause wird nichts gelesen", blicke[0] == blicke_vorher)
    plugin._pause_bis = 0
    await plugin._runde()
    check("nach der Pause wieder", blicke[0] == blicke_vorher + 1)
    check("und der Backoff ist zurückgesetzt", plugin._backoff == 0)

    print("\n== Nicht installiert ==")
    weg = {"game": "4242", "artwork": "cover"}
    cw = ctx_for(plugin, "launch", weg)
    check("Zustand missing", plugin.get_state("launch", weg, cw) == "missing")
    check("Label sagt es", plugin.get_label("launch", weg, cw) == "nicht installiert")
    check("Kachel wird gezeichnet", plugin.render("launch", weg, cw).size == (120, 120))

    print("\n== Steam öffnen ==")
    for ziel, url in (("games", "steam://open/games"), ("store", "steam://store"),
                      ("friends", "steam://open/friends"), ("downloads", "steam://open/downloads"),
                      ("settings", "steam://open/settings"),
                      ("bigpicture", "steam://open/bigpicture")):
        so = {"target": ziel}
        co = ctx_for(plugin, "open", so)
        await plugin.on_key_down("open", so, co)
        check(f"{ziel} → {url}", aufrufe.befehle[-1] == ["/usr/bin/steam", url])
        check(f"{ziel}: Zustand wählt das Symbol", plugin.get_state("open", so, co) == ziel)
        check(f"{ziel}: Label", plugin.get_label("open", so, co) == plugin.t(f"ziel.{ziel}"))
    so = {"target": "quatsch"}
    await plugin.on_key_down("open", so, ctx_for(plugin, "open", so))
    check("Unbekanntes Ziel öffnet die Bibliothek", aufrufe.befehle[-1][-1] == "steam://open/games")
    check("Taste wird gezeichnet",
          plugin.render("open", {"target": "store"},
                        ctx_for(plugin, "open", {"target": "store"})).size == (120, 120))

    print("\n== Dial „Spiele durchblättern“ ==")
    sb = {"source": "recent", "count": 10}
    cb = ctx_for(plugin, "browse", sb, input_type="dial", index=3)
    liste = [x.appid for x in plugin._dial_liste(sb)]
    check("zuletzt gespielte zuerst", liste == ["1002", "1003", "1001", "1005"], str(liste))
    check("„Wie viele“ wird beachtet",
          len(plugin._dial_liste({"source": "recent", "count": 2})) == 2)
    check("am Anfang das erste", plugin._auswahl(sb, cb).appid == "1002")
    plugin.on_dial_rotate("browse", sb, 1, cb)
    check("eins weiter", plugin._auswahl(sb, cb).appid == "1003")
    plugin.on_dial_rotate("browse", sb, -2, cb)
    check("rückwärts über den Anfang hinaus", plugin._auswahl(sb, cb).appid == "1005")
    await plugin.on_dial_push("browse", sb, cb)
    check("Drücken startet das angezeigte",
          aufrufe.befehle[-1] == ["/usr/bin/steam", "steam://rungameid/1005"])
    plugin.on_tick("browse", sb, cb)
    check("Nachbarn werden mit vorgeladen",
          {("1002", "cover"), ("1005", "cover"), ("1001", "cover")} <= set(plugin._gebraucht))
    await plugin._runde()
    segment = plugin.render("browse", sb, cb)
    check("Segment 200×100", segment.size == (200, 100))
    check("Cover links im Segment", nah(segment.getpixel((20, 50)), ROT),
          str(segment.getpixel((20, 50))))

    sa = {"source": "all"}
    check("alle nach Namen", [x.appid for x in plugin._dial_liste(sa)]
          == ["1005", "1003", "1001", "1002"])
    sp = {"source": "pick", "game_1": "1003", "game_2": "", "game_3": "4242", "game_4": "1003",
          "game_5": "1001"}
    check("eigene Auswahl: ohne Lücken, Doppelte und Fremde",
          [x.appid for x in plugin._dial_liste(sp)] == ["1003", "1001"])
    sl = {"source": "pick"}
    cl = ctx_for(plugin, "browse", sl, input_type="dial", index=4)
    vorher = len([m for m in rt.meldungen if m[0] == "error"])
    await plugin.on_dial_push("browse", sl, cl)
    check("leere Liste meldet sich", len([m for m in rt.meldungen if m[0] == "error"]) == vorher + 1)
    check("leere Liste wird gezeichnet", plugin.render("browse", sl, cl).size == (200, 100))
    plugin.on_dial_rotate("browse", sl, 1, cl)
    check("Drehen auf leerer Liste wirft nicht", True)

    cd = ctx_for(plugin, "launch", s, input_type="dial", index=5)
    await plugin.on_dial_push("launch", s, cd)
    check("Spiel starten am Dial", aufrufe.befehle[-1][-1] == "steam://rungameid/1001")
    check("Spiel starten als Segment", plugin.render("launch", s, cd).size == (200, 100))
    await plugin.on_touch("launch", s, 10, 10, cd)
    check("Tippen auf den Streifen startet auch", aufrufe.befehle[-1][-1]
          == "steam://rungameid/1001")

    print("\n== Englisch ==")
    texte.verbinde_sprache(lambda: "en")
    check("Status auf Englisch", plugin.get_status()["detail"] == "4 games installed")
    check("Label auf Englisch", plugin.get_label("launch", weg, cw) == "not installed")
    texte.verbinde_sprache(lambda: "de")

    print("\n== Nur Flatpak ==")
    fp = mache_plugin(steam_dir=str(home / "fp" / ".var" / "app" / "com.valvesoftware.Steam"
                                    / ".local" / "share" / "Steam"))
    # Ohne den nativen Ordner: Heimverzeichnis auf den Flatpak-Baum biegen
    alt_home = os.environ["HOME"]
    os.environ["HOME"] = str(home / "fp")
    try:
        await fp._runde()
        check("Status sagt Flatpak", "Flatpak" in fp.get_status()["detail"], fp.get_status()["detail"])
        await fp.on_key_down("launch", s, ctx_for(fp, "launch", s))
        check("automatisch geht der Aufruf an flatpak run",
              aufrufe.befehle[-1] == ["/usr/bin/flatpak", "run", "com.valvesoftware.Steam",
                                      "steam://rungameid/1001"], str(aufrufe.befehle[-1]))
    finally:
        os.environ["HOME"] = alt_home

    print("\n== Kein Steam ==")
    os.environ["HOME"] = str(home / "leer")
    try:
        nix = mache_plugin()
        await nix._runde()
        check("Status sagt: nicht gefunden",
              nix.get_status() == {"connected": False,
                                   "detail": nix.t("status.nicht_gefunden")})
        check("Auswahlliste mit Hinweis",
              nix.get_dynamic_options("spiele") == [{"value": "",
                                                     "label": nix.t("optionen.keine_spiele")}])
    finally:
        os.environ["HOME"] = alt_home

    print("\n== Hintergrundaufgabe ==")
    await plugin.setup()
    check("setup startet die Schleife", plugin._aufgabe is not None and not plugin._aufgabe.done())
    await plugin.teardown()
    check("teardown beendet sie", plugin._aufgabe is None)

    print("\n== Gezeichnet wird alles ==")
    for aktion, einst in (("launch", s), ("launch", leer), ("open", {"target": "games"}),
                          ("browse", sb)):
        for art, groesse in (("key", (120, 120)), ("dial", (200, 100))):
            if aktion == "browse" and art == "key":
                continue
            bild_ = plugin.render(aktion, einst, ctx_for(plugin, aktion, einst, input_type=art,
                                                         index=9))
            check(f"{aktion} {einst} als {art}", bild_.size == groesse, str(bild_.size))


def pruefe_texte():
    print("\n== Sprachdateien ==")
    import re
    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text())
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text())
    check("dieselben Schlüssel", set(de) == set(en), str(set(de) ^ set(en)))
    platz = [k for k in de if set(re.findall(r"\{(\w+)", de[k]))
             != set(re.findall(r"\{(\w+)", en.get(k, "")))]
    check("dieselben Platzhalter", not platz, str(platz))
    quelltext = "".join(p.read_text() for p in PLUGIN_DIR.glob("*.py") if p.name != "screenshots.py")
    benutzt = set(re.findall(r'self\.t\(\s*["\x27]([a-z_.]+)["\x27]', quelltext))
    benutzt |= set(re.findall(r'StartFehler\(\s*"([a-z_.]+)"', quelltext))
    benutzt |= {f"ziel.{z}" for z in steammod.ZIELE}
    check("jeder benutzte Schlüssel steht in de.json", benutzt <= set(de),
          str(sorted(benutzt - set(de))))
    check("kein Schlüssel ohne Verwendung", set(de) <= benutzt, str(sorted(set(de) - benutzt)))
    alles = [*de.values(), *en.values()]
    manifest_text = (PLUGIN_DIR / "manifest.json").read_text()
    check("kein Gedankenstrich", not any("—" in v for v in alles) and "—" not in manifest_text)
    manifest = json.loads(manifest_text)
    check("eine erste Fassung hat keinen Changelog", "changelog" not in manifest)
    check("summary in beiden Sprachen", set(manifest["summary"]) == {"de", "en"})


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="steam-test-") as tmp:
        tmp = pathlib.Path(tmp)
        home = tmp / "home"
        steam, zweite = baue_steam(home)
        pruefe_vdf(tmp)
        orte = pruefe_bibliothek(home, steam, zweite)
        pruefe_laufend(tmp, home, orte)
        pruefe_start()
        pruefe_texte()
        alt_home = os.environ.get("HOME", "")
        os.environ["HOME"] = str(home)
        try:
            asyncio.run(pruefe_plugin(home, tmp / "proc"))
        finally:
            os.environ["HOME"] = alt_home

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
