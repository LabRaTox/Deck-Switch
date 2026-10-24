"""Prüft die Ordnernummern beim Installieren und Entfernen."""
import _wache
_wache.sichere_umgebung()

import io, json, sys, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch import paths
from deckswitch.plugins import installer

FAILS = []
def check(name, ok, detail=""):
    print(f"  {'✔' if ok else '✘'} {name}" + (f"  ({detail})" if detail else ""))
    if not ok: FAILS.append(name)

def archiv(pid, version="1.0.0"):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr(f"{pid}/manifest.json", json.dumps({
            "id": pid, "name": pid, "version": version, "type": "action",
            "entry": "plugin.py", "class": "P"}))
        z.writestr(f"{pid}/plugin.py", "class P:\n    pass\n")
    return puffer.getvalue()

def ordner():
    return sorted(p.name for p in paths.USER_PLUGINS_DIR.iterdir() if p.is_dir())

print("Installieren")
installer.install_archive(archiv("wetter"))
check("der erste Ordner heißt 0001", ordner() == ["0001"], ", ".join(ordner()))

installer.install_archive(archiv("lampen"))
check("der zweite 0002", ordner() == ["0001", "0002"], ", ".join(ordner()))

print("\nEine neue Fassung ersetzt an Ort und Stelle")
installer.install_archive(archiv("wetter", "2.0.0"))
check("kein dritter Ordner", ordner() == ["0001", "0002"], ", ".join(ordner()))
m = json.loads((paths.USER_PLUGINS_DIR / "0001" / "manifest.json").read_text())
check("aber die neue Fassung darin", m["version"] == "2.0.0", m["version"])

print("\nEin Archiv bestimmt den Ordnernamen nicht mehr")
# Früher hätte dieses Manifest den Ordner „../../boese" heißen lassen können.
check("die Kennung steht nur im Manifest",
      not (paths.USER_PLUGINS_DIR / "wetter").exists())

print("\nEntfernen findet über das Manifest")
installer.uninstall("wetter")
check("0001 ist weg", ordner() == ["0002"], ", ".join(ordner()))
check("lampen steht noch",
      json.loads((paths.USER_PLUGINS_DIR / "0002" / "manifest.json").read_text())["id"] == "lampen")

print("\nAlte Ordner aus früheren Fassungen")
alt = paths.USER_PLUGINS_DIR / "altmodisch"
alt.mkdir()
(alt / "manifest.json").write_text(json.dumps({
    "id": "altmodisch", "name": "Alt", "version": "1.0.0", "type": "action",
    "entry": "plugin.py", "class": "P"}))
(alt / "plugin.py").write_text("class P:\n    pass\n")
installer.uninstall("altmodisch")
check("werden trotzdem gefunden und entfernt", not alt.exists())

print("\nArchive, die je nach Leser anders aussehen")
def abgelehnt(daten, **kw):
    try:
        installer.install_archive(daten, **kw)
    except installer.InstallError:
        return True
    return False

puffer = io.BytesIO()
with zipfile.ZipFile(puffer, "w") as z:
    for pid in ("harmlos", "boese"):
        z.writestr(f"{pid}/manifest.json", json.dumps({
            "id": pid, "name": pid, "version": "1.0.0", "type": "action",
            "entry": "plugin.py", "class": "P"}))
        z.writestr(f"{pid}/plugin.py", "class P:\n    pass\n")
check("zwei Plugin-Ordner werden abgelehnt", abgelehnt(puffer.getvalue()))

puffer = io.BytesIO()
with zipfile.ZipFile(puffer, "w") as z:
    z.writestr("x/manifest.json", json.dumps({
        "id": "x", "name": "x", "version": "1.0.0", "type": "action",
        "entry": "plugin.py", "class": "P"}))
    z.writestr("x\\plugin.py", "class P:\n    pass\n")
check("ein Backslash im Namen wird abgelehnt", abgelehnt(puffer.getvalue()))

check("eine fremde ID wird abgelehnt", abgelehnt(archiv("lampen", "3.0.0"), expected_id="wetter"))
m = json.loads((paths.USER_PLUGINS_DIR / "0002" / "manifest.json").read_text())
check("und das andere Plugin bleibt unberührt", m["version"] == "1.0.0", m["version"])
check("die passende ID geht durch", not abgelehnt(archiv("wetter", "3.0.0"), expected_id="wetter"))

print()
if FAILS:
    print("FEHLGESCHLAGEN: " + ", ".join(FAILS)); sys.exit(1)
print("Alle Prüfungen bestanden.")
