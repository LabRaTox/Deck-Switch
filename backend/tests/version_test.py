"""Alle Versionsangaben im Projekt müssen dieselbe sein.

Die Version steht in ``deckswitch/__init__.py``. ``pyproject.toml`` liest
sie von dort, Rust und npm können das nicht — dort steht die Zahl noch
einmal. Genau dieses Wiederholen ist der Grund für diese Suite: Vor dem
2026-08-19 standen fünf Stellen auf drei verschiedenen Werten, ohne dass es
jemandem auffiel.

Aufruf (braucht keine Konfiguration, schreibt nichts):

    cd backend
    ../.venv/bin/python tests/version_test.py
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch import __version__  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
FAILS = []

#: Semver, wie ihn sowohl Cargo als auch npm und die Plugin-Manifeste
#: erwarten. Ein „1.0" wäre für Cargo in Ordnung und für npm nicht.
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def main() -> None:
    print(f"\nQuelle: deckswitch/__init__.py → {__version__}")
    check("die Version ist ein vollständiger Semver", bool(SEMVER.match(__version__)),
          __version__)

    pyproject = tomllib.loads((WURZEL / "backend" / "pyproject.toml").read_text())
    # Steht dort eine feste Zahl, ist die dynamische Ableitung kaputt oder
    # jemand hat sie zurückgedreht — beides muss auffallen.
    check("pyproject.toml holt die Version dynamisch",
          "version" in pyproject["project"].get("dynamic", []),
          str(pyproject["project"].get("version", "— kein festes Feld")))

    cargo = tomllib.loads((WURZEL / "gui" / "src-tauri" / "Cargo.toml").read_text())
    check("Cargo.toml stimmt überein", cargo["package"]["version"] == __version__,
          cargo["package"]["version"])

    paket = json.loads((WURZEL / "gui" / "package.json").read_text())
    check("package.json stimmt überein", paket["version"] == __version__,
          paket["version"])

    tauri = json.loads((WURZEL / "gui" / "src-tauri" / "tauri.conf.json").read_text())
    # Ohne eigenes Feld nimmt Tauri die Zahl aus der Cargo.toml — genau so
    # ist es gewollt, eine Stelle weniger zum Pflegen.
    check("tauri.conf.json hat keine eigene Version",
          "version" not in tauri,
          tauri.get("version", "— kein Feld"))

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


main()
