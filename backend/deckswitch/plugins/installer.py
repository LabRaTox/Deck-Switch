"""Installieren und Entfernen von Plugins.

Ein Plugin ist ein Ordner mit ``manifest.json``. Zum Verteilen wird er als
ZIP verpackt — entweder mit dem Plugin-Ordner als oberster Ebene oder mit
den Dateien direkt in der Wurzel; beides wird erkannt.

Installiert wird immer nach ``~/.local/share/deckswitch/plugins/``.
Mitgelieferte Plugins in ``backend/plugins/`` bleiben unangetastet und
lassen sich nicht überschreiben oder löschen.

Sicherheitshinweis: Ein Action-Plugin ist Python-Code, der mit den Rechten
des Nutzers läuft. Das Entpacken ist deshalb streng (keine Pfade außerhalb
des Zielordners, keine Symlinks, Größenbegrenzung) — das schützt aber nur
vor verunglückten Archiven, nicht vor bösartigem Plugin-Code. Wer ein
Plugin installiert, vertraut seinem Autor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .. import paths
from .base import Manifest

log = logging.getLogger(__name__)

#: Obergrenzen beim Entpacken — schützt vor versehentlichen Zip-Bomben.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 20_000

VALID_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class InstallError(RuntimeError):
    pass


@dataclass(slots=True)
class InstallRequest:
    """Eine über ``streamdeck://`` angeforderte Installation.

    Bewusst nur *angefordert*: Ein Klick im Browser darf keinen Code auf dem
    Rechner installieren. Die Anfrage wartet, bis sie in der GUI bestätigt
    wird.
    """

    id: str
    url: str
    origin: str = ""
    created_at: float = 0.0
    #: Angekündigte Prüfsumme aus dem Link. Leer heißt: Niemand hat gesagt,
    #: was ankommen soll — die Oberfläche weist darauf hin.
    sha256: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "origin": self.origin,
            "created_at": self.created_at,
            "sha256": self.sha256,
        }


# --------------------------------------------------------------------------
# Installation aus dem Netz
# --------------------------------------------------------------------------

#: Nur diese Schemata werden geladen — `file://` wäre ein Weg, beliebige
#: Pfade des Rechners einzulesen.
ALLOWED_SCHEMES = ("http", "https")

DOWNLOAD_TIMEOUT_S = 30


def download(url: str) -> bytes:
    """Lädt ein Plugin-Archiv herunter.

    Blockierend — vom Aufrufer im Executor auszuführen.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise InstallError(
            f"Nur http(s)-Adressen werden geladen, nicht '{parsed.scheme or url[:20]}'"
        )
    if not parsed.netloc:
        raise InstallError("Adresse unvollständig")

    request = urllib.request.Request(
        url, headers={"User-Agent": "StreamDeckApp/0.1 (+local)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise InstallError("Archiv zu groß (max. 64 MB)")
            # Ein Byte mehr lesen, um auch ohne Content-Length zu begrenzen.
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise InstallError(f"Download fehlgeschlagen ({exc.code})") from exc
    except urllib.error.URLError as exc:
        raise InstallError(f"Adresse nicht erreichbar: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise InstallError(f"Download abgebrochen: {exc}") from exc

    if len(data) > MAX_ARCHIVE_BYTES:
        raise InstallError("Archiv zu groß (max. 64 MB)")
    if not data:
        raise InstallError("Leere Antwort")
    return data


class ChecksumError(InstallError):
    """Das Heruntergeladene ist nicht das Erwartete."""


def pruefe_sha256(data: bytes, erwartet: str) -> str:
    """Vergleicht die Prüfsumme und liefert die tatsächliche zurück.

    Der Vergleich ist unempfindlich gegen Groß- und Kleinschreibung und
    gegen umgebende Leerzeichen: Die Summe wird oft von Hand kopiert, und
    daran soll eine Installation nicht scheitern.

    **Warum das hier steht und nicht erst beim Auspacken.** Ein Archiv aus
    dem Netz ist fremder Code. Stimmt die Summe nicht, darf niemand mehr
    hineinsehen — auch nicht, um „nur mal das Manifest zu lesen". Zwischen
    Herunterladen und Auspacken gibt es genau einen Platz für diese
    Prüfung, und das ist dieser.
    """
    erwartet = erwartet.strip().lower()
    if not erwartet:
        raise ChecksumError("Keine Prüfsumme angegeben")
    if len(erwartet) != 64 or any(z not in "0123456789abcdef" for z in erwartet):
        raise ChecksumError(
            "Die Prüfsumme sieht nicht wie ein SHA-256 aus "
            "(erwartet werden 64 Zeichen aus 0-9 und a-f)"
        )

    tatsaechlich = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(tatsaechlich, erwartet):
        raise ChecksumError(
            "Die Prüfsumme stimmt nicht: erwartet wurde "
            f"{erwartet[:12]}…, geladen wurde {tatsaechlich[:12]}…. "
            "Das Archiv ist ein anderes als das angekündigte — es wird "
            "nicht installiert."
        )
    return tatsaechlich


def install_url(url: str, *, sha256: str = "") -> Manifest:
    """Lädt ein Plugin-Archiv von einer Adresse und installiert es.

    Ist ``sha256`` angegeben, muss es passen — sonst wird nichts
    ausgepackt. Ohne Angabe wird installiert wie bisher; die Oberfläche
    weist dann darauf hin, dass niemand geprüft hat, was da ankommt.
    """
    data = download(url)
    if sha256:
        pruefe_sha256(data, sha256)
    return install_archive(data, filename=url.rsplit("/", 1)[-1])


# --------------------------------------------------------------------------
# Installation aus einem Archiv
# --------------------------------------------------------------------------


def install_archive(data: bytes, *, filename: str = "") -> Manifest:
    """Entpackt ein Plugin-Archiv und installiert es."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InstallError("Archiv zu groß (max. 64 MB)")

    with tempfile.TemporaryDirectory(prefix="streamdeck-plugin-") as tmp:
        staging = Path(tmp) / "unpacked"
        staging.mkdir()
        _extract(data, staging)

        source = _find_plugin_root(staging)
        if source is None:
            raise InstallError(
                "Kein Plugin gefunden — im Archiv fehlt eine manifest.json"
            )
        manifest = _read_manifest(source)
        if manifest is None:
            raise InstallError("manifest.json ist unlesbar oder unvollständig")

        return _install_from_directory(source, manifest.id)


def _extract(data: bytes, target: Path) -> None:
    """Entpackt ein ZIP — ohne Pfade außerhalb des Ziels und ohne Symlinks."""
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InstallError(f"Kein gültiges ZIP-Archiv: {exc}") from exc

    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise InstallError("Archiv enthält zu viele Dateien")
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        raise InstallError("Archivinhalt zu groß (max. 256 MB entpackt)")

    resolved_target = target.resolve()
    for entry in entries:
        name = entry.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise InstallError(f"Unerlaubter Pfad im Archiv: {name}")

        # Symlinks im ZIP könnten aus dem Zielordner herauszeigen.
        if (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise InstallError(f"Symlinks werden nicht entpackt: {name}")

        destination = (resolved_target / name).resolve()
        if resolved_target != destination and resolved_target not in destination.parents:
            raise InstallError(f"Eintrag zeigt aus dem Zielordner heraus: {name}")

        if entry.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as source, open(destination, "wb") as handle:
            shutil.copyfileobj(source, handle, length=1024 * 64)


def _find_plugin_root(staging: Path) -> Path | None:
    """Findet den Ordner mit der manifest.json.

    Erkennt beide üblichen Packweisen: Plugin-Ordner als oberste Ebene oder
    Dateien direkt in der Archivwurzel.
    """
    if (staging / "manifest.json").is_file():
        return staging

    candidates = [p for p in staging.iterdir() if p.is_dir()]
    for directory in candidates:
        if (directory / "manifest.json").is_file():
            return directory

    # Eine Ebene tiefer suchen — manche Packer legen noch einen Ordner an.
    for directory in candidates:
        for nested in directory.iterdir():
            if nested.is_dir() and (nested / "manifest.json").is_file():
                return nested
    return None


def _install_from_directory(source: Path, plugin_id: str) -> Manifest:
    manifest = _read_manifest(source)
    if manifest is None:
        raise InstallError("manifest.json ist unlesbar oder unvollständig")

    if manifest.id != plugin_id:
        raise InstallError(
            f"ID im Manifest ('{manifest.id}') passt nicht zum Plugin ('{plugin_id}')"
        )
    if not VALID_ID.match(manifest.id):
        raise InstallError(
            f"Ungültige Plugin-ID '{manifest.id}' — erlaubt sind Kleinbuchstaben, "
            "Ziffern, Punkt, Bindestrich und Unterstrich"
        )
    if manifest.type != "iconset" and not (manifest.entry and manifest.plugin_class):
        raise InstallError(
            f"{manifest.type}-Plugin braucht 'entry' und 'class' im Manifest"
        )

    builtin = paths.BUILTIN_PLUGINS_DIR / manifest.id
    if builtin.is_dir():
        raise InstallError(
            f"'{manifest.id}' ist bereits eingebaut und kann nicht ersetzt werden"
        )

    paths.USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    target = paths.USER_PLUGINS_DIR / manifest.id

    # Erst neben das Ziel kopieren, dann tauschen — bricht das Kopieren ab,
    # bleibt eine vorhandene Installation unversehrt.
    staged = paths.USER_PLUGINS_DIR / f".{manifest.id}.new"
    backup = paths.USER_PLUGINS_DIR / f".{manifest.id}.old"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)

    try:
        shutil.copytree(source, staged, symlinks=False, ignore=_ignore_junk)
        if target.exists():
            target.rename(backup)
        staged.rename(target)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise InstallError(f"Installation fehlgeschlagen: {exc}") from exc
    finally:
        shutil.rmtree(backup, ignore_errors=True)

    log.info("Plugin '%s' v%s installiert nach %s", manifest.id, manifest.version, target)
    return manifest


def _ignore_junk(_directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n in {"__pycache__", ".git", ".DS_Store"} or n.endswith(".pyc")}


# --------------------------------------------------------------------------
# Entfernen
# --------------------------------------------------------------------------


def uninstall(plugin_id: str) -> None:
    if not VALID_ID.match(plugin_id or ""):
        raise InstallError("Ungültige Plugin-ID")

    if (paths.BUILTIN_PLUGINS_DIR / plugin_id).is_dir():
        raise InstallError("Eingebaute Plugins lassen sich nicht entfernen")

    target = (paths.USER_PLUGINS_DIR / plugin_id).resolve()
    root = paths.USER_PLUGINS_DIR.resolve()
    if root not in target.parents or not target.is_dir():
        raise InstallError(f"'{plugin_id}' ist nicht installiert")

    shutil.rmtree(target)
    log.info("Plugin '%s' entfernt", plugin_id)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def _read_manifest(directory: Path) -> Manifest | None:
    manifest_file = directory / "manifest.json"
    if not manifest_file.is_file():
        return None
    try:
        return Manifest.model_validate(
            json.loads(manifest_file.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        log.debug("Manifest in %s unlesbar: %s", directory, exc)
        return None
