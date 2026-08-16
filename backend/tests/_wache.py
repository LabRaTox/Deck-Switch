"""Verhindert, dass eine Testsuite in die echte Konfiguration schreibt.

Die Suiten legen Decks, Profile und Seiten an — das ist ihr Zweck. Ohne
gesetztes ``XDG_CONFIG_HOME`` landet all das aber in
``~/.config/deckswitch/config.json``, und die Belegung, die dort stand, ist
weg. Am 2026-08-16 ist genau das passiert.

Jede Suite importiert diese Wache als erstes. Sie bricht ab, statt zu
schreiben — ein abgebrochener Testlauf kostet Sekunden, eine verlorene
Belegung kostet Stunden.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def sichere_umgebung() -> None:
    from deckswitch import paths

    echt = Path.home() / ".config" / "deckswitch"
    ziel = paths.CONFIG_DIR.resolve()

    if ziel == echt.resolve() or not os.environ.get("XDG_CONFIG_HOME"):
        sys.exit(
            "ABBRUCH: Diese Suite würde in die echte Konfiguration schreiben\n"
            f"  Ziel wäre: {ziel}\n\n"
            "So starten (je Suite ein eigenes, frisches Verzeichnis — sonst\n"
            "sieht die nächste Suite die Seiten der vorigen):\n"
            "  d=$(mktemp -d)\n"
            f"  env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d python {sys.argv[0]}\n"
        )

