"""Zentrale Pfad-Auflösung.

Alles Nutzerbezogene liegt unter ``~/.config/deckswitch/`` (laut Spec),
alles Mitgelieferte relativ zum Repo bzw. zum installierten Paket.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def _xdg(var: str, default: str) -> Path:
    raw = os.environ.get(var)
    return Path(raw) if raw else Path.home() / default


CONFIG_DIR: Path = _xdg("XDG_CONFIG_HOME", ".config") / "deckswitch"
DATA_DIR: Path = _xdg("XDG_DATA_HOME", ".local/share") / "deckswitch"

CONFIG_FILE: Path = CONFIG_DIR / "config.json"

#: Vom User pro Belegung hochgeladene Icons/Bilder.
UPLOADS_DIR: Path = DATA_DIR / "uploads"

#: Touchstrip-Hintergründe. Bewusst neben den Uploads statt darin: ein
#: 800×100-Streifen ist als Icon oder Kachelhintergrund nicht zu gebrauchen
#: und stünde in einem gemeinsamen Topf in jeder Bildauswahl im Weg.
WALLPAPERS_DIR: Path = DATA_DIR / "wallpapers"

#: Wo nach einer Bilddatei gesucht wird, wenn nur ihr Name bekannt ist.
IMAGE_DIRS: tuple[Path, ...] = (UPLOADS_DIR, WALLPAPERS_DIR)

#: Nachinstallierte Plugins (Action- wie Iconset-Plugins).
USER_PLUGINS_DIR: Path = DATA_DIR / "plugins"

#: Mitgelieferte Plugins — technisch gleichwertig, nur anderer Suchpfad.
BUILTIN_PLUGINS_DIR: Path = Path(__file__).resolve().parent.parent / "plugins"

LOG_FILE: Path = DATA_DIR / "deckswitch.log"


#: Wie die Ordner hießen, bevor die Software DECK//SWITCH wurde. Wer von
#: einer älteren Fassung kommt, hat seine Belegungen dort liegen.
LEGACY_NAME = "streamdeck-app"
LEGACY_CONFIG_DIR: Path = _xdg("XDG_CONFIG_HOME", ".config") / LEGACY_NAME
LEGACY_DATA_DIR: Path = _xdg("XDG_DATA_HOME", ".local/share") / LEGACY_NAME


def migrate_legacy_dirs() -> list[str]:
    """Zieht Konfiguration und Daten aus den alten Ordnern um.

    Wird beim Start aufgerufen, *bevor* etwas gelesen wird. Verschoben wird
    nur, wenn der alte Ordner existiert und der neue noch nicht — sonst
    würde ein zweiter Start eine bereits gepflegte Konfiguration mit einer
    alten überschreiben.

    Der alte Ordner bleibt als ``…-alt`` liegen statt gelöscht zu werden.
    Bei fremden Daten ist ein Umzug schon Eingriff genug; das Aufräumen
    darf der Benutzer selbst entscheiden.
    """
    moved = []
    for old, new in ((LEGACY_CONFIG_DIR, CONFIG_DIR), (LEGACY_DATA_DIR, DATA_DIR)):
        if not old.is_dir() or new.exists():
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(old, new)
            old.rename(old.with_name(f"{old.name}-alt"))
            moved.append(f"{old} → {new}")
        except OSError as exc:
            log.error("Umzug von %s nach %s fehlgeschlagen: %s", old, new, exc)
    return moved


def image_path(filename: str, *dirs: Path) -> Path | None:
    """Sucht eine Bilddatei in den Ablagen — ``None``, wenn es sie nicht gibt.

    In der Konfiguration steht nur der Dateiname, nicht die Ablage; gesucht
    wird deshalb der Reihe nach in allen. Der Abgleich gegen ``parents``
    hält Pfadangaben wie ``../../etc/passwd`` draußen.
    """
    for directory in dirs or IMAGE_DIRS:
        candidate = (directory / filename).resolve()
        if directory.resolve() in candidate.parents and candidate.is_file():
            return candidate
    return None


def ensure_dirs() -> None:
    migrate_legacy_dirs()
    for path in (CONFIG_DIR, DATA_DIR, UPLOADS_DIR, WALLPAPERS_DIR, USER_PLUGINS_DIR):
        path.mkdir(parents=True, exist_ok=True)
