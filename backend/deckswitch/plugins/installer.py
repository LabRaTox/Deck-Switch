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
from .. import texte

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
            texte.t("installer.http_s_adressen_werden", scheme=parsed.scheme or url[:20])
        )
    if not parsed.netloc:
        raise InstallError(texte.t("installer.adresse_unvollstaendig"))

    request = urllib.request.Request(
        url, headers={"User-Agent": "StreamDeckApp/0.1 (+local)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise InstallError(texte.t("installer.archiv_gross_max_64"))
            # Ein Byte mehr lesen, um auch ohne Content-Length zu begrenzen.
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise InstallError(texte.t("installer.download_fehlgeschlagen", code=exc.code)) from exc
    except urllib.error.URLError as exc:
        raise InstallError(texte.t("installer.adresse_nicht_erreichbar", reason=exc.reason)) from exc
    except (TimeoutError, OSError) as exc:
        raise InstallError(texte.t("installer.download_abgebrochen", exc=exc)) from exc

    if len(data) > MAX_ARCHIVE_BYTES:
        raise InstallError(texte.t("installer.archiv_gross_max_64"))
    if not data:
        raise InstallError(texte.t("installer.leere_antwort"))
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
        raise ChecksumError(texte.t("installer.keine_pruefsumme_angegeben"))
    if len(erwartet) != 64 or any(z not in "0123456789abcdef" for z in erwartet):
        raise ChecksumError(
            texte.t("installer.pruefsumme_sieht_nicht_wie")
        )

    tatsaechlich = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(tatsaechlich, erwartet):
        raise ChecksumError(
            texte.t("installer.pruefsumme_stimmt_nicht_erwartet", erwartet=erwartet[:12], tatsaechlich=tatsaechlich[:12])
        )
    return tatsaechlich


def install_url(url: str, *, sha256: str = "", expected_id: str = "") -> Manifest:
    """Lädt ein Plugin-Archiv von einer Adresse und installiert es.

    Ist ``sha256`` angegeben, muss es passen — sonst wird nichts
    ausgepackt. Ohne Angabe wird installiert wie bisher; die Oberfläche
    weist dann darauf hin, dass niemand geprüft hat, was da ankommt.

    ``expected_id`` ist die Plugin-ID, nach der gefragt wurde, etwa der Slug
    aus dem Store. Ein Archiv mit anderer ID wird abgelehnt, damit es kein
    fremdes Plugin überschreiben kann.
    """
    data = download(url)
    if sha256:
        pruefe_sha256(data, sha256)
    return install_archive(data, filename=url.rsplit("/", 1)[-1], expected_id=expected_id)


# --------------------------------------------------------------------------
# Installation aus einem Archiv
# --------------------------------------------------------------------------


def install_archive(data: bytes, *, filename: str = "", expected_id: str = "") -> Manifest:
    """Entpackt ein Plugin-Archiv und installiert es."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InstallError(texte.t("installer.archiv_gross_max_64"))

    with tempfile.TemporaryDirectory(prefix="streamdeck-plugin-") as tmp:
        staging = Path(tmp) / "unpacked"
        staging.mkdir()

        _extract(data, staging)

        source = _find_plugin_root(staging)
        if source is None:
            raise InstallError(
                texte.t("installer.kein_plugin_gefunden_archiv")
            )
        manifest = _read_manifest(source)
        if manifest is None:
            raise InstallError(texte.t("installer.manifest_json_unlesbar_oder"))
        if expected_id and manifest.id != expected_id:
            raise InstallError(
                texte.t("installer.id_manifest_passt_nicht", id=manifest.id, plugin_id=expected_id)
            )

        return _install_from_directory(source, manifest.id)


def _extract(data: bytes, target: Path) -> None:
    """Entpackt ein ZIP — ohne Pfade außerhalb des Ziels und ohne Symlinks."""
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InstallError(texte.t("installer.kein_gueltiges_zip_archiv", exc=exc)) from exc

    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise InstallError(texte.t("installer.archiv_enthaelt_viele_dateien"))
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        raise InstallError(texte.t("installer.archivinhalt_gross_max_256"))

    resolved_target = target.resolve()
    for entry in entries:
        name = entry.filename
        # Ein Backslash ist unter Linux Teil des Dateinamens, andere Programme
        # lesen ihn als Trenner. Solche Archive sehen je nach Leser anders aus.
        if "\\" in name:
            raise InstallError(texte.t("installer.unerlaubter_pfad_archiv", name=name))
        if name.startswith("/") or ".." in Path(name).parts:
            raise InstallError(texte.t("installer.unerlaubter_pfad_archiv", name=name))

        # Symlinks im ZIP könnten aus dem Zielordner herauszeigen.
        if (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise InstallError(texte.t("installer.symlinks_werden_nicht_entpackt", name=name))

        destination = (resolved_target / name).resolve()
        if resolved_target != destination and resolved_target not in destination.parents:
            raise InstallError(texte.t("installer.eintrag_zeigt_aus_zielordner", name=name))

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

    # Mehr als ein Plugin-Ordner wird abgelehnt. Sonst hinge es von der
    # Reihenfolge im Dateisystem ab, welcher installiert wird.
    candidates = sorted(p for p in staging.iterdir() if p.is_dir())
    found = [d for d in candidates if (d / "manifest.json").is_file()]
    if not found:
        # Eine Ebene tiefer suchen, manche Packer legen noch einen Ordner an.
        found = [
            nested
            for directory in candidates
            for nested in sorted(directory.iterdir())
            if nested.is_dir() and (nested / "manifest.json").is_file()
        ]
    if len(found) > 1:
        raise InstallError(texte.t("installer.mehrere_plugins_archiv"))
    return found[0] if found else None


def _install_from_directory(source: Path, plugin_id: str) -> Manifest:
    manifest = _read_manifest(source)
    if manifest is None:
        raise InstallError(texte.t("installer.manifest_json_unlesbar_oder"))

    if manifest.id != plugin_id:
        raise InstallError(
            texte.t("installer.id_manifest_passt_nicht", id=manifest.id, plugin_id=plugin_id)
        )
    if not VALID_ID.match(manifest.id):
        raise InstallError(
            texte.t("installer.ungueltige_plugin_id_erlaubt", id=manifest.id)
        )
    if manifest.type != "iconset" and not (manifest.entry and manifest.plugin_class):
        raise InstallError(
            texte.t("installer.plugin_braucht_entry_class", type=manifest.type)
        )

    builtin = paths.BUILTIN_PLUGINS_DIR / manifest.id
    if builtin.is_dir():
        raise InstallError(
            texte.t("installer.bereits_eingebaut_kann_nicht", id=manifest.id)
        )

    paths.USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    target = _ordner_fuer(manifest.id)

    # Erst neben das Ziel kopieren, dann tauschen — bricht das Kopieren ab,
    # bleibt eine vorhandene Installation unversehrt.
    staged = paths.USER_PLUGINS_DIR / f".{target.name}.new"
    backup = paths.USER_PLUGINS_DIR / f".{target.name}.old"
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
        raise InstallError(texte.t("installer.installation_fehlgeschlagen", exc=exc)) from exc
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
        raise InstallError(texte.t("installer.ungueltige_plugin_id"))

    if (paths.BUILTIN_PLUGINS_DIR / plugin_id).is_dir():
        raise InstallError(texte.t("installer.eingebaute_plugins_lassen_nicht"))

    # Gesucht wird über das Manifest und nicht über den Ordnernamen: Der ist
    # eine Nummer und sagt nichts darüber, was darin liegt.
    target = _finde_ordner(plugin_id)
    if target is None:
        raise InstallError(texte.t("installer.nicht_installiert", plugin_id=plugin_id))

    root = paths.USER_PLUGINS_DIR.resolve()
    if root not in target.resolve().parents:
        raise InstallError(texte.t("installer.liegt_nicht_plugin_verzeichnis", plugin_id=plugin_id))

    shutil.rmtree(target)
    log.info("Plugin '%s' entfernt (%s)", plugin_id, target.name)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def _finde_ordner(plugin_id: str) -> Path | None:
    """Der Ordner, in dem dieses Plugin liegt — oder ``None``.

    Über das Manifest und nicht über den Namen: Seit die Ordner Nummern
    tragen, sagt der Name nichts mehr über den Inhalt. Ordner aus früheren
    Fassungen heißen noch wie die Kennung; auch die findet diese Suche, denn
    sie sieht in jedes Manifest.
    """
    if not paths.USER_PLUGINS_DIR.is_dir():
        return None
    for eintrag in sorted(paths.USER_PLUGINS_DIR.iterdir()):
        if not eintrag.is_dir() or eintrag.name.startswith((".", "_")):
            continue
        manifest = _read_manifest(eintrag)
        if manifest is not None and manifest.id == plugin_id:
            return eintrag
    return None


def _ordner_fuer(plugin_id: str) -> Path:
    """Wohin dieses Plugin installiert wird.

    **Warum eine Nummer und nicht die Kennung.** Zwei Plugins mit derselben
    Kennung soll es zwar nicht geben — der Store lässt jede nur einmal zu —,
    aber auf der Platte hätte ein Name aus einem Archiv trotzdem
    Macht: Wer ein Plugin von Hand installiert, bestimmt damit einen
    Ordnernamen, und ein Manifest ist nichts als eine Behauptung. Eine
    laufende Nummer nimmt dem Archiv diese Entscheidung ab.

    Ist das Plugin schon da, bleibt es in seinem Ordner: Eine neue Fassung
    ersetzt die alte an Ort und Stelle, statt daneben eine zweite anzulegen.
    """
    vorhanden = _finde_ordner(plugin_id)
    if vorhanden is not None:
        return vorhanden

    hoechste = 0
    if paths.USER_PLUGINS_DIR.is_dir():
        for eintrag in paths.USER_PLUGINS_DIR.iterdir():
            if eintrag.is_dir() and eintrag.name.isdigit():
                hoechste = max(hoechste, int(eintrag.name))
    # Vierstellig, damit eine Auflistung in der Reihenfolge der Installation
    # steht und nicht 10 vor 2 einsortiert.
    return paths.USER_PLUGINS_DIR / f"{hoechste + 1:04d}"


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
