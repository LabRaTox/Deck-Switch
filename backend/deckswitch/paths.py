"""Zentrale Pfad-Auflösung.

Alles Nutzerbezogene liegt unter ``~/.config/deckswitch/`` (laut Spec),
alles Mitgelieferte relativ zum Repo bzw. zum installierten Paket.

**Zwei Betriebsarten.** Aus einem Checkout heraus liegen Plugins, Overlay
und gebaute Oberfläche dort, wo sie im Repo entstehen — in drei
verschiedenen Ordnern. Als Paket installiert liegen sie gemeinsam unter
``/usr/share/deckswitch/``. Welche der beiden gilt, entscheidet sich hier
an genau einer Stelle; der übrige Code fragt nur noch nach dem fertigen
Pfad. Vorher stand die Rechnerei an vier Stellen verstreut, jede mit einem
eigenen ``parents[…]`` — und jede davon zeigte nach einer Installation
irgendwohin.
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

# -- Mitgeliefertes: Repo oder Installation ---------------------------------


def _repo_root() -> Path | None:
    """Die Repo-Wurzel, wenn die App aus einem Checkout läuft.

    Erkannt am Ordner ``packaging/``: Den gibt es nur im Repo, während
    ``backend/`` unter einem anderen Namen als Paket auch installiert
    existieren könnte.
    """
    kandidat = Path(__file__).resolve().parents[2]
    return kandidat if (kandidat / "packaging").is_dir() else None


#: Wo ein installiertes Paket sein Mitgeliefertes ablegt. Über die
#: Umgebungsvariable umstellbar — nur so lässt sich der Installationsfall
#: prüfen, ohne vorher wirklich zu installieren.
SHARE_DIR: Path = Path(
    os.environ.get("DECKSWITCH_SHARE_DIR") or "/usr/share/deckswitch"
)

#: ``None``, sobald die App installiert ist oder die Variable gesetzt wurde.
REPO_ROOT: Path | None = None if os.environ.get("DECKSWITCH_SHARE_DIR") else _repo_root()


def _bundled(im_repo: str, installiert: str) -> Path:
    """Ein mitgeliefertes Verzeichnis — je nach Betriebsart."""
    if REPO_ROOT is not None:
        return REPO_ROOT / im_repo
    return SHARE_DIR / installiert


#: Mitgelieferte Plugins — technisch gleichwertig, nur anderer Suchpfad.
BUILTIN_PLUGINS_DIR: Path = _bundled("backend/plugins", "plugins")

#: Das QML-Programm des Overlays.
OVERLAY_QML: Path = _bundled(
    "packaging/overlay/deck-overlay.qml", "overlay/deck-overlay.qml"
)

#: Die gebaute Oberfläche, die der Server ausliefert.
GUI_DIST: Path = _bundled("gui/dist", "gui")

def gui_command() -> list[str] | None:
    """Der Befehl, der das Fenster öffnet — oder ``None``, wenn es keins gibt.

    Im Checkout wird ``start-gui.sh`` genommen und nicht die Binärdatei
    direkt: Das Skript fängt den Wayland-Fehlstart ab, an dem das Fenster
    auf manchen Treibern sonst sofort stirbt. Aufgerufen wird es aber nur,
    wenn schon gebaut wurde — sonst würde ein Klick im Systemabschnitt
    minutenlang unsichtbar kompilieren.

    Ist die App installiert, bringt das Paket ``deckswitch-gui`` mit.
    """
    if REPO_ROOT is not None:
        gebaut = REPO_ROOT / "gui/src-tauri/target/release/deckswitch"
        starter = REPO_ROOT / "scripts/start-gui.sh"
        if os.access(gebaut, os.X_OK) and os.access(starter, os.X_OK):
            return [str(starter)]
        return None

    pfad = shutil.which("deckswitch-gui")
    return [pfad] if pfad else None


#: Die vom Paket mitgelieferte systemd-Unit. Gibt es sie, gehört sie der
#: Paketverwaltung und wird nicht überschrieben.
PACKAGED_UNIT: Path = Path("/usr/lib/systemd/user/deckswitch.service")

LOG_FILE: Path = DATA_DIR / "deckswitch.log"

#: Frühere Stände der Konfiguration. Eine Belegung ist Handarbeit und steht
#: in genau einer Datei — vor jedem Überschreiben wandert eine Kopie hierhin.
BACKUP_DIR: Path = DATA_DIR / "backups"


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
