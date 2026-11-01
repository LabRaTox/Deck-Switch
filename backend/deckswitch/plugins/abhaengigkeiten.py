"""Was ein Plugin außer seinen eigenen Dateien braucht.

Jedes Plugin kann das im Manifest nennen::

    "dependencies": {
      "python": ["icalendar>=6.0"],
      "system": ["ffmpeg", {"arch": "python-gobject", "debian": "python3-gi"}]
    }

``python`` nennt Pakete von PyPI. Sie brauchen keine besonderen Rechte: Jedes
Plugin bekommt einen eigenen Ordner unter ``<plugins>/.deps/``, gefüllt von
``uv`` und beim Laden *ans Ende* von ``sys.path`` gehängt. Ein Plugin kann
also Pakete ergänzen, aber keines ersetzen, auf dem das Backend läuft. Genommen
werden nur fertige Wheels, damit beim Installieren kein Code eines Pakets
läuft. Verlangen zwei Plugins verschiedene Versionen desselben Pakets, teilen
sie sich die zuerst geladene.

``system`` nennt Pakete der Distribution. Ein einfacher Name gilt überall, wo
die Namen abweichen, nennt ein Objekt einen je Familie: ``arch``, ``debian``
(auch Ubuntu) und ``fedora``. Dafür braucht es root, also fragt ``pkexec``
nach dem Passwort. Geht das nicht oder lehnt jemand ab, nennt der Fehler den
Befehl für die Hand. Auf einem Fedora mit Image wie Bazzite kommt ein Paket
erst mit dem nächsten Start an, dort ist es immer Handarbeit. Ohne bekannten
Paketmanager wird jeder Name als Programm gesucht.

Alles muss da sein, bevor das Plugin installiert wird: :func:`sicherstellen`
wirft, wenn etwas fehlt, und der Installer hört dort auf.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.metadata
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from .. import paths, texte

#: So lange darf eine Installation dauern, die Passwortabfrage eingerechnet.
ZEITLIMIT_S = 300
#: Ein Paketname. Ohne Bindestrich vorn, damit er nie als Option gilt.
SYSTEMNAME = re.compile(r"^[A-Za-z0-9@_+][A-Za-z0-9@._+:-]{0,127}$")
#: Die Familien, für die ein ``system``-Eintrag ein Paket nennen kann.
FAMILIEN = ("arch", "debian", "fedora")
#: Kennzeichnet ein System, das ein Image startet, so dokumentiert ``ostree``.
OSTREE_MARKE = Path("/run/ostree-booted")
#: Wo ``uv`` liegt, wenn es kein Systempaket ist. Ein systemd-Dienst hat
#: nichts davon im PATH, dass die Login-Shell es findet, beweist hier nichts.
UV_ORTE = ("~/.local/bin/uv", "~/.cargo/bin/uv", "/home/linuxbrew/.linuxbrew/bin/uv")


class AbhaengigkeitsFehler(Exception):
    """Die Angaben eines Plugins sind kaputt oder lassen sich nicht erfüllen."""


def _liste(abschnitt: dict[str, Any], schluessel: str) -> list[Any]:
    werte = abschnitt.get(schluessel, [])
    if not isinstance(werte, list):
        raise AbhaengigkeitsFehler(texte.t("abhaengigkeiten.keine_liste", feld=schluessel))
    return werte


def angegeben(rohdaten: Any) -> dict[str, list[Any]]:
    """Die ``dependencies`` eines Manifests, geprüft.

    Python-Pakete müssen unter ihrem Namen vom Paketindex kommen: Eine direkte
    Adresse ginge an allem vorbei, was der Store an einem Plugin ansieht.
    """
    if not isinstance(rohdaten, dict):
        raise AbhaengigkeitsFehler(texte.t("abhaengigkeiten.kein_objekt"))
    python = _liste(rohdaten, "python")
    system = _liste(rohdaten, "system")
    for angabe in python:
        try:
            anforderung = Requirement(angabe) if isinstance(angabe, str) else None
        except InvalidRequirement:
            anforderung = None
        if anforderung is None:
            raise AbhaengigkeitsFehler(
                texte.t("abhaengigkeiten.python_ungueltig", angabe=repr(angabe))
            )
        if anforderung.url:
            raise AbhaengigkeitsFehler(texte.t("abhaengigkeiten.python_adresse", angabe=angabe))
    for eintrag in system:
        namen = list(eintrag.values()) if isinstance(eintrag, dict) else [eintrag]
        gueltig = bool(namen) and all(
            isinstance(name, str) and SYSTEMNAME.match(name) for name in namen
        )
        if not gueltig or (isinstance(eintrag, dict) and set(eintrag) - set(FAMILIEN)):
            raise AbhaengigkeitsFehler(
                texte.t("abhaengigkeiten.system_ungueltig", angabe=repr(eintrag))
            )
    return {"python": python, "system": system}


def ordner(plugin_id: str) -> Path:
    """Wo die Python-Pakete eines Plugins liegen."""
    return paths.USER_PLUGINS_DIR / ".deps" / plugin_id


def _starte(befehl: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(befehl, capture_output=True, text=True, timeout=ZEITLIMIT_S, check=False)


def _erfuellt(angabe: str, suchpfad: list[str]) -> bool:
    anforderung = Requirement(angabe)
    if anforderung.marker is not None and not anforderung.marker.evaluate():
        return True
    # Ein Extra bringt eigene Pakete mit, das zeigt die Version allein nicht.
    if anforderung.extras:
        return False
    gefunden = next(
        iter(importlib.metadata.distributions(name=anforderung.name, path=suchpfad)), None
    )
    if gefunden is None:
        return False
    return anforderung.specifier.contains(gefunden.version, prereleases=True)


def fehlende_python(plugin_id: str, angaben: list[str]) -> list[str]:
    # Was ein anderes Plugin mitbrachte, zählt nicht: Es geht mit diesem Plugin.
    fremde = str(ordner(plugin_id).parent)
    suchpfad = [
        str(ordner(plugin_id)),
        *(pfad for pfad in sys.path if not pfad.startswith(fremde)),
    ]
    return [angabe for angabe in angaben if not _erfuellt(angabe, suchpfad)]


def _pacman_fehlt(namen: list[str]) -> list[str]:
    # ``pacman -T`` nennt, was nicht installiert ist, je Zeile ein Name.
    return _starte(["pacman", "-T", *namen]).stdout.split()


def _dpkg_fehlt(namen: list[str]) -> list[str]:
    def da(name: str) -> bool:
        return "install ok installed" in _starte(
            ["dpkg-query", "-W", "-f=${Status}", name]
        ).stdout

    return [name for name in namen if not da(name)]


def _rpm_fehlt(namen: list[str]) -> list[str]:
    return [
        name
        for name in namen
        if _starte(["rpm", "-q", "--whatprovides", name]).returncode != 0
    ]


@dataclasses.dataclass(frozen=True)
class Paketmanager:
    familie: str
    fehlt: Callable[[list[str]], list[str]]
    #: Was man von Hand aufruft.
    von_hand: tuple[str, ...]
    #: Was ``pkexec`` aufruft. Leer, wo die Installation nicht von selbst fertig wird.
    automatisch: tuple[str, ...] = ()
    #: Ob das Paket erst nach einem Neustart ankommt.
    neustart: bool = False

    def befehl(self, namen: list[str]) -> str:
        return shlex.join([*self.von_hand, *namen])


PACMAN = Paketmanager(
    "arch", _pacman_fehlt, ("sudo", "pacman", "-S", "--needed"),
    ("pacman", "-S", "--needed", "--noconfirm"),
)
APT = Paketmanager(
    "debian", _dpkg_fehlt, ("sudo", "apt", "install"), ("apt-get", "install", "-y"),
)
DNF = Paketmanager(
    "fedora", _rpm_fehlt, ("sudo", "dnf", "install"), ("dnf", "install", "-y"),
)
RPM_OSTREE = Paketmanager(
    "fedora", _rpm_fehlt, ("sudo", "rpm-ostree", "install"),
    neustart=True,
)


def paketmanager() -> Paketmanager | None:
    """Der, dem dieses System gehört.

    Ein Image zuerst: ``dnf`` kann dort vorhanden sein, ändert das Image aber
    nicht.
    """
    if OSTREE_MARKE.exists() and shutil.which("rpm-ostree"):
        return RPM_OSTREE
    if shutil.which("pacman"):
        return PACMAN
    if shutil.which("apt-get") and shutil.which("dpkg-query"):
        return APT
    if shutil.which("dnf"):
        return DNF
    return None


def _namen_fuer(eintraege: list[Any], familie: str) -> list[str]:
    """Die Paketnamen dieser Familie.

    Fehlt für einen Eintrag der Name, stoppt das die Installation: Raten
    könnte etwas ganz anderes holen.
    """
    namen = []
    for eintrag in eintraege:
        if isinstance(eintrag, str):
            namen.append(eintrag)
        elif familie in eintrag:
            namen.append(eintrag[familie])
        else:
            raise AbhaengigkeitsFehler(
                texte.t(
                    "abhaengigkeiten.kein_name_fuer_familie",
                    namen=" / ".join(eintrag.values()),
                    familie=familie,
                )
            )
    return namen


def _ohne_paketmanager(eintraege: list[Any]) -> None:
    def da(eintrag: Any) -> bool:
        namen = eintrag.values() if isinstance(eintrag, dict) else [eintrag]
        return any(shutil.which(name) for name in namen)

    uebrig = [eintrag for eintrag in eintraege if not da(eintrag)]
    if uebrig:
        namen = [" / ".join(e.values()) if isinstance(e, dict) else e for e in uebrig]
        raise AbhaengigkeitsFehler(
            texte.t("abhaengigkeiten.fehlt_von_hand", namen=", ".join(namen))
        )


def sichere_system(eintraege: list[Any]) -> None:
    """Holt alle Systempakete oder sagt, was zu tun ist."""
    if not eintraege:
        return
    manager = paketmanager()
    if manager is None:
        _ohne_paketmanager(eintraege)
        return
    namen = _namen_fuer(eintraege, manager.familie)
    uebrig = manager.fehlt(namen)
    if uebrig and manager.automatisch and shutil.which("pkexec"):
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            _starte(["pkexec", *manager.automatisch, *uebrig])
        # Nach dem Ergebnis beurteilt: Am Rückgabewert von pkexec sieht man
        # nicht, ob das Passwort abgelehnt wurde oder der Paketmanager
        # mittendrin aufgab.
        uebrig = manager.fehlt(uebrig)
    if uebrig:
        namen, befehl = ", ".join(uebrig), manager.befehl(uebrig)
        raise AbhaengigkeitsFehler(
            texte.t("abhaengigkeiten.fehlt_befehl_neustart", namen=namen, befehl=befehl)
            if manager.neustart
            else texte.t("abhaengigkeiten.fehlt_befehl", namen=namen, befehl=befehl)
        )


def finde_uv() -> str | None:
    gefunden = shutil.which("uv")
    if gefunden:
        return gefunden
    # Aus der venv heraus liegt es neben dem Interpreter, ohne im PATH zu stehen.
    orte = [Path(sys.executable).parent / "uv", *(Path(ort).expanduser() for ort in UV_ORTE)]
    return next((str(ort) for ort in orte if ort.is_file()), None)


def installiere_python(plugin_id: str, angaben: list[str]) -> None:
    """Füllt den Ordner des Plugins neu. Der alte bleibt, bis das geklappt hat."""
    liste = ", ".join(angaben)
    uv = finde_uv()
    if uv is None:
        raise AbhaengigkeitsFehler(texte.t("abhaengigkeiten.kein_uv", namen=liste))
    ziel = ordner(plugin_id)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zwischenablage = ziel.parent / f".staging-{uuid.uuid4().hex}"
    try:
        try:
            ergebnis = _starte([
                uv, "pip", "install", "--quiet", "--python", sys.executable,
                "--target", str(zwischenablage), "--only-binary", ":all:", *angaben,
            ])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AbhaengigkeitsFehler(
                texte.t("abhaengigkeiten.python_gescheitert", namen=liste, grund=exc)
            ) from exc
        if ergebnis.returncode != 0:
            zeilen = ergebnis.stderr.strip().splitlines()
            grund = zeilen[-1].strip() if zeilen else f"uv: {ergebnis.returncode}"
            raise AbhaengigkeitsFehler(
                texte.t("abhaengigkeiten.python_gescheitert", namen=liste, grund=grund)
            )
        abmelden(plugin_id)
        shutil.rmtree(ziel, ignore_errors=True)
        zwischenablage.rename(ziel)
    finally:
        shutil.rmtree(zwischenablage, ignore_errors=True)


def sicherstellen(plugin_id: str, rohdaten: Any) -> None:
    """Erfüllt, was ein Plugin braucht, oder wirft.

    Systempakete zuerst: Sie können die Installation stoppen, und das soll
    passieren, bevor etwas heruntergeladen wurde.
    """
    bedarf = angegeben(rohdaten)
    sichere_system(bedarf["system"])
    if not bedarf["python"]:
        # Eine neue Fassung kann ohne auskommen, die alten Pakete müssen weg.
        entfernen(plugin_id)
    elif fehlende_python(plugin_id, bedarf["python"]):
        installiere_python(plugin_id, bedarf["python"])


def anmelden(plugin_id: str) -> None:
    """Macht die Pakete eines Plugins importierbar. Ans Ende, siehe oben."""
    pfad = str(ordner(plugin_id))
    if ordner(plugin_id).is_dir() and pfad not in sys.path:
        sys.path.append(pfad)
        importlib.invalidate_caches()


def abmelden(plugin_id: str) -> None:
    pfad = str(ordner(plugin_id))
    if pfad in sys.path:
        sys.path.remove(pfad)
        importlib.invalidate_caches()


def entfernen(plugin_id: str) -> None:
    """Die Pakete gehen mit dem Plugin."""
    abmelden(plugin_id)
    shutil.rmtree(ordner(plugin_id), ignore_errors=True)
