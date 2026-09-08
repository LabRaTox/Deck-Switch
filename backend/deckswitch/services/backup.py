"""Sicherung, Wiederherstellung und Austausch einzelner Profile.

Drei Dinge, die sich einen Unterbau teilen:

* **Sicherungspaket** — ein ZIP mit der Konfiguration und den eigenen
  Bildern. Der reine JSON-Export der Config reicht dafür nicht: Eine Taste
  verweist auf eine hochgeladene Datei, und ohne die käme sie leer zurück.
* **Zeitreise** — der Store legt vor jedem Überschreiben eine Kopie der
  Konfiguration ab (siehe ``ConfigStore._rotate_backup``). Diese Stände
  liegen längst auf der Platte; hier bekommen sie einen Weg zurück.
* **Profilpaket** — ein einzelnes Profil weitergeben, samt der Bilder, die
  darin vorkommen.

Klänge des Soundboards sind bewusst nicht dabei: Sie werden über beliebige
Pfade eingebunden und liegen irgendwo im Dateisystem, nicht in unserem
Datenverzeichnis. Die Verweise darauf überstehen eine Sicherung, die Dateien
selbst muss der Benutzer wie jede andere eigene Datei sichern.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..config import Config, ConfigStore, Profile

log = logging.getLogger(__name__)

#: Aufbau der Pakete. Wird beim Einlesen geprüft, damit eine fremde ZIP-Datei
#: nicht als Sicherung durchgeht.
ARCHIVE_KIND = "deckswitch-backup"
PROFILE_KIND = "deckswitch-profile"
FORMAT_VERSION = 1

#: Was an Bildern mitgenommen wird — dieselben Endungen, die auch der
#: Upload-Endpunkt annimmt. Alles andere wird beim Einspielen übergangen.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"})

#: Obergrenze beim Auspacken. Ein Paket, das sich zu Gigabytes entfaltet,
#: soll nicht die Platte füllen, bevor jemand es merkt.
MAX_UNPACKED_BYTES = 256 * 1024 * 1024

#: Die Ordner, die ein Paket mitbringt: Name im Archiv → Ziel auf der Platte.
BUNDLED_DIRS: dict[str, Path] = {
    "uploads": paths.UPLOADS_DIR,
    "wallpapers": paths.WALLPAPERS_DIR,
}


class BackupError(RuntimeError):
    """Das Paket ist nicht das, was es sein sollte."""


# ---------------------------------------------------------------- Hilfen


def _safe_name(name: str) -> str | None:
    """Nur den Dateinamen gelten lassen — nie einen Pfad.

    Ein Archiv darf bestimmen, *wie* eine Datei heißt, aber nicht *wo* sie
    landet. Einträge wie ``../../.bashrc`` oder ``/etc/passwd`` verlieren
    hier ihren Pfadanteil und damit ihre Wirkung.
    """
    knapp = Path(name).name
    if not knapp or knapp in {".", ".."}:
        return None
    if Path(knapp).suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return knapp


def _collect_uploads(daten: Any, gefunden: set[str]) -> None:
    """Sammelt alle Dateinamen, auf die eine Struktur verweist.

    Läuft über die ausgepackte JSON-Struktur statt über die Modellklassen:
    Bilder stecken an vielen Stellen — im Symbol je Zustand, im Hintergrund
    einer Taste, im Streifenbild einer Seite, in den Schritten einer
    Multi-Aktion. Wer sie einzeln aufzählt, vergisst beim nächsten neuen Feld
    genau eines. Gesucht wird deshalb nach dem Muster, nicht nach dem Ort:
    ein Feld ``upload`` oder ein Wert der Form ``upload:<datei>``.
    """
    if isinstance(daten, dict):
        for schluessel, wert in daten.items():
            if schluessel == "upload" and isinstance(wert, str) and wert:
                gefunden.add(Path(wert).name)
            else:
                _collect_uploads(wert, gefunden)
    elif isinstance(daten, list):
        for eintrag in daten:
            _collect_uploads(eintrag, gefunden)
    elif isinstance(daten, str) and daten.startswith("upload:"):
        rest = daten.split(":", 1)[1]
        if rest:
            gefunden.add(Path(rest).name)


def _manifest(kind: str, **extra: Any) -> bytes:
    from .. import __version__

    return json.dumps(
        {
            "kind": kind,
            "format": FORMAT_VERSION,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "app_version": __version__,
            **extra,
        },
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")


def _read_manifest(zf: zipfile.ZipFile, erwartet: str) -> dict[str, Any]:
    try:
        roh = zf.read("manifest.json")
    except KeyError as exc:
        raise BackupError("Kein Manifest im Paket — das ist keine Sicherung.") from exc
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError as exc:
        raise BackupError(f"Manifest unlesbar: {exc}") from exc
    if daten.get("kind") != erwartet:
        raise BackupError(
            f"Falsche Art von Paket: erwartet '{erwartet}', gefunden "
            f"'{daten.get('kind')}'."
        )
    if int(daten.get("format", 0)) > FORMAT_VERSION:
        raise BackupError(
            "Das Paket stammt aus einer neueren Fassung und lässt sich hier "
            "nicht einspielen."
        )
    return daten


def _unpack_images(zf: zipfile.ZipFile, praefix: str, ziel: Path) -> int:
    """Packt Bilder eines Ordners aus. Gibt zurück, wie viele es waren."""
    ziel.mkdir(parents=True, exist_ok=True)
    gesamt = 0
    anzahl = 0
    for eintrag in zf.infolist():
        if eintrag.is_dir() or not eintrag.filename.startswith(f"{praefix}/"):
            continue
        name = _safe_name(eintrag.filename)
        if name is None:
            log.warning("Übergehe Eintrag im Paket: %s", eintrag.filename)
            continue
        gesamt += eintrag.file_size
        if gesamt > MAX_UNPACKED_BYTES:
            raise BackupError("Das Paket entpackt sich zu größer als erlaubt.")
        with zf.open(eintrag) as quelle, (ziel / name).open("wb") as datei:
            shutil.copyfileobj(quelle, datei)
        anzahl += 1
    return anzahl


# --------------------------------------------------------- Sicherungspaket


def make_archive(store: ConfigStore) -> bytes:
    """Schnürt Konfiguration und eigene Bilder zu einem Paket."""
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as zf:
        bilder = 0
        for ordnername, ordner in BUNDLED_DIRS.items():
            if not ordner.is_dir():
                continue
            for datei in sorted(ordner.iterdir()):
                if datei.is_file() and datei.suffix.lower() in IMAGE_SUFFIXES:
                    zf.write(datei, f"{ordnername}/{datei.name}")
                    bilder += 1
        zf.writestr("config.json", store.export_json())
        zf.writestr("manifest.json", _manifest(ARCHIVE_KIND, images=bilder))
    return puffer.getvalue()


def restore_archive(daten: bytes, store: ConfigStore) -> Config:
    """Spielt ein Paket zurück.

    Zuerst wird geprüft und erst dann geschrieben: Eine Sicherung, die auf
    halbem Weg abbricht, wäre schlimmer als gar keine.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile as exc:
        raise BackupError("Das ist keine lesbare ZIP-Datei.") from exc

    with zf:
        _read_manifest(zf, ARCHIVE_KIND)
        try:
            roh = zf.read("config.json").decode("utf-8")
        except KeyError as exc:
            raise BackupError("Im Paket fehlt die Konfiguration.") from exc

        # Erst validieren, dann anfassen.
        try:
            Config.model_validate(json.loads(roh))
        except (json.JSONDecodeError, ValueError) as exc:
            raise BackupError(f"Die Konfiguration im Paket ist ungültig: {exc}") from exc

        for ordnername, ziel in BUNDLED_DIRS.items():
            _unpack_images(zf, ordnername, ziel)

        # ``import_json`` legt über den Store den bisherigen Stand beiseite,
        # bevor er überschrieben wird — die Zeitreise unten führt also auch
        # hinter eine Wiederherstellung zurück.
        return store.import_json(roh)


# ------------------------------------------------------------- Zeitreise


@dataclass(slots=True)
class Snapshot:
    """Ein automatisch abgelegter Stand der Konfiguration."""

    name: str
    saved_at: float
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "saved_at": self.saved_at,
            "size": self.size,
        }


def snapshots() -> list[Snapshot]:
    """Die vorhandenen Stände, jüngster zuerst."""
    ordner = paths.BACKUP_DIR
    if not ordner.is_dir():
        return []
    gefunden = []
    for datei in ordner.glob("config-*.json"):
        try:
            info = datei.stat()
        except OSError:
            continue
        gefunden.append(Snapshot(datei.name, info.st_mtime, info.st_size))
    return sorted(gefunden, key=lambda s: s.saved_at, reverse=True)


def restore_snapshot(name: str, store: ConfigStore) -> Config:
    """Spielt einen der automatischen Stände zurück."""
    knapp = Path(name).name
    if knapp != name or not knapp.startswith("config-") or not knapp.endswith(".json"):
        raise BackupError("Unbekannter Stand.")
    datei = paths.BACKUP_DIR / knapp
    if not datei.is_file():
        raise BackupError("Diesen Stand gibt es nicht (mehr).")

    roh = datei.read_text(encoding="utf-8")
    try:
        Config.model_validate(json.loads(roh))
    except (json.JSONDecodeError, ValueError) as exc:
        raise BackupError(f"Der Stand ist beschädigt: {exc}") from exc
    return store.import_json(roh)


# ----------------------------------------------------------- Profilpaket


def export_profile(store: ConfigStore, profile_id: str) -> bytes:
    """Packt ein einzelnes Profil samt der darin verwendeten Bilder."""
    profil = store.config.profiles.get(profile_id)
    if profil is None:
        raise BackupError("Dieses Profil gibt es nicht.")

    daten = profil.model_dump(mode="json")
    referenziert: set[str] = set()
    _collect_uploads(daten, referenziert)

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as zf:
        mitgenommen = 0
        for name in sorted(referenziert):
            for ordnername, ordner in BUNDLED_DIRS.items():
                quelle = ordner / name
                if quelle.is_file():
                    zf.write(quelle, f"{ordnername}/{name}")
                    mitgenommen += 1
                    break
        zf.writestr(
            "profile.json", json.dumps(daten, indent=2, ensure_ascii=False)
        )
        zf.writestr(
            "manifest.json",
            _manifest(PROFILE_KIND, name=profil.name, images=mitgenommen),
        )
    return puffer.getvalue()


def import_profile(daten: bytes, store: ConfigStore) -> Profile:
    """Fügt ein Profilpaket hinzu — als zusätzliches Profil, nie ersetzend.

    Ein importiertes Profil bekommt eine neue Kennung und, falls der Name
    schon vergeben ist, eine Nummer dahinter. Wer ein Profil weitergibt,
    soll beim Empfänger nichts überschreiben.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile as exc:
        raise BackupError("Das ist keine lesbare ZIP-Datei.") from exc

    with zf:
        _read_manifest(zf, PROFILE_KIND)
        try:
            roh = zf.read("profile.json").decode("utf-8")
        except KeyError as exc:
            raise BackupError("Im Paket fehlt das Profil.") from exc

        try:
            profil = Profile.model_validate(json.loads(roh))
        except (json.JSONDecodeError, ValueError) as exc:
            raise BackupError(f"Das Profil im Paket ist ungültig: {exc}") from exc

        for ordnername, ziel in BUNDLED_DIRS.items():
            _unpack_images(zf, ordnername, ziel)

    # Neue Kennung, damit ein zweiter Import daneben landet statt darüber.
    profil.id = type(profil)().id
    vergeben = {p.name for p in store.config.profiles.values()}
    if profil.name in vergeben:
        nummer = 2
        while f"{profil.name} ({nummer})" in vergeben:
            nummer += 1
        profil.name = f"{profil.name} ({nummer})"

    store.config.profiles[profil.id] = profil
    store.save()
    return profil
