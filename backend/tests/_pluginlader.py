"""Lädt ein Plugin so, wie die App es lädt — als Paket.

Ein ``import plugin`` reicht dafür nicht mehr: Seit die Plugins ihre
Nachbardateien relativ importieren (``from .api import …``), brauchen sie
einen Paketkontext. Den stellt diese Datei her, mit demselben Kniff wie
:mod:`deckswitch.plugins.loader` — ``submodule_search_locations``.

Der Gewinn steht in :func:`deckswitch.plugins.loader._kollision`: Zwei
Plugins dürfen ihre Hilfsdateien gleich benennen, ohne sich in die Quere zu
kommen. Wenn die Prüfsuiten anders laden als die App, prüfen sie am Ende
etwas anderes, als läuft — deshalb hier derselbe Weg.

    from _pluginlader import lade, nachbar

    modul = lade(PLUGIN_DIR)                 # plugin.py als Paket
    api = nachbar(modul, "twitch_api")       # eine Nachbardatei daraus
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def lade(ordner: Path, *, name: str | None = None) -> ModuleType:
    """Die ``plugin.py`` aus ``ordner``, geladen als Paket."""
    ordner = Path(ordner).resolve()
    paket = name or f"pruef_plugin_{ordner.name.replace('-', '_')}"
    eintrag = ordner / "plugin.py"
    if not eintrag.is_file():
        raise FileNotFoundError(f"Keine plugin.py in {ordner}")

    spec = importlib.util.spec_from_file_location(
        paket, eintrag, submodule_search_locations=[str(ordner)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Kann {eintrag} nicht laden")
    modul = importlib.util.module_from_spec(spec)
    # Vor dem Ausführen eintragen: Die relativen Importe darin suchen ihr
    # Paket über sys.modules.
    sys.modules[paket] = modul
    spec.loader.exec_module(modul)
    return modul


def nachbar(modul: ModuleType, name: str) -> ModuleType:
    """Eine Nachbardatei desselben Plugins — etwa zum Umbiegen einer URL."""
    return importlib.import_module(f"{modul.__name__}.{name}")
