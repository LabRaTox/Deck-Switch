"""Nach neuen Plugins sehen, ohne die laufenden abzuwürgen.

Diese Suite gibt es wegen eines Knopfes, den niemand mehr anfassen wollte:
„Plugins neu laden" riss jedes Plugin ab und baute es neu auf. Verbindungen
fielen, gemerkte Zustände waren weg, Timer standen wieder auf Anfang — und
das alles nur, weil jemand nachsehen wollte, ob es etwas Neues im Store
gibt.

Geprüft wird deshalb die Regel, die das verhindert: **Angefasst wird nur,
was sich auf der Platte geändert hat.** Ein Plugin, das unverändert
dasteht, behält seine Instanz — mitsamt allem, was darin lebt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/plugin_sync_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from deckswitch import paths  # noqa: E402
from deckswitch.runtime import Runtime  # noqa: E402

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


PLUGIN = '''
from deckswitch.plugins.base import ActionPlugin


class Probe(ActionPlugin):
    """Merkt sich, wie oft es hochgefahren wurde — und was es gesammelt hat."""

    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.hochgefahren = 0
        self.gemerkt = []

    async def setup(self):
        self.hochgefahren += 1

    async def teardown(self):
        self.gemerkt.append("abgebaut")
'''


def lege_an(name: str, version: str = "1.0.0") -> pathlib.Path:
    ordner = paths.USER_PLUGINS_DIR / name
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "manifest.json").write_text(json.dumps({
        "id": name, "name": name, "version": version, "type": "action",
        "entry": "plugin.py", "class": "Probe",
        "actions": [{"id": "tu", "name": "Tu was"}],
    }), encoding="utf-8")
    (ordner / "plugin.py").write_text(PLUGIN, encoding="utf-8")
    return ordner


async def main() -> int:
    runtime = Runtime()
    lege_an("probe-eins")
    lege_an("probe-zwei")
    runtime.load_plugins()
    await runtime._setup_plugins()

    eins = runtime.registry.instance("probe-eins")
    zwei = runtime.registry.instance("probe-zwei")
    check("beide Prüf-Plugins laufen", eins is not None and zwei is not None)
    eins.gemerkt.append("etwas, das nicht verloren gehen darf")

    print("\n== Nachsehen, wenn sich nichts geändert hat ==")
    ergebnis = await runtime.sync_plugins()
    check("es gibt nichts zu tun", ergebnis == {"neu": [], "weg": [], "geaendert": []},
          json.dumps(ergebnis))
    check("dasselbe Plugin läuft weiter — dieselbe Instanz",
          runtime.registry.instance("probe-eins") is eins)
    check("und hat behalten, was es sich gemerkt hatte",
          "etwas, das nicht verloren gehen darf" in eins.gemerkt, str(eins.gemerkt))
    check("es wurde auch nicht abgebaut", "abgebaut" not in eins.gemerkt, str(eins.gemerkt))
    check("und nicht ein zweites Mal hochgefahren", eins.hochgefahren == 1,
          str(eins.hochgefahren))

    print("\n== Ein neues Plugin kommt dazu ==")
    lege_an("probe-drei")
    ergebnis = await runtime.sync_plugins()
    check("es wird gefunden", ergebnis["neu"] == ["probe-drei"], json.dumps(ergebnis))
    drei = runtime.registry.instance("probe-drei")
    check("und hochgefahren", drei is not None and drei.hochgefahren == 1,
          str(drei.hochgefahren if drei else None))
    check("die anderen bleiben dieselben",
          runtime.registry.instance("probe-eins") is eins
          and runtime.registry.instance("probe-zwei") is zwei)
    check("und behalten ihren Zustand",
          "etwas, das nicht verloren gehen darf" in eins.gemerkt)

    print("\n== Eine neue Fassung wird eingespielt ==")
    lege_an("probe-zwei", version="2.0.0")
    ergebnis = await runtime.sync_plugins()
    check("die Änderung wird bemerkt", ergebnis["geaendert"] == ["probe-zwei"],
          json.dumps(ergebnis))
    check("die alte Instanz wurde ordentlich abgebaut", "abgebaut" in zwei.gemerkt,
          str(zwei.gemerkt))
    neu_zwei = runtime.registry.instance("probe-zwei")
    check("es läuft jetzt eine neue", neu_zwei is not zwei)
    check("mit der neuen Fassung",
          runtime.registry.get("probe-zwei").manifest.version == "2.0.0",
          runtime.registry.get("probe-zwei").manifest.version)
    check("und die unbeteiligten bleiben unberührt",
          runtime.registry.instance("probe-eins") is eins
          and eins.hochgefahren == 1, str(eins.hochgefahren))

    print("\n== Ein Plugin verschwindet ==")
    shutil.rmtree(paths.USER_PLUGINS_DIR / "probe-drei")
    ergebnis = await runtime.sync_plugins()
    check("das wird bemerkt", ergebnis["weg"] == ["probe-drei"], json.dumps(ergebnis))
    check("es ist aus der Liste", runtime.registry.get("probe-drei") is None)
    check("und wurde vorher abgebaut", "abgebaut" in drei.gemerkt, str(drei.gemerkt))
    check("die übrigen laufen unverändert weiter",
          runtime.registry.instance("probe-eins") is eins and eins.hochgefahren == 1)

    print("\n== Der harte Weg bleibt hart ==")
    await runtime.reload_plugins()
    check("dabei wird alles neu aufgebaut",
          runtime.registry.instance("probe-eins") is not eins)
    check("und das alte ordentlich abgebaut", "abgebaut" in eins.gemerkt, str(eins.gemerkt))

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(asyncio.run(main()))
