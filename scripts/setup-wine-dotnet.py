#!/usr/bin/env python3
"""Legt die .NET-Laufzeit in die Windows-Umgebung von DECK//SWITCH.

Die meisten Elgato-Plugins für Windows sind in .NET geschrieben und bringen
die Laufzeit **nicht** mit. Ohne sie startet das Plugin nicht, sondern
schreibt „You must install .NET to run this application" — die Plugin-Karte
zeigt diese Zeile dann an.

    ./scripts/setup-wine-dotnet.py            neueste Fassung holen
    ./scripts/setup-wine-dotnet.py --version 9.0
    ./scripts/setup-wine-dotnet.py --pruefen  nur nachsehen, was da ist

**Warum das ein Skript ist und kein Knopf in der App.** Es lädt rund 80 MB
bei Microsoft — das ist nichts, was eine Anwendung ungefragt tun sollte, und
es ist einmalige Einrichtung, keine Bedienung. Wer es lieber von Hand macht:
Die beiden ZIPs (Runtime und Desktop Runtime, ``win-x64``) gehören
ausgepackt nach ``<Umgebung>/drive_c/Program Files/dotnet``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

INDEX = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json"

#: Dieselbe Stelle, an der die App sie sucht — siehe
#: ``deckswitch.plugins.elgato.wine_prefix``.
def prefix() -> Path:
    basis = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(basis) / "deckswitch" / "wine"


def hole(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as antwort:
        return antwort.read()


def kanal(version: str) -> dict:
    """Der Eintrag zu einer .NET-Reihe — ``""`` nimmt die aktuell gepflegte."""
    index = json.loads(hole(INDEX))["releases-index"]
    if version:
        eintrag = next((k for k in index if k["channel-version"] == version), None)
        if eintrag is None:
            raise SystemExit(f".NET {version} gibt es in der Liste nicht")
        return eintrag
    # ``active`` ist die Reihe, die Microsoft gerade empfiehlt; Vorschauen
    # stehen weiter oben und wären eine schlechte Vorgabe.
    eintrag = next((k for k in index if k.get("support-phase") == "active"), None)
    return eintrag or index[0]


def pakete(kanal_eintrag: dict) -> list[tuple[str, str]]:
    """Runtime und Desktop Runtime als ``(Name, URL)`` für win-x64.

    Beide werden gebraucht: Die Basis reicht für ein Konsolenprogramm, aber
    ein Plugin mit WPF-Oberfläche verlangt ``Microsoft.WindowsDesktop.App``.
    """
    freigabe = json.loads(hole(kanal_eintrag["releases.json"]))["releases"][0]
    gefunden = []
    for schluessel in ("runtime", "windowsdesktop"):
        block = freigabe.get(schluessel) or {}
        datei = next(
            (d for d in block.get("files", []) if d["name"].endswith("win-x64.zip")),
            None,
        )
        if datei is None:
            raise SystemExit(f"Für '{schluessel}' gibt es kein win-x64.zip")
        gefunden.append((schluessel, datei["url"]))
    return gefunden


def bereits_da(ziel: Path) -> list[str]:
    geteilt = ziel / "shared"
    if not geteilt.is_dir():
        return []
    return sorted(
        f"{ordner.name} {fassung.name}"
        for ordner in geteilt.iterdir() if ordner.is_dir()
        for fassung in ordner.iterdir() if fassung.is_dir()
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="z. B. 9.0; leer = aktuelle Reihe")
    parser.add_argument("--pruefen", action="store_true", help="nur nachsehen, nichts laden")
    args = parser.parse_args(argv[1:])

    ziel = prefix() / "drive_c" / "Program Files" / "dotnet"
    print(f"Windows-Umgebung: {prefix()}")

    vorhanden = bereits_da(ziel)
    if vorhanden:
        print("Schon vorhanden:")
        for eintrag in vorhanden:
            print(f"  {eintrag}")
    else:
        print("Bisher keine .NET-Laufzeit darin.")
    if args.pruefen:
        return 0

    eintrag = kanal(args.version)
    print(f"\n.NET {eintrag['channel-version']} ({eintrag.get('support-phase')}) "
          f"— Laufzeit {eintrag.get('latest-runtime')}")

    ziel.mkdir(parents=True, exist_ok=True)
    for name, url in pakete(eintrag):
        print(f"  {name}: {url.rsplit('/', 1)[-1]} … ", end="", flush=True)
        daten = hole(url)
        with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
            archiv.extractall(ziel)
        print(f"{len(daten) // (1024 * 1024)} MB ausgepackt")

    print("\nFertig. Jetzt vorhanden:")
    for zeile in bereits_da(ziel):
        print(f"  {zeile}")
    print("\nDanach das Backend neu starten:")
    print("  systemctl --user restart deckswitch.service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
