"""Installierte Programme auflisten, für die Auswahl in der Profil-Automatik.

Die Automatik vergleicht die Fensterklasse des vorderen Programms mit den
Einträgen im Profil (siehe :mod:`deckswitch.services.smartprofile`). Bislang
mussten diese Namen von Hand getippt werden; die Auswahl soll künftig aus
einer Liste kommen.

„Installierte Programme“ aufzulisten ist keine Distributionsfrage: Der
Free-Desktop-Standard legt fest, dass Menüeinträge als ``.desktop``-Dateien
in den Datenverzeichnissen liegen. Ob Arch sie per pacman, Debian per apt
oder Fedora per dnf dorthin gebracht hat, ist dabei egal — gelesen wird
immer dieselbe Struktur. Fehlt auf einem ungewöhnlichen System der Ordner,
ist die Liste eben leer, und die manuelle Eingabe bleibt.

Aus jeder Datei werden nur der Anzeigename und der Name geholt, unter dem
das Fenster des Programms erscheint. Das ist nicht immer der Befehl aus
``Exec=``: Steam-Spiele starten alle über ``steam``, ihr Fenster heißt aber
``steam_app_<id>``; ein Flatpak startet über ``flatpak run``. Deshalb gilt
zuerst ``StartupWMClass``, das genau für diesen Zweck im Standard steht,
und erst danach der Befehl. Einträge, deren Programm sich nicht bestimmen
lässt (``sh -c "…"``), fallen weg — ein ``sh`` in der Liste träfe als
Teilzeichenkette fast jedes Fenster.

``NoDisplay``- und ``Hidden``-Einträge erscheinen in keinem Menü und werden
auch hier nicht gezeigt.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

#: Vorsatz-Befehle in ``Exec=``-Zeilen, hinter denen das eigentliche
#: Programm steht. Ohne sie hieße der Eintrag „env“, und die Fensterklasse
#: eines mit ``env`` gestarteten Programms heißt trotzdem nicht ``env``.
_VORSAETZE = ("env", "sudo", "pkexec", "qtchooser", "xdg-open", "gio")

#: Shells. Hinter ihnen steht ein Skript oder mit ``-c`` eine Zeichenkette;
#: das Fenster heißt nach keinem von beiden — solche Einträge fallen weg.
_SHELLS = ("sh", "bash", "dash", "zsh", "fish")

#: Optionen der Vorsätze, die ihr Argument getrennt mitnehmen
#: (``env -u NAME``, ``sudo -u benutzer``).
_MIT_ARGUMENT = ("-u", "--unset", "-C", "--chdir", "-g", "--group")

_STEAM_SPIEL = re.compile(r"steam://rungameid/(\d+)")


#: Wo die Menüeinträge liegen, in der Reihenfolge, die der Standard vorgibt:
#: Das Benutzerverzeichnis darf das System überschreiben, nicht umgekehrt.
def _verzeichnisse() -> list[Path]:
    daten = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    such = [daten] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return [Path(teil.strip()) / "applications" for teil in such if teil.strip()]


def _programm(zeile: str) -> str:
    """Der Name, unter dem das Fenster aus einer ``Exec=``-Zeile erscheint.

    Zerlegt wird wie in der Shell; der Standard lehnt sein Quoting daran an.
    Vorsätze wie ``env`` samt ihren Optionen und ``VAR=wert`` werden
    übersprungen, vom Programm bleibt der Name ohne Pfad. Steam-Spiele und
    Flatpaks bekommen den Namen, den ihr Fenster tatsächlich trägt. Leer
    heißt: nicht zu bestimmen.
    """
    spiel = _STEAM_SPIEL.search(zeile)
    if spiel:
        return f"steam_app_{spiel.group(1)}"
    try:
        teile = shlex.split(zeile)
    except ValueError:
        teile = zeile.split()

    im_vorsatz = False
    ueberspringen = False
    for nummer, teil in enumerate(teile):
        if "%" in teil:
            break
        if ueberspringen:
            ueberspringen = False
            continue
        name = Path(teil).name
        if "=" in teil or (im_vorsatz and teil.startswith("-")):
            ueberspringen = im_vorsatz and teil in _MIT_ARGUMENT
            continue
        if name in _VORSAETZE:
            im_vorsatz = True
            continue
        if name in _SHELLS:
            return ""
        if name == "flatpak":
            # flatpak run [Optionen] <App-ID> — die App-ID ist auch der Name
            # des Fensters, unter Wayland wie unter X11.
            rest = [t for t in teile[nummer + 1:] if t != "run" and not t.startswith("-")]
            return rest[0] if rest else ""
        return name
    return ""


def _lese(pfad: Path) -> dict[str, str] | None:
    """Ein Menüeintrag, oder ``None``, wenn er hier nicht hergehört."""
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    im_eintrag = False
    name = name_de = programm = klasse = ""
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile == "[Desktop Entry]":
            im_eintrag = True
            continue
        if zeile.startswith("[") and zeile.endswith("]"):
            if im_eintrag:
                break  # der erste Eintrag ist vorbei, dahinter kommt nichts Nütze
            continue
        if not im_eintrag or "=" not in zeile:
            continue
        schluessel, _, wert = zeile.partition("=")
        schluessel = schluessel.strip()
        if schluessel == "Name" and not name:
            name = wert.strip()
        elif schluessel == "Name[de]" and not name_de:
            name_de = wert.strip()
        elif schluessel == "Exec" and not programm:
            programm = _programm(wert)
        elif schluessel == "StartupWMClass" and not klasse:
            klasse = wert.strip()
        elif schluessel == "Type" and wert.strip() != "Application":
            return None
        elif schluessel in ("NoDisplay", "Hidden") and wert.strip().lower() == "true":
            return None
    programm = klasse or programm
    if not name or not programm:
        return None
    eintrag = {"name": name, "exec": programm}
    if name_de:
        eintrag["name_de"] = name_de
    return eintrag


def list_applications() -> list[dict[str, str]]:
    """Alle Programme, die ein Menü haben, sortiert und ohne Doppelte."""
    eintraege: dict[tuple[str, str], dict[str, str]] = {}
    # Überschrieben wird nach Dateiname: Wer eine Systemdatei mit
    # ``NoDisplay=true`` in sein Verzeichnis kopiert, will sie verstecken —
    # dann darf die Systemfassung nicht doch wieder auftauchen.
    gesehen: set[str] = set()
    for verzeichnis in _verzeichnisse():
        if not verzeichnis.is_dir():
            continue
        for datei in sorted(verzeichnis.glob("*.desktop")):
            if datei.name in gesehen:
                continue
            gesehen.add(datei.name)
            eintrag = _lese(datei)
            if eintrag is None:
                continue
            eintraege.setdefault(
                (eintrag["name"].casefold(), eintrag["exec"]), eintrag
            )
    return sorted(eintraege.values(), key=lambda eintrag: eintrag["name"].casefold())
