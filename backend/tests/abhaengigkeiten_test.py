"""Prüft, was Plugins mitbringen: Angaben, Python-Pakete und Systempakete.

Der Python-Teil holt ein echtes Paket von PyPI und braucht dafür Netz und
``uv``. Die Systempakete laufen gegen einen nachgestellten Paketmanager: Ein
echter Durchlauf öffnete den Passwortdialog und änderte das System.
"""
import _wache
_wache.sichere_umgebung()

import importlib.metadata, io, json, sys, zipfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch import paths
from deckswitch.plugins import abhaengigkeiten as ab
from deckswitch.plugins import installer
from deckswitch.plugins.loader import PluginRegistry

FAILS = []
def check(name, ok, detail=""):
    print(f"  {'✔' if ok else '✘'} {name}" + (f"  ({detail})" if detail else ""))
    if not ok: FAILS.append(name)

def wirft(aufruf, *argumente, **benannt):
    try:
        aufruf(*argumente, **benannt)
    except (ab.AbhaengigkeitsFehler, installer.InstallError) as exc:
        return str(exc)
    return ""

def archiv(pid, abhaengig, version="1.0.0", code="class P:\n    pass\n"):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr(f"{pid}/manifest.json", json.dumps({
            "id": pid, "name": pid, "version": version, "type": "action",
            "entry": "plugin.py", "class": "P", "dependencies": abhaengig}))
        z.writestr(f"{pid}/plugin.py", code)
    return puffer.getvalue()

def installiere(*argumente, **benannt):
    return installer.install_archive(archiv(*argumente, **benannt))

print("Angaben")
check("leer ist erlaubt", ab.angegeben({}) == {"python": [], "system": []})
check("Name mit Version geht", ab.angegeben({"python": ["icalendar>=6.0"]})["python"] == ["icalendar>=6.0"])
check("eine Adresse wird abgelehnt", wirft(ab.angegeben, {"python": ["x @ https://boese.example/x.whl"]}))
check("Unsinn wird abgelehnt", wirft(ab.angegeben, {"python": ["nicht gültig!"]}))
check("Nicht-Text wird abgelehnt", wirft(ab.angegeben, {"python": [3]}))
check("keine Liste wird abgelehnt", wirft(ab.angegeben, {"python": "icalendar"}))
check("kein Objekt wird abgelehnt", wirft(ab.angegeben, ["icalendar"]))
check("eine Option als Systemname wird abgelehnt", wirft(ab.angegeben, {"system": ["--overwrite=*"]}))
check("auch im Objekt", wirft(ab.angegeben, {"system": [{"arch": "-x"}]}))
check("eine unbekannte Familie wird abgelehnt", wirft(ab.angegeben, {"system": [{"gentoo": "x"}]}))
check("ein leeres Objekt wird abgelehnt", wirft(ab.angegeben, {"system": [{}]}))

print("\nSystempakete")
gerufen = []
fehlend = set()
def fehlt(namen):
    return [n for n in namen if n in fehlend]
HAND = ("sudo", "pacman", "-S")
MANAGER = ab.Paketmanager("arch", fehlt, HAND, ("pacman", "-S"))
original = (ab.paketmanager, ab._starte, ab.shutil.which)
ab.paketmanager = lambda: MANAGER
def starte(befehl):
    gerufen.append(befehl)
    return None
ab._starte = starte
ab.shutil.which = lambda name: "/usr/bin/pkexec" if name == "pkexec" else None

ab.sichere_system(["ffmpeg"])
check("was da ist, fragt nicht nach dem Passwort", gerufen == [])

fehlend.add("ffmpeg")
meldung = wirft(ab.sichere_system, ["ffmpeg"])
check("pkexec wird gefragt", gerufen == [["pkexec", "pacman", "-S", "ffmpeg"]], str(gerufen))
check("bleibt es fehlend, nennt der Fehler den Befehl", "sudo pacman -S ffmpeg" in meldung, meldung)

gerufen.clear()
def starte_und_installiere(befehl):
    gerufen.append(befehl)
    fehlend.clear()
ab._starte = starte_und_installiere
fehlend.add("ffmpeg")
check("kommt es an, ist alles gut", wirft(ab.sichere_system, ["ffmpeg"]) == "" and gerufen)

fehlend.add("gobject")
ab._starte = starte
meldung = wirft(ab.sichere_system, [{"debian": "python3-gi"}])
check("ohne Name für die Familie stoppt es", "python3-gi" in meldung, meldung)
check("ein Eintrag nimmt den Namen der Familie",
      "gobject" in wirft(ab.sichere_system, [{"arch": "gobject", "debian": "python3-gi"}]))

gerufen.clear()
ab.paketmanager = lambda: ab.Paketmanager("fedora", fehlt, ("sudo", "rpm-ostree", "install"),
                                          neustart=True)
meldung = wirft(ab.sichere_system, ["gobject"])
check("auf einem Image ist es immer Handarbeit", gerufen == [] and "rpm-ostree" in meldung, meldung)

ab.paketmanager = lambda: None
meldung = wirft(ab.sichere_system, ["gibtsnicht"])
check("ohne Paketmanager wird nach dem Programm gesucht", "gibtsnicht" in meldung, meldung)

ab.paketmanager = lambda: MANAGER
fehlend.clear(); fehlend.add("ffmpeg")
ab.shutil.which = lambda name: None
meldung = wirft(installiere, "blockiert", {"system": ["ffmpeg"]})
check("was fehlt, stoppt die Installation", "ffmpeg" in meldung, meldung)
check("und das Plugin bleibt draußen", installer._finde_ordner("blockiert") is None)
installiere("blockiert", {})
fehlend.add("ffmpeg")
wirft(installiere, "blockiert", {"system": ["ffmpeg"]}, version="2.0.0")
m = json.loads((installer._finde_ordner("blockiert") / "manifest.json").read_text())
check("eine ältere Fassung bleibt liegen", m["version"] == "1.0.0", m["version"])
ab.paketmanager, ab._starte, ab.shutil.which = original

print("\nPython-Pakete")
PAKET = "iniconfig"
try:
    importlib.metadata.version(PAKET)
    # Liegt es schon in der Umgebung, bewiese der Import nichts mehr.
    PAKET = "tomli-w"
    importlib.metadata.version(PAKET)
    raise SystemExit("Beide Testpakete liegen schon in der Umgebung")
except importlib.metadata.PackageNotFoundError:
    pass
MODUL = PAKET.replace("-", "_")
CODE = f"""
import {MODUL}
from deckswitch.plugins.base import ActionPlugin
class P(ActionPlugin):
    pass
"""

check("uv ist zu finden", ab.finde_uv() is not None, str(ab.finde_uv()))
installiere("mitpaket", {"python": [PAKET]}, code=CODE)
ordner = ab.ordner("mitpaket")
check("das Paket liegt im eigenen Ordner", (ordner / MODUL).is_dir(), str(ordner))
check("keine Zwischenablage bleibt liegen",
      [p.name for p in ordner.parent.iterdir()] == ["mitpaket"])

registry = PluginRegistry()
registry.discover(lambda d: SimpleNamespace(plugin_dir=d), search_paths=[(paths.USER_PLUGINS_DIR, False)])
geladen = registry.get("mitpaket")
check("das Plugin lädt und findet sein Paket", geladen is not None and geladen.error is None,
      geladen.error if geladen else "fehlt")
check("der Ordner steht am Ende des Suchpfads", sys.path[-1] == str(ordner))

stempel = ordner.stat().st_mtime_ns
installiere("mitpaket", {"python": [PAKET]}, version="1.1.0", code=CODE)
check("eine neue Fassung lädt nichts neu, wenn alles da ist", ordner.stat().st_mtime_ns == stempel)

meldung = wirft(installiere, "mitpaket", {"python": [f"{PAKET}>=9999"]}, version="1.2.0", code=CODE)
check("was es nicht gibt, stoppt die Installation", PAKET in meldung, meldung[:120])
check("und der alte Ordner bleibt", (ordner / MODUL).is_dir())

installiere("mitpaket", {}, version="1.3.0", code="class P:\n    pass\n")
check("eine Fassung ohne Pakete räumt den Ordner", not ordner.exists())
check("und den Suchpfad", str(ordner) not in sys.path)

installiere("mitpaket", {"python": [PAKET]}, version="1.4.0", code=CODE)
installer.uninstall("mitpaket")
check("die Pakete gehen mit dem Plugin", not ordner.exists())

print()
if FAILS:
    print("FEHLGESCHLAGEN: " + ", ".join(FAILS)); sys.exit(1)
print("Alle Prüfungen bestanden.")
