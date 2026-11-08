"""Prüft Installieren und Laden von Plugins unter widrigen Umständen.

* Zwei Installationen gleichzeitig dürfen sich nicht gegenseitig löschen.
* Ein Manifest, das kein UTF-8 ist oder eine Liste statt eines Objekts
  enthält, kostet nur dieses eine Plugin. Die übrigen laden weiter, und
  die Installation meldet einen verständlichen Fehler.

Alles läuft im Datenverzeichnis aus ``XDG_DATA_HOME``.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/plugin_robust_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import io
import json
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from deckswitch import paths
from deckswitch.plugins import installer
from deckswitch.plugins.loader import PluginRegistry

FAILS = []


def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c:
        FAILS.append(n)


def archiv(manifest: bytes, dateien: int = 3) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("manifest.json", manifest)
        for i in range(dateien):
            z.writestr(f"icons/i{i}.svg", "<svg/>")
    return puffer.getvalue()


def iconset(kennung: str) -> bytes:
    return archiv(json.dumps(
        {"id": kennung, "name": kennung, "version": "1.0.0", "type": "iconset"}
    ).encode())


def bestand_auf_platte() -> dict[str, str]:
    ergebnis = {}
    for eintrag in sorted(paths.USER_PLUGINS_DIR.iterdir()):
        datei = eintrag / "manifest.json"
        if eintrag.name.isdigit() and datei.is_file():
            ergebnis[eintrag.name] = json.loads(datei.read_text())["id"]
    return ergebnis


# ==========================================================================
print("Zwei Installationen zur selben Zeit")
shutil.rmtree(paths.USER_PLUGINS_DIR, ignore_errors=True)
paths.USER_PLUGINS_DIR.mkdir(parents=True)

# Die Ordnerwahl künstlich verlangsamen: Ohne Sperre wählen beide Threads
# in diesem Fenster dieselbe freie Nummer.
original = installer._ordner_fuer


def langsam(kennung):
    ziel = original(kennung)
    time.sleep(0.3)
    return ziel


installer._ordner_fuer = langsam
ergebnis = {}


def installiere(name, daten):
    try:
        ergebnis[name] = installer.install_archive(daten).id
    except Exception as exc:
        ergebnis[name] = repr(exc)


threads = [
    threading.Thread(target=installiere, args=("a", iconset("aaa-plugin"))),
    threading.Thread(target=installiere, args=("b", iconset("bbb-plugin"))),
]
for t in threads:
    t.start()
for t in threads:
    t.join()
installer._ordner_fuer = original

check("beide melden Erfolg", ergebnis == {"a": "aaa-plugin", "b": "bbb-plugin"}, str(ergebnis))
platte = bestand_auf_platte()
check("beide liegen auf der Platte, je in einem eigenen Ordner",
      sorted(platte.values()) == ["aaa-plugin", "bbb-plugin"] and len(platte) == 2, str(platte))

print("\nEntfernen während einer Installation")
installer._ordner_fuer = langsam
t = threading.Thread(target=installiere, args=("c", iconset("ccc-plugin")))
t.start()
time.sleep(0.1)
installer.uninstall("aaa-plugin")
t.join()
installer._ordner_fuer = original
platte = bestand_auf_platte()
check("das neue ist da, das entfernte weg, das dritte unberührt",
      sorted(platte.values()) == ["bbb-plugin", "ccc-plugin"], str(platte))

# ==========================================================================
print("\nKaputte Manifeste beim Laden")
wurzel = Path(tempfile.mkdtemp(dir=paths.DATA_DIR))
(wurzel / "kaputt").mkdir()
(wurzel / "kaputt" / "manifest.json").write_bytes(
    b'{"id":"b\xe4d","name":"x","version":"1.0.0","type":"iconset"}'
)
(wurzel / "liste").mkdir()
(wurzel / "liste" / "manifest.json").write_text("[1, 2]")
(wurzel / "gut" / "icons").mkdir(parents=True)
(wurzel / "gut" / "manifest.json").write_text(
    json.dumps({"id": "gut", "name": "g", "version": "1.2.3", "type": "iconset"})
)

registry = PluginRegistry()
try:
    registry.discover(lambda _d: None, search_paths=[(wurzel, False)])
    abgestuerzt = None
except Exception as exc:
    abgestuerzt = exc
check("discover läuft durch", abgestuerzt is None, repr(abgestuerzt))
check("das gute Plugin ist geladen", "gut" in registry.plugins, str(list(registry.plugins)))
fehler = {e.plugin_id for e in registry.errors}
check("beide kaputten stehen als Fehler da", {"kaputt", "liste"} <= fehler, str(fehler))

try:
    bestand = registry.bestand(search_paths=[(wurzel, False)])
    abgestuerzt = None
except Exception as exc:
    bestand, abgestuerzt = {}, exc
check("bestand läuft durch", abgestuerzt is None, repr(abgestuerzt))
check("und kennt das gute", bestand.get("gut", (None, ""))[1] == "1.2.3", str(bestand))

print("\nKaputte Manifeste beim Installieren")
for name, roh in (
    ("kein UTF-8", b'{"id":"b\xe4d","name":"x","version":"1.0.0","type":"iconset"}'),
    ("eine Liste", b"[1, 2]"),
):
    try:
        installer.install_archive(archiv(roh))
        art = None
    except installer.InstallError:
        art = "InstallError"
    except Exception as exc:
        art = repr(exc)
    check(f"{name} ergibt einen InstallError", art == "InstallError", str(art))

print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("Alle Prüfungen bestanden.")
