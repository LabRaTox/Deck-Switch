"""Zwei Plugins, zwei gleichnamige Hilfsdateien, kein Ärger.

Diese Suite gibt es wegen eines Fehlers, der schwer zu lesen war: Das
Twitch-Plugin brachte eine ``api.py`` mit, das Wetter-Plugin auch. Alle
Plugins teilten sich einen Modulraum, also gewann die zuerst geladene
Datei — und Twitch scheiterte an einem Namen, den es in seiner eigenen
Datei sehr wohl gab. Die Meldung zeigte dabei auf den Ordner des anderen
Plugins.

Seitdem wird jedes Plugin als **Paket** geladen. Wer seine Nachbardatei
relativ importiert (``from .api import …``), bekommt garantiert die aus dem
eigenen Ordner. Genau das wird hier nachgestellt: zwei Plugins, beide mit
einer ``api.py``, beide mit demselben Funktionsnamen darin, aber
unterschiedlichem Ergebnis.

Der alte Weg (``from api import …``) läuft weiterhin — fremde Plugins
sollen nicht brechen. Dass er weiterhin läuft, steht ebenfalls hier drin.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/plugin_pakete_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from deckswitch.config import default_config  # noqa: E402
from deckswitch.plugins.base import Services  # noqa: E402
from deckswitch.plugins.loader import PluginRegistry  # noqa: E402

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


MANIFEST = {
    "id": "", "name": {"de": ""}, "version": "1.0.0", "type": "action",
    "entry": "plugin.py", "class": "PruefPlugin",
    "actions": [{"id": "tu", "name": {"de": "Tu"}, "inputs": ["key"]}],
}

#: Beide Plugins bringen eine ``api.py`` mit derselben Funktion mit — nur
#: das Ergebnis unterscheidet sich. Genau daran fällt auf, wer wen bekommt.
API = 'def wer():\n    return "{wer}"\n'

RELATIV = '''from deckswitch.plugins.base import ActionPlugin

from .api import wer


class PruefPlugin(ActionPlugin):
    herkunft = wer()
'''

ABSOLUT = '''from deckswitch.plugins.base import ActionPlugin

from api import wer


class PruefPlugin(ActionPlugin):
    herkunft = wer()
'''


def baue(wurzel: pathlib.Path, kennung: str, quelltext: str) -> pathlib.Path:
    ordner = wurzel / kennung
    ordner.mkdir(parents=True)
    manifest = dict(MANIFEST, id=kennung, name={"de": kennung})
    (ordner / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (ordner / "plugin.py").write_text(quelltext, encoding="utf-8")
    (ordner / "api.py").write_text(API.format(wer=kennung), encoding="utf-8")
    return ordner


def dienste(ordner=None):
    return Services(audio=None, icons=None, render=None, runtime=None,
                    config=default_config(), plugin_dir=ordner or pathlib.Path("."))


def lade(wurzel: pathlib.Path) -> PluginRegistry:
    """Wie die App: alles unter ``wurzel`` einsammeln und laden."""
    registry = PluginRegistry()
    registry.discover(dienste, search_paths=[(wurzel, False)])
    return registry


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pakete-") as tmp:
        wurzel = pathlib.Path(tmp)

        print("== Zwei Plugins mit gleichnamiger Hilfsdatei ==")
        eins = baue(wurzel, "pruef-eins", RELATIV)
        zwei = baue(wurzel, "pruef-zwei", RELATIV)

        registry = lade(wurzel)

        check("beide sind geladen",
              sorted(registry.plugins) == ["pruef-eins", "pruef-zwei"],
              json.dumps(sorted(registry.plugins)))
        check("und keines meldet einen Fehler", not registry.errors,
              json.dumps([f"{e.plugin_id}: {e.message[:80]}" for e in registry.errors]))

        a = registry.instance("pruef-eins")
        b = registry.instance("pruef-zwei")
        check("das erste bekam seine eigene api.py",
              a is not None and a.herkunft == "pruef-eins",
              getattr(a, "herkunft", "—"))
        check("das zweite auch seine eigene",
              b is not None and b.herkunft == "pruef-zwei",
              getattr(b, "herkunft", "—"))

        print("\n== Der alte Weg bleibt offen ==")
        # Fremde Plugins importieren ihre Nachbarn womöglich beim kurzen
        # Namen. Das darf nicht brechen — nur eindeutig muss der Name dann
        # sein, und dabei hilft die Meldung des Loaders.
        alt = baue(wurzel / "alt", "pruef-alt", ABSOLUT)
        registry2 = lade(alt.parent)
        check("ein Plugin mit absolutem Import lädt weiterhin",
              registry2.instance("pruef-alt") is not None,
              json.dumps([f"{e.plugin_id}: {e.message[:100]}" for e in registry2.errors]))
        c = registry2.instance("pruef-alt")
        check("und bekommt seine eigene Datei",
              c is not None and c.herkunft == "pruef-alt",
              getattr(c, "herkunft", "—"))

        print("\n== Und die echten Plugins des Projekts ==")
        quellen = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources"
        registry3 = lade(quellen)
        mit_nachbarn = [
            ordner.name for ordner in sorted(quellen.iterdir())
            if ordner.is_dir()
            and any(p.stem not in ("plugin", "screenshots") for p in ordner.glob("*.py"))
        ]
        check("die mit Hilfsdateien laden alle",
              all(name in registry3.plugins for name in mit_nachbarn),
              f"{mit_nachbarn} → {sorted(registry3.plugins)}")
        check("ohne einen einzigen Ladefehler", not registry3.errors,
              json.dumps([f"{e.plugin_id}: {e.message[:80]}" for e in registry3.errors]))

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
