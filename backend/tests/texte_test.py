"""Prüft die Übersetzung der Texte, die das Backend an die Oberfläche schickt.

Geprüft wird der Mechanismus (Sprache, Ersatzsprache, Code, Neuerzeugung,
Plugin-Texte), die Antwort des Servers mit Code und die Vollständigkeit:
Jeder Schlüssel, den der Kern benutzt, steht in beiden Sprachdateien, mit
denselben Platzhaltern.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/texte_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import json
import pathlib
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from deckswitch import texte  # noqa: E402
from deckswitch.config import default_config  # noqa: E402
from deckswitch.plugins.base import ActionPlugin, Manifest, Services  # noqa: E402
from deckswitch.services.desktop import DesktopError  # noqa: E402

FAILS = []
KERN = pathlib.Path(__file__).resolve().parents[1] / "deckswitch"


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def sprache_auf(code):
    texte.verbinde_sprache(lambda: code)


def pruefe_mechanismus():
    print("== t() ==")
    sprache_auf("de")
    deutsch = texte.t("desktop.nicht_installiert", programm="spectacle")
    check("Deutsch als Vorgabe", deutsch == "'spectacle' ist nicht installiert", deutsch)
    check("der Text kennt seinen Schlüssel", deutsch.code == "desktop.nicht_installiert")
    check("und seine Werte", deutsch.werte == {"programm": "spectacle"})
    sprache_auf("en")
    englisch = texte.t("desktop.nicht_installiert", programm="spectacle")
    check("Englisch nach Umschalten", englisch == "'spectacle' is not installed", englisch)
    sprache_auf("fr")
    check("unbekannte Sprache fällt auf Deutsch", texte.sprache() == "de")
    sprache_auf("de")
    check("fehlender Schlüssel kommt als Schlüssel zurück", texte.t("gibt.es.nicht") == "gibt.es.nicht")
    check("fehlender Platzhalter bricht nicht ab",
          texte.t("desktop.nicht_installiert") == "'{programm}' ist nicht installiert")

    print("\n== aktuell() ==")
    gespeichert = texte.t("session.ddcutil_nicht_installiert")
    sprache_auf("en")
    check("ein gespeicherter Text folgt dem Sprachwechsel",
          texte.aktuell(gespeichert) == "'ddcutil' is not installed", texte.aktuell(gespeichert))
    check("gewöhnliche Zeichenketten bleiben, wie sie sind", texte.aktuell("roh") == "roh")
    check("None bleibt None", texte.aktuell(None) is None)
    sprache_auf("de")

    print("\n== Code im Fehler ==")
    try:
        try:
            raise DesktopError(texte.t("desktop.kein_programm_angegeben"))
        except DesktopError as innen:
            raise RuntimeError(str(innen)) from innen
    except RuntimeError as aussen:
        check("der Code findet sich auch in der Ursache",
              texte.code_von(aussen) == "desktop.kein_programm_angegeben", texte.code_von(aussen))
    check("ohne Text kein Code", texte.code_von(ValueError("roh")) is None)


def pruefe_plugin():
    print("\n== self.t() im Plugin ==")
    with tempfile.TemporaryDirectory() as tmp:
        ordner = pathlib.Path(tmp)
        (ordner / "locales").mkdir()
        (ordner / "locales" / "de.json").write_text(json.dumps({"gruss": "Hallo {name}", "nur_de": "nur deutsch"}))
        (ordner / "locales" / "en.json").write_text(json.dumps({"gruss": "Hello {name}"}))
        manifest = Manifest(id="pruef-plugin", name="Prüf")
        dienste = Services(audio=None, icons=None, render=None, runtime=None,
                           config=default_config(), plugin_dir=ordner)
        plugin = ActionPlugin(manifest, dienste)
        sprache_auf("de")
        check("Deutsch", plugin.t("gruss", name="Heiko") == "Hallo Heiko")
        sprache_auf("en")
        check("Englisch", plugin.t("gruss", name="Heiko") == "Hello Heiko")
        check("fehlt Englisch, kommt Deutsch", plugin.t("nur_de") == "nur deutsch")
        check("Code mit Plugin-ID davor", plugin.t("gruss", name="x").code == "pruef-plugin.gruss")
        check("aktuell() lässt Plugin-Texte in Ruhe", texte.aktuell(plugin.t("gruss", name="x")) == "Hello x")
        sprache_auf("de")


def pruefe_vollstaendigkeit():
    print("\n== Vollständigkeit ==")
    de = json.loads((KERN / "locales" / "de.json").read_text())
    en = json.loads((KERN / "locales" / "en.json").read_text())
    check("beide Sprachen haben dieselben Schlüssel", set(de) == set(en), str(set(de) ^ set(en)))
    platz = [k for k in de if set(re.findall(r"\{(\w+)", de[k])) != set(re.findall(r"\{(\w+)", en.get(k, "")))]
    check("Platzhalter stimmen überein", not platz, str(platz))
    benutzt = set()
    for datei in KERN.rglob("*.py"):
        benutzt |= set(re.findall(r'texte\.t\(\s*"([^"]+)"', datei.read_text()))
        benutzt |= set(re.findall(r'"(desktop\.fenster\.[a-z_]+)"', datei.read_text()))
    fehlt = sorted(benutzt - set(de))
    check("jeder benutzte Schlüssel steht im Katalog", not fehlt, str(fehlt))
    unbenutzt = sorted(set(de) - benutzt)
    check("kein Schlüssel ohne Verwendung", not unbenutzt, str(unbenutzt))
    check("kein Gedankenstrich in den Texten", not any("—" in v for v in [*de.values(), *en.values()]))


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pruefe_server():
    print("\n== Fehlerantwort mit Code ==")
    from deckswitch.runtime import Runtime
    from deckswitch.server import create_app

    runtime = Runtime()
    app = create_app(runtime)
    port = freier_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

    def hole(pfad):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{pfad}", timeout=10) as antwort:
                return antwort.status, json.loads(antwort.read())
        except urllib.error.HTTPError as fehler:
            return fehler.code, json.loads(fehler.read())

    try:
        runtime.config.app.language = "de"
        status, inhalt = hole("/api/decks/gibt-es-nicht/tiles")
        check("404 mit deutschem Text", status == 404 and inhalt.get("detail") == "Deck nicht gefunden", str(inhalt))
        check("und mit Code", inhalt.get("code") == "server.deck_nicht_gefunden", str(inhalt))
        runtime.config.app.language = "en"
        status, inhalt = hole("/api/decks/gibt-es-nicht/tiles")
        check("nach Umschalten auf Englisch englisch", inhalt.get("detail") == "Deck not found", str(inhalt))
        status, inhalt = hole("/api/gibt-es-gar-nicht")
        check("fremde Fehler ohne Code bleiben wie bisher", status == 404 and "code" not in inhalt, str(inhalt))
    finally:
        server.should_exit = True
        sprache_auf("de")


def main() -> int:
    pruefe_mechanismus()
    pruefe_plugin()
    pruefe_vollstaendigkeit()
    pruefe_server()
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
