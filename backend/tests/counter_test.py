"""Prüft das Zähler-Plugin: zählen, teilen, speichern, Textdatei, Threads.

Gespeichert wird wirklich, aber nur in Wegwerf-Ordnern unter dem
``XDG_DATA_HOME`` des Laufs. Die Textdateien für OBS landen ebenfalls dort.
Netz und Subprozesse braucht das Plugin nicht.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/counter_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import pathlib
import re
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "counter"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import paths  # noqa: E402
from deckswitch.config import Appearance, Page, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

zaehlermod = lade(PLUGIN_DIR)
speicher = nachbar(zaehlermod, "speicher")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))

    def fehler(self):
        return [m for lvl, m in self.meldungen if lvl == "error"]


manifest_dict = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
manifest = Manifest.model_validate(manifest_dict)
icons = IconService()
render_dienst = RenderService(icons)
BASIS = pathlib.Path(tempfile.mkdtemp(prefix="zaehler-", dir=paths.DATA_DIR.parent))


def neue_umgebung(name):
    """Eigener Datenordner, eigene Config, eigenes Plugin."""
    ordner = BASIS / name
    ordner.mkdir(parents=True, exist_ok=True)
    paths.DATA_DIR = ordner / "deckswitch"
    config = default_config()
    services = Services(audio=None, icons=icons, render=render_dienst, runtime=FakeRuntime(),
                        config=config, plugin_dir=PLUGIN_DIR)
    return zaehlermod.CounterPlugin(manifest, services), services, ordner


def ctx_for(services, action, settings, *, index=0, input_type="key", label=""):
    aussehen = Appearance()
    aussehen.label_text = label
    slot = Slot(plugin_id="counter", action_id=action, settings=settings, appearance=aussehen)
    return SlotContext(
        action_id=action, settings=settings, appearance=aussehen, input_type=input_type,
        index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def druck(plugin, c):
    plugin.on_key_down(c.action_id, c.settings, c)
    plugin.on_key_up(c.action_id, c.settings, c)


def platzhalter(text):
    return set(re.findall(r"\{(\w+)\}", text))


def pruefe_texte():
    print("== Manifest und Texte ==")
    check("Manifest ist gültig", manifest.id == "counter")
    for feld, soll in (("version", "1.0.0"), ("min_app_version", "1.4.0"), ("type", "action"),
                       ("author", "LabRaTox"), ("license", "MIT"), ("category", "streaming"),
                       ("icon", "icon.png")):
        check(f"{feld} = {soll}", manifest_dict.get(feld) == soll, str(manifest_dict.get(feld)))
    for feld in ("name", "description", "summary"):
        check(f"{feld} zweisprachig", set(manifest_dict[feld]) == {"de", "en"})
    check("eine erste Fassung hat keinen Changelog", "changelog" not in manifest_dict)
    check("das Icon gibt es", (PLUGIN_DIR / "icon.png").is_file())
    for bild in manifest_dict.get("screenshots", []):
        check(f"Bild {bild} gibt es", (PLUGIN_DIR / bild).is_file())
    ids = [a["id"] for a in manifest_dict["actions"]]
    check("fünf Aktionen", ids == ["increment", "decrement", "set", "show", "dial"], str(ids))

    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text(encoding="utf-8"))
    check("beide Sprachdateien haben dieselben Schlüssel", set(de) == set(en),
          str(set(de) ^ set(en)))
    for k in de:
        if k in en:
            check(f"„{k}“ hat in beiden Sprachen dieselben Platzhalter",
                  platzhalter(de[k]) == platzhalter(en[k]))
    roh = (PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8") + json.dumps(
        de, ensure_ascii=False) + json.dumps(en, ensure_ascii=False)
    check("kein Gedankenstrich im Sichtbaren", "—" not in roh)

    quelltext = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
    benutzt = set(re.findall(r'self\.t\(\s*"([\w.]+)"', quelltext))
    check("jeder benutzte Schlüssel steht in den Sprachdateien", benutzt <= set(de),
          str(benutzt - set(de)))


async def pruefe_zaehlen():
    print("\n== Zählen ==")
    plugin, services, _ = neue_umgebung("zaehlen")
    await plugin.setup()
    hoch = ctx_for(services, "increment", {"counter": "Deaths", "step": 1})
    runter = ctx_for(services, "decrement", {"counter": "deaths", "step": 1,
                                            "floor_zero": True}, index=1)
    zeigen = ctx_for(services, "show", {"counter": " DEATHS "}, index=2)
    setzen = ctx_for(services, "set", {"counter": "Deaths", "value": 10}, index=3)

    for _ in range(3):
        druck(plugin, hoch)
    check("drei Drücke sind drei", plugin.stand.wert("Deaths") == 3)
    check("die Anzeige-Taste sieht denselben Wert, trotz anderer Schreibweise",
          plugin.get_label("show", zeigen.settings, zeigen) == "3")
    druck(plugin, zeigen)
    check("Anzeigen ändert nichts", plugin.stand.wert("Deaths") == 3)
    druck(plugin, runter)
    check("Herunterzählen auf derselben Zahl", plugin.stand.wert("Deaths") == 2)
    for _ in range(5):
        druck(plugin, runter)
    check("mit Untergrenze nicht unter 0", plugin.stand.wert("Deaths") == 0)
    ohne = ctx_for(services, "decrement", {"counter": "Deaths", "floor_zero": False})
    druck(plugin, ohne)
    check("ohne Untergrenze ins Minus", plugin.stand.wert("Deaths") == -1)
    druck(plugin, runter)
    check("im Minus hält die Untergrenze den Wert fest", plugin.stand.wert("Deaths") == -1)
    druck(plugin, setzen)
    check("Auf Wert setzen", plugin.stand.wert("Deaths") == 10)
    fuenf = ctx_for(services, "increment", {"counter": "Deaths", "step": 5})
    druck(plugin, fuenf)
    check("Schrittweite 5", plugin.stand.wert("Deaths") == 15)
    check("runter() mit Boden", zaehlermod.runter(3, 5, True) == 0
          and zaehlermod.runter(-4, 1, True) == -4 and zaehlermod.runter(3, 5, False) == -2)

    halten = ctx_for(services, "set", {"counter": "Deaths", "value": 0})
    halten.is_long_press = True
    druck(plugin, halten)
    check("als Halten-Zweig wirkt dieselbe Aktion genau einmal",
          plugin.stand.wert("Deaths") == 0)
    check("nach jeder Änderung wird neu gezeichnet", services.runtime.redraws > 0)

    leer = ctx_for(services, "increment", {})
    druck(plugin, leer)
    check("ohne Namen zählt der namenlose Zähler", plugin.stand.wert("") == 1)
    check("und heißt auf der Kachel „Zähler“ oder „Counter“",
          plugin._anzeigename("") in ("Zähler", "Counter"))
    check("keine Fehlermeldungen dabei", not services.runtime.fehler(),
          str(services.runtime.fehler()))
    await plugin.teardown()


async def pruefe_dial():
    print("\n== Dial ==")
    plugin, services, _ = neue_umgebung("dial")
    await plugin.setup()
    einst = {"counter": "Wins", "step": 2, "value": 0, "floor_zero": True}
    d = ctx_for(services, "dial", einst, input_type="dial")
    plugin.on_dial_rotate("dial", einst, 3, d)
    check("drei Rasten nach rechts mit Schritt 2 sind 6", plugin.stand.wert("Wins") == 6)
    plugin.on_dial_rotate("dial", einst, -1, d)
    check("eine zurück ist 4", plugin.stand.wert("Wins") == 4)
    plugin.on_dial_rotate("dial", einst, -10, d)
    check("mit Untergrenze nicht unter 0", plugin.stand.wert("Wins") == 0)
    plugin.on_dial_rotate("dial", einst, 5, d)
    plugin.on_dial_push("dial", dict(einst, value=3), d)
    check("Drücken setzt auf den Startwert", plugin.stand.wert("Wins") == 3)

    rechts = ctx_for(services, "increment", {"counter": "Wins", "step": 1}, input_type="dial")
    druck(plugin, rechts)
    check("Hochzählen als Richtungsbelegung zählt bei jedem Auslösen",
          plugin.stand.wert("Wins") == 4)
    plugin.on_dial_rotate("increment", rechts.settings, -2, rechts)
    check("Hochzählen als Dial dreht in beide Richtungen", plugin.stand.wert("Wins") == 2)
    zeigen = ctx_for(services, "show", {"counter": "Wins"})
    plugin.on_dial_rotate("show", zeigen.settings, 4, zeigen)
    check("Anzeigen reagiert nicht aufs Drehen", plugin.stand.wert("Wins") == 2)

    bild = plugin.render("dial", einst, d)
    check("der Touchstrip zeichnet 200 × 100", bild.size == (200, 100), str(bild.size))
    bild = plugin.render("increment", rechts.settings,
                         ctx_for(services, "increment", rechts.settings, label="Eigene"))
    check("eine Taste zeichnet 120 × 120", bild.size == (120, 120), str(bild.size))
    groß = ctx_for(services, "show", {"counter": "Groß"})
    plugin.stand.aendere("Groß", lambda alt: -123456789)
    check("auch eine lange Zahl lässt sich zeichnen",
          plugin.render("show", groß.settings, groß).size == (120, 120))
    await plugin.teardown()


async def pruefe_dauerhaft():
    print("\n== Dauerhaft ==")
    plugin, services, ordner = neue_umgebung("dauerhaft")
    await plugin.setup()
    datei = paths.DATA_DIR / "plugin-data" / "counter" / "zaehler.json"
    a = ctx_for(services, "increment", {"counter": "Alpha", "step": 7})
    druck(plugin, a)
    check("die Datei liegt in einem eigenen Unterordner", datei.is_file(), str(datei))
    inhalt = json.loads(datei.read_text(encoding="utf-8"))
    check("sie ist gültiges JSON mit dem Wert", inhalt["zaehler"]["alpha"]["wert"] == 7,
          json.dumps(inhalt, ensure_ascii=False))
    check("keine temporären Dateien bleiben liegen",
          [p.name for p in datei.parent.iterdir()] == ["zaehler.json"],
          str([p.name for p in datei.parent.iterdir()]))

    # Umbenennen: dieselbe Taste heißt jetzt anders.
    umbenannt = ctx_for(services, "increment", {"counter": "Beta", "step": 1})
    druck(plugin, umbenannt)
    check("der neue Name beginnt bei 0", plugin.stand.wert("Beta") == 1)
    check("der alte behält seinen Wert", plugin.stand.wert("Alpha") == 7)

    neu = zaehlermod.CounterPlugin(manifest, services)
    check("nach einem Neustart ist Alpha noch 7", neu.stand.wert("Alpha") == 7)
    check("und Beta noch 1", neu.stand.wert("Beta") == 1)
    optionen = neu.get_dynamic_options("zaehler", {})
    werte = [o["value"] for o in optionen]
    check("die Vorschläge kennen beide Namen", werte == ["Alpha", "Beta"], str(werte))
    check("mit Wert in der Beschriftung", optionen[0]["label"] == "Alpha · 7",
          optionen[0]["label"])
    check("unbekannte Quellen liefern nichts", neu.get_dynamic_options("x") == [])

    # Unlesbare Datei: beiseitelegen, einmal melden, weiterzählen.
    datei.write_text("{kaputt", encoding="utf-8")
    kaputt = zaehlermod.CounterPlugin(manifest, services)
    services.runtime.meldungen.clear()
    await kaputt.setup()
    check("eine unlesbare Datei wird gemeldet", len(services.runtime.fehler()) == 1,
          str(services.runtime.fehler()))
    beiseite = list(datei.parent.glob("zaehler.json.kaputt-*"))
    check("und beiseitegelegt statt überschrieben", len(beiseite) == 1)
    check("alle Zähler beginnen bei 0", kaputt.stand.wert("Alpha") == 0)

    # Speichern scheitert: einmal melden, im Speicher weiterzählen.
    services.runtime.meldungen.clear()
    sperre = ordner / "gesperrt"
    sperre.write_text("ich bin eine Datei", encoding="utf-8")
    kaputt.stand.datei = sperre / "zaehler.json"
    c = ctx_for(services, "increment", {"counter": "Gamma"})
    druck(plugin=kaputt, c=c)
    druck(plugin=kaputt, c=c)
    check("ohne Speicherplatz zählt es trotzdem", kaputt.stand.wert("Gamma") == 2)
    check("und meldet das genau einmal", len(services.runtime.fehler()) == 1,
          str(services.runtime.fehler()))
    await plugin.teardown()


async def pruefe_threads():
    print("\n== Viele Drücke gleichzeitig ==")
    plugin, services, ordner = neue_umgebung("threads")
    await plugin.setup()
    ausgabe = ordner / "obs" / "stand.txt"
    ausgabe.parent.mkdir(parents=True)
    hoch = ctx_for(services, "increment", {"counter": "Hits", "file_path": str(ausgabe),
                                           "file_template": "{value}"})
    runter = ctx_for(services, "decrement", {"counter": "Hits", "floor_zero": False},
                     index=1)
    THREADS, JE = 16, 60
    start = threading.Barrier(THREADS * 2)

    def drueck(c):
        start.wait()
        for _ in range(JE):
            plugin.on_key_down(c.action_id, c.settings, c)

    def drueck_doppelt(c):
        start.wait()
        for _ in range(JE * 2):
            plugin.on_key_down(c.action_id, c.settings, c)

    faeden = [threading.Thread(target=drueck_doppelt, args=(hoch,)) for _ in range(THREADS)]
    faeden += [threading.Thread(target=drueck, args=(runter,)) for _ in range(THREADS)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=60)
    soll = THREADS * JE * 2 - THREADS * JE
    check(f"{THREADS * JE * 3} Drücke aus {len(faeden)} Threads gehen nicht verloren",
          plugin.stand.wert("Hits") == soll, f"{plugin.stand.wert('Hits')} statt {soll}")
    neu = zaehlermod.CounterPlugin(manifest, services)
    check("auf der Platte steht derselbe Stand", neu.stand.wert("Hits") == soll)
    check("die Textdatei zeigt am Ende den letzten Stand",
          ausgabe.read_text(encoding="utf-8") == str(soll), ausgabe.read_text(encoding="utf-8"))
    check("keine Fehlermeldungen dabei", not services.runtime.fehler(),
          str(services.runtime.fehler()))

    # Die Rechnung oben ist so kurz, dass Python mitten darin kaum den Thread
    # wechselt. Hier wird der Wechsel erzwungen: Ohne Lock gingen dabei
    # Hunderte Zählungen verloren (gemessen: 182 von 960).
    import time
    stand = speicher.Zaehlerstand(ordner / "lock" / "z.json")
    sperre = threading.Barrier(16)

    def langsam():
        sperre.wait()
        for _ in range(60):
            stand.aendere("x", lambda alt: (time.sleep(0.0001), alt + 1)[1])

    faeden = [threading.Thread(target=langsam) for _ in range(16)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=60)
    check("auch mit Threadwechsel mitten in der Rechnung geht keine verloren",
          stand.wert("x") == 960, str(stand.wert("x")))
    await plugin.teardown()


async def pruefe_textdatei():
    print("\n== Textdatei für OBS ==")
    plugin, services, ordner = neue_umgebung("textdatei")
    obs = ordner / "obs"
    obs.mkdir()
    ziel = obs / "deaths.txt"

    # Die Taste mit dem Pfad liegt in der Konfiguration, gedrückt wird eine andere.
    seite = Page(id="seite", name="Test")
    seite.keys[0] = Slot(plugin_id="counter", action_id="show",
                         settings={"counter": "Deaths", "file_path": str(ziel),
                                   "file_template": "Deaths: {wert}"})
    zweite = obs / "en.txt"
    seite.keys[1] = Slot(plugin_id="system", action_id="irgendwas",
                         long_press=Slot(plugin_id="counter", action_id="set",
                                         settings={"counter": "deaths",
                                                   "file_path": str(zweite),
                                                   "file_template": "{name}: {value} {x}"}))
    profil = next(iter(services.config.profiles.values()))
    profil.pages[seite.id] = seite

    await plugin.setup()
    check("nach dem Start steht der gespeicherte Stand schon in der Datei",
          ziel.read_text(encoding="utf-8") == "Deaths: 0")

    hoch = ctx_for(services, "increment", {"counter": "Deaths"})
    druck(plugin, hoch)
    druck(plugin, hoch)
    check("{wert} wird ersetzt, auch wenn eine andere Taste gedrückt wurde",
          ziel.read_text(encoding="utf-8") == "Deaths: 2", ziel.read_text(encoding="utf-8"))
    check("{value} und {name} auch, aus einem Halten-Zweig, fremde Klammern bleiben",
          zweite.read_text(encoding="utf-8") == "Deaths: 2 {x}",
          zweite.read_text(encoding="utf-8"))
    check("keine temporären Dateien im OBS-Ordner",
          sorted(p.name for p in obs.iterdir()) == ["deaths.txt", "en.txt"],
          str(sorted(p.name for p in obs.iterdir())))
    check("eine leere Vorlage schreibt nur die Zahl",
          speicher.fuelle_vorlage("", 5, "x") == "5")

    print("\n== Ungültige Pfade ==")
    services.runtime.meldungen.clear()
    fehlt = ctx_for(services, "increment", {"counter": "Kills",
                                            "file_path": str(ordner / "gibtsnicht" / "k.txt")})
    for _ in range(3):
        druck(plugin, fehlt)
    check("ein fehlender Ordner bricht nichts ab", plugin.stand.wert("Kills") == 3)
    check("und kommt genau einmal als Meldung", len(services.runtime.fehler()) == 1,
          str(services.runtime.fehler()))
    check("die Meldung nennt den Pfad",
          "gibtsnicht" in (services.runtime.fehler() or [""])[0])

    services.runtime.meldungen.clear()
    relativ = ctx_for(services, "increment", {"counter": "Kills", "file_path": "k.txt"})
    druck(plugin, relativ)
    druck(plugin, relativ)
    check("ein relativer Pfad wird einmal abgewiesen", len(services.runtime.fehler()) == 1,
          str(services.runtime.fehler()))
    check("und nicht ins Arbeitsverzeichnis geschrieben", not pathlib.Path("k.txt").exists())

    # Wird der Ordner angelegt, klappt es; fehlt er wieder, kommt die Meldung neu.
    services.runtime.meldungen.clear()
    (ordner / "gibtsnicht").mkdir()
    druck(plugin, fehlt)
    check("ist der Ordner da, wird geschrieben",
          (ordner / "gibtsnicht" / "k.txt").read_text(encoding="utf-8") == "6")
    (ordner / "gibtsnicht" / "k.txt").unlink()
    (ordner / "gibtsnicht").rmdir()
    druck(plugin, fehlt)
    check("nach einem Erfolg darf derselbe Fehler wieder gemeldet werden",
          len(services.runtime.fehler()) == 1, str(services.runtime.fehler()))
    await plugin.teardown()


async def pruefe_anzeige():
    print("\n== Anzeige folgt fremden Änderungen ==")
    plugin, services, _ = neue_umgebung("anzeige")
    await plugin.setup()
    zeigen = ctx_for(services, "show", {"counter": "Score"}, index=5)
    plugin.on_tick("show", zeigen.settings, zeigen)
    vorher = services.runtime.redraws
    plugin.on_tick("show", zeigen.settings, zeigen)
    check("ohne Änderung kein neues Bild", services.runtime.redraws == vorher)
    plugin.stand.aendere("Score", lambda alt: alt + 1)
    plugin.on_tick("show", zeigen.settings, zeigen)
    check("ändert jemand anders den Wert, zeichnet der Tick neu",
          services.runtime.redraws == vorher + 1)

    # render, get_label und on_tick dürfen nichts schreiben.
    datei = paths.DATA_DIR / "plugin-data" / "counter" / "zaehler.json"
    stempel = datei.stat().st_mtime_ns
    original = speicher.schreibe_atomar
    geschrieben = []
    speicher.schreibe_atomar = lambda *a, **k: geschrieben.append(a)
    zaehlermod.schreibe_atomar = speicher.schreibe_atomar
    try:
        plugin.render("show", zeigen.settings, zeigen)
        plugin.get_label("show", zeigen.settings, zeigen)
        plugin.on_tick("show", zeigen.settings, zeigen)
    finally:
        speicher.schreibe_atomar = original
        zaehlermod.schreibe_atomar = original
    check("Zeichnen und Tick schreiben nichts",
          not geschrieben and datei.stat().st_mtime_ns == stempel)
    await plugin.teardown()


async def laufzeit():
    await pruefe_zaehlen()
    await pruefe_dial()
    await pruefe_dauerhaft()
    await pruefe_threads()
    await pruefe_textdatei()
    await pruefe_anzeige()


def main() -> int:
    pruefe_texte()
    asyncio.run(laufzeit())
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} · {', '.join(FAILS)}")
        return 1
    print("Alles grün.")
    return 0


if __name__ == "__main__":
    os.chdir(BASIS)
    raise SystemExit(main())
