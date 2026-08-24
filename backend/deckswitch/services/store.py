"""Der Store aus Sicht der App.

Vier Dinge: stöbern, installieren, anmelden, hochladen. Alles blockierend
— der Aufrufer führt es im Executor aus, wie beim Installer auch.

**Was hier nicht geschieht: vertrauen.** Der Store nennt zu jeder Fassung
eine Prüfsumme; installiert wird nur, was ihr entspricht. Das schützt
nicht davor, dass der Store selbst Unfug ausliefert — aber davor, dass
jemand auf dem Weg dazwischen etwas austauscht. Und die Funde der
Durchsicht wandern mit, damit die Oberfläche warnen kann, bevor jemand
klickt.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..plugins import installer

log = logging.getLogger(__name__)

#: Wo der Store steht. Über die Umgebung umstellbar — sonst ließe sich
#: gegen eine Testinstanz nicht arbeiten, ohne den Quelltext zu ändern.
STORE_URL = os.environ.get("DECKSWITCH_STORE_URL", "https://streamdeckstore.labratox.de")

#: Wie lange eine Katalogantwort wiederverwendet wird. Kurz genug, dass
#: eine neue Fassung schnell auftaucht; lang genug, dass das Blättern in
#: der Oberfläche nicht bei jedem Klick ins Netz greift.
CACHE_SEKUNDEN = 300

ZEITLIMIT_S = 20

#: Das Anmeldetoken. Nicht in der config.json: Die lässt sich exportieren
#: und weitergeben, und ein Token darin wäre nach dem ersten „schick mir
#: mal deine Einstellungen" unterwegs.
TOKEN_DATEI: Path = paths.CONFIG_DIR / "store-token"


class StoreError(RuntimeError):
    """Der Store hat nicht das getan, was er sollte."""


@dataclass(slots=True)
class _Zwischenspeicher:
    daten: dict[str, tuple[float, Any]] = field(default_factory=dict)

    def hol(self, schluessel: str) -> Any | None:
        eintrag = self.daten.get(schluessel)
        if eintrag is None or time.monotonic() - eintrag[0] > CACHE_SEKUNDEN:
            return None
        return eintrag[1]

    def leg_ab(self, schluessel: str, wert: Any) -> None:
        self.daten[schluessel] = (time.monotonic(), wert)

    def leere(self) -> None:
        self.daten.clear()


_cache = _Zwischenspeicher()


# --------------------------------------------------------------------------
# Der Weg ins Netz
# --------------------------------------------------------------------------


def _url(pfad: str, **abfrage: Any) -> str:
    basis = STORE_URL.rstrip("/")
    frage = {k: v for k, v in abfrage.items() if v not in ("", None)}
    return f"{basis}{pfad}" + (f"?{urllib.parse.urlencode(frage)}" if frage else "")


def _anfrage(
    pfad: str,
    *,
    methode: str = "GET",
    rumpf: bytes | None = None,
    typ: str = "",
    mit_token: bool = False,
    token_falls_da: bool = False,
    **abfrage: Any,
) -> Any:
    """Eine Anfrage an den Store — Antwort als JSON.

    ``mit_token`` verlangt eine Anmeldung, ``token_falls_da`` schickt sie
    nur mit, wenn es eine gibt: Die Bewertung eines Plugins darf jeder
    lesen, aber wer angemeldet ist, soll dabei auch die eigene Stimme
    zurückbekommen.
    """
    kopf = {"Accept": "application/json", "User-Agent": "DeckSwitch/1.0"}
    if typ:
        kopf["Content-Type"] = typ
    if mit_token:
        token = lies_token()
        if not token:
            raise StoreError("Dafür musst du im Store angemeldet sein")
        kopf["Authorization"] = f"Bearer {token}"
    elif token_falls_da:
        token = lies_token()
        if token:
            kopf["Authorization"] = f"Bearer {token}"

    anfrage = urllib.request.Request(
        _url(pfad, **abfrage), data=rumpf, headers=kopf, method=methode
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
            roh = antwort.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise StoreError(_fehlertext(exc)) from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"Der Store ist nicht erreichbar: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise StoreError(f"Verbindung abgebrochen: {exc}") from exc

    if not roh:
        return None
    try:
        return json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError("Der Store hat etwas Unlesbares geschickt") from exc


def _fehlertext(exc: urllib.error.HTTPError) -> str:
    """Die Begründung des Stores, wenn er eine mitschickt.

    Die Texte dort sind für Menschen geschrieben („Version 1.0.0 gibt es
    schon") — eine Zahl allein wäre eine verschenkte Auskunft.
    """
    try:
        daten = json.loads(exc.read(64 * 1024).decode("utf-8"))
        grund = daten.get("detail") or daten.get("message")
        if isinstance(grund, str) and grund:
            return grund
    except Exception:  # noqa: BLE001 — der Fehlertext ist nur ein Zubrot
        pass
    if exc.code == 401:
        return "Nicht angemeldet"
    if exc.code == 403:
        return "Dafür fehlen die Rechte"
    return f"Der Store antwortet mit {exc.code}"


# --------------------------------------------------------------------------
# Stöbern
# --------------------------------------------------------------------------


def katalog(*, kind: str = "", q: str = "") -> dict[str, Any]:
    schluessel = f"katalog:{kind}:{q}"
    zwischen = _cache.hol(schluessel)
    if zwischen is not None:
        return zwischen
    daten = _anfrage("/api/catalog", kind=kind, q=q)
    _cache.leg_ab(schluessel, daten)
    return daten


def plugin(slug: str) -> dict[str, Any]:
    schluessel = f"plugin:{slug}"
    zwischen = _cache.hol(schluessel)
    if zwischen is not None:
        return zwischen
    daten = _anfrage(f"/api/catalog/{urllib.parse.quote(slug)}")
    _cache.leg_ab(schluessel, daten)
    return daten


def beliebt(*, kind: str = "") -> dict[str, Any]:
    return _anfrage("/api/popular", kind=kind)


# --------------------------------------------------------------------------
# Bewertungen
# --------------------------------------------------------------------------
#
# Nicht zwischengespeichert: Wer gerade auf „Daumen hoch" gedrückt hat, will
# das sofort sehen und nicht in fünf Minuten. Es ist eine kleine Antwort und
# sie wird nur beim Öffnen einer Detailansicht geholt.


def bewertung(slug: str) -> dict[str, Any]:
    """Stimmen, die eigene Stimme und die letzten Kommentare."""
    return _anfrage(
        f"/api/catalog/{urllib.parse.quote(slug)}/rating", token_falls_da=True
    )


def bewerte(slug: str, wert: int, kommentar: str = "") -> dict[str, Any]:
    """Daumen hoch (``1``) oder runter (``-1``), auf Wunsch mit einem Satz."""
    if wert not in (1, -1):
        raise StoreError("Eine Bewertung ist entweder 1 oder -1")
    rumpf = json.dumps({"value": wert, "comment": kommentar}).encode("utf-8")
    daten = _anfrage(
        f"/api/catalog/{urllib.parse.quote(slug)}/rating",
        methode="PUT", rumpf=rumpf, typ="application/json", mit_token=True,
    )
    # Im Katalog stehen dieselben Zahlen — der Zwischenspeicher wüsste sonst
    # noch die alten.
    vergiss()
    return daten


def bewertung_zuruecknehmen(slug: str) -> dict[str, Any]:
    daten = _anfrage(
        f"/api/catalog/{urllib.parse.quote(slug)}/rating",
        methode="DELETE", mit_token=True,
    )
    vergiss()
    return daten


def vergiss() -> None:
    """Den Zwischenspeicher leeren — nach einer Installation etwa."""
    _cache.leere()
    _bilder.clear()


# --------------------------------------------------------------------------
# Bilder
# --------------------------------------------------------------------------

#: Wie groß ein Symbol oder Screenshot höchstens sein darf. Dieselbe Grenze
#: wie im Store — was er nicht ausliefert, muss hier auch nicht ankommen.
MAX_BILD_BYTES = 4 * 1024 * 1024

#: Bildtypen, die die Oberfläche anzeigt. SVG steht bewusst nicht dabei: Es
#: ist ein Dokument, darf Skript enthalten, und das liefe im Ursprung der GUI.
BILDTYPEN = {"image/png", "image/jpeg", "image/gif", "image/webp"}

#: Schon geholte Bilder, nach Adresse. Ein Symbol wandert bei jedem Blick in
#: die Liste über den Bildschirm; jedes Mal ins Netz zu greifen wäre eine
#: Runde zu viel. Der Speicher ist klein und lebt nur, solange die App läuft.
_bilder: dict[str, tuple[bytes, str]] = {}

#: Mehr als so viele Bilder behält der Speicher nicht.
_BILDER_MAX = 200


def bild(slug: str, version: str, art: str, index: int = 0) -> tuple[bytes, str]:
    """Symbol oder Screenshot einer Fassung — Bytes und Inhaltstyp.

    Die Adresse kommt aus dem Katalog und wird nicht hier zusammengesetzt.
    Das ist keine Bequemlichkeit, sondern die Schranke: Geholt wird nur, was
    der Store selbst als Bild dieser Fassung genannt hat, und nur von *ihm*
    — eine Adresse anderswohin lehnt diese Funktion ab, auch wenn sie im
    Katalog stünde.
    """
    daten = plugin(slug)
    fassungen = [*daten.get("versions", []), daten.get("latest")]
    passend = next((v for v in fassungen if v and v.get("version") == version), None)
    if passend is None:
        raise StoreError(f"Fassung {version} steht nicht im Katalog")

    if art == "icon":
        adresse = passend.get("icon_url")
    else:
        bilder = passend.get("screenshot_urls") or []
        adresse = bilder[index] if 0 <= index < len(bilder) else None
    if not adresse:
        raise StoreError("Dafür nennt der Katalog kein Bild")

    return _hol_bild(adresse)


def _hol_bild(adresse: str) -> tuple[bytes, str]:
    zwischen = _bilder.get(adresse)
    if zwischen is not None:
        return zwischen

    if not adresse.startswith(STORE_URL.rstrip("/") + "/"):
        raise StoreError("Diese Bildadresse zeigt nicht auf den Store")

    anfrage = urllib.request.Request(
        adresse, headers={"Accept": "image/*", "User-Agent": "DeckSwitch/1.0"}
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
            typ = (antwort.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            roh = antwort.read(MAX_BILD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise StoreError(_fehlertext(exc)) from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"Der Store ist nicht erreichbar: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise StoreError(f"Verbindung abgebrochen: {exc}") from exc

    if typ not in BILDTYPEN:
        raise StoreError(f"Der Store hat kein Bild geschickt, sondern {typ or 'nichts Erkennbares'}")
    if len(roh) > MAX_BILD_BYTES:
        raise StoreError("Das Bild ist zu groß")

    if len(_bilder) >= _BILDER_MAX:
        _bilder.clear()
    _bilder[adresse] = (roh, typ)
    return roh, typ


# --------------------------------------------------------------------------
# Installieren
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Versionen vergleichen
# --------------------------------------------------------------------------


def als_zahlen(version: str) -> tuple[int, ...]:
    """``"1.10.2"`` → ``(1, 10, 2)`` — zum Vergleichen, nicht zum Anzeigen.

    Zeichenweise verglichen wäre ``1.10`` kleiner als ``1.9``, und genau
    dieser Fehler fällt erst auf, wenn die zehnte Fassung erscheint. Was
    keine Zahl ist, zählt als 0: ``1.0.0-beta`` ist damit dasselbe wie
    ``1.0.0``, und das ist die richtige Vorsicht — niemand soll aus Versehen
    von einer Fassung auf eine Vorabfassung „aktualisiert" werden.
    """
    teile: list[int] = []
    for stueck in str(version or "").split("."):
        ziffern = ""
        for zeichen in stueck:
            if not zeichen.isdigit():
                break
            ziffern += zeichen
        teile.append(int(ziffern) if ziffern else 0)
    return tuple(teile) or (0,)


def neuer_als(kandidat: str, vorhanden: str) -> bool:
    """Ist ``kandidat`` eine spätere Fassung als ``vorhanden``?"""
    a, b = als_zahlen(kandidat), als_zahlen(vorhanden)
    # Unterschiedlich viele Stellen auffüllen: 1.1 und 1.1.0 sind dasselbe.
    laenge = max(len(a), len(b))
    a += (0,) * (laenge - len(a))
    b += (0,) * (laenge - len(b))
    return a > b


def _passt_zur_app(mindestens: str | None) -> bool:
    """Läuft eine Fassung mit dieser App — oder verlangt sie eine neuere?"""
    if not mindestens:
        return True
    from .. import __version__

    return not neuer_als(mindestens, __version__)


def verfuegbare_updates(installiert: dict[str, str]) -> list[dict[str, Any]]:
    """Was von den installierten Plugins im Store neuer vorliegt.

    ``installiert`` ist ``{slug: version}``. Zurück kommt je Plugin ein
    Eintrag mit alter und neuer Nummer — und was sich geändert hat, damit
    die Oberfläche das zeigen kann, ohne noch einmal zu fragen.

    Nicht angeboten wird, was diese App nicht ausführen kann: Ein Plugin,
    das eine neuere Fassung von DECK//SWITCH verlangt, wäre nach dem
    „Aktualisieren" kaputt statt neu.
    """
    if not installiert:
        return []

    eintraege = katalog().get("plugins", [])
    updates: list[dict[str, Any]] = []
    for eintrag in eintraege:
        slug = str(eintrag.get("slug") or "")
        habe = installiert.get(slug)
        if habe is None:
            continue
        neueste = eintrag.get("latest") or {}
        dort = str(neueste.get("version") or "")
        if not dort or not neuer_als(dort, habe):
            continue
        updates.append({
            "slug": slug,
            "name": eintrag.get("name") or slug,
            "installed": habe,
            "available": dort,
            "changelog": neueste.get("changelog"),
            "size": neueste.get("size"),
            "released_at": neueste.get("released_at"),
            "min_app_version": neueste.get("min_app_version"),
            "usable": _passt_zur_app(neueste.get("min_app_version")),
        })
    return sorted(updates, key=lambda u: str(u["slug"]))


def _neueste(daten: dict[str, Any]) -> dict[str, Any] | None:
    """Die neueste Fassung, die noch im Katalog steht.

    Zurückgezogene stehen mit in der Liste — herunterladen darf man sie,
    *vorschlagen* soll sie niemand mehr.
    """
    fassungen = [v for v in daten.get("versions", []) if v.get("state") == "approved"]
    return fassungen[0] if fassungen else None


def installiere(slug: str, version: str = "") -> dict[str, Any]:
    """Installiert ein Plugin aus dem Store.

    Ohne ``version`` die neueste freigegebene. Die Prüfsumme kommt aus dem
    Katalog und muss stimmen — sonst wird nichts ausgepackt.
    """
    daten = plugin(slug)
    fassungen = daten.get("versions", [])
    if version:
        gesucht = next((v for v in fassungen if v.get("version") == version), None)
    else:
        gesucht = _neueste(daten)
    if gesucht is None:
        raise StoreError(
            f"Für '{slug}' gibt es keine Fassung {version or 'zum Installieren'}"
        )

    summe = str(gesucht.get("sha256") or "")
    if not summe:
        # Der Store nennt zu jeder Fassung eine Summe. Fehlt sie, stimmt
        # etwas nicht — und ungeprüft wird nichts ausgepackt.
        raise StoreError("Der Store nennt keine Prüfsumme — es wird nichts installiert")

    # Die Adresse kommt aus dem Katalog: Ändert der Store seinen Weg,
    # ändert er ihn dort. Nur wenn er keine nennt, wird sie hier gebaut.
    adresse = str(gesucht.get("download_url") or "")
    if adresse:
        trenner = "&" if "?" in adresse else "?"
        adresse = f"{adresse}{trenner}via=app"
    else:
        adresse = _url(
            f"/api/download/{urllib.parse.quote(slug)}/"
            f"{urllib.parse.quote(gesucht['version'])}",
            via="app",
        )
    manifest = installer.install_url(adresse, sha256=summe)
    vergiss()

    return {
        "plugin_id": manifest.id,
        "name": manifest.name,
        "version": gesucht["version"],
        "sha256": summe,
        # Was die Durchsicht gefunden hat, reicht die Oberfläche weiter:
        # Installiert ist installiert — gewusst haben soll man es vorher.
        "warnings": gesucht.get("warnings", []),
    }


# --------------------------------------------------------------------------
# Anmelden
# --------------------------------------------------------------------------


def lies_token() -> str:
    try:
        return TOKEN_DATEI.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def schreib_token(token: str) -> None:
    TOKEN_DATEI.parent.mkdir(parents=True, exist_ok=True)
    if not token:
        TOKEN_DATEI.unlink(missing_ok=True)
        return
    # Erst anlegen, dann die Rechte setzen, dann schreiben: Zwischen einem
    # ``write_text`` und einem späteren ``chmod`` läge ein Moment, in dem
    # die Datei für alle lesbar ist.
    TOKEN_DATEI.touch(mode=0o600, exist_ok=True)
    TOKEN_DATEI.chmod(0o600)
    TOKEN_DATEI.write_text(token, encoding="utf-8")


def anmeldung_starten() -> dict[str, Any]:
    """Holt den Code, den der Benutzer auf github.com eintippt."""
    return _anfrage("/api/auth/device", methode="POST")


def anmeldung_nachfragen(device_code: str) -> dict[str, Any]:
    """Fragt einmal nach. Bei Erfolg wird das Token abgelegt.

    Drei mögliche Stände: ``ok``, ``pending`` und ``slow_down``. Der letzte
    heißt *nicht* „noch nicht bestätigt", sondern „du fragst zu oft" — und
    wer daraufhin im gleichen Takt weiterfragt, bekommt bis zum Ablauf des
    Codes dieselbe Antwort. Die Oberfläche muss ihren Abstand vergrößern,
    deshalb kommt ``backoff`` mit zurück.
    """
    antwort = _anfrage(
        "/api/auth/device/poll",
        methode="POST",
        rumpf=json.dumps({"device_code": device_code}).encode(),
        typ="application/json",
    )
    stand = antwort.get("status", "pending")
    if stand == "ok":
        schreib_token(antwort["token"])
        return {"status": "ok", "user": antwort.get("user")}
    if stand == "slow_down":
        return {"status": "slow_down", "backoff": int(antwort.get("backoff", 5))}
    return {"status": stand}


def wer_bin_ich() -> dict[str, Any] | None:
    """Wer angemeldet ist — oder ``None``.

    Ein Token, das der Store nicht mehr kennt, wird gelöscht: Sonst zeigte
    die Oberfläche dauerhaft einen Namen an, unter dem nichts mehr geht.
    """
    if not lies_token():
        return None
    try:
        return _anfrage("/api/auth/me", mit_token=True)
    except StoreError as exc:
        if "angemeldet" in str(exc).lower():
            schreib_token("")
            return None
        raise


def offene_pruefungen() -> dict[str, Any] | None:
    """Was auf Prüfung wartet — nur für Moderatoren.

    ``None``, wenn der Angemeldete nicht prüfen darf oder niemand angemeldet
    ist. Das ist kein Fehler, sondern der Normalfall: Die allermeisten
    Benutzer prüfen nichts.
    """
    if not lies_token():
        return None
    try:
        return _anfrage("/api/review/pending", mit_token=True)
    except StoreError as exc:
        text = str(exc).lower()
        if "recht" in text or "angemeldet" in text:
            return None
        raise


def abmelden() -> None:
    if lies_token():
        try:
            _anfrage("/api/auth/logout", methode="POST", mit_token=True)
        except StoreError as exc:
            # Die Sitzung serverseitig zu beenden wäre schöner, ist aber
            # nicht nötig: Ohne das Token hier kommt niemand mehr hinein.
            log.info("Abmelden beim Store fehlgeschlagen: %s", exc)
    schreib_token("")


# --------------------------------------------------------------------------
# Hochladen
# --------------------------------------------------------------------------


def name_pruefen(slug: str) -> dict[str, Any]:
    """Ob eine Kennung zu haben ist — vor dem Hochladen zu fragen."""
    return _anfrage(f"/api/slugs/{urllib.parse.quote(slug)}")


def hochladen(daten: bytes, *, dateiname: str = "plugin.zip") -> dict[str, Any]:
    """Reicht ein Archiv beim Store ein."""
    if len(daten) > installer.MAX_ARCHIVE_BYTES:
        raise StoreError("Das Archiv ist zu groß (max. 64 MB)")

    grenze = "----DeckSwitch" + os.urandom(16).hex()
    rumpf = b"".join(
        [
            f"--{grenze}\r\n".encode(),
            b'Content-Disposition: form-data; name="datei"; filename="',
            dateiname.replace('"', "").encode("utf-8"),
            b'"\r\nContent-Type: application/zip\r\n\r\n',
            daten,
            f"\r\n--{grenze}--\r\n".encode(),
        ]
    )
    antwort = _anfrage(
        "/api/plugins",
        methode="POST",
        rumpf=rumpf,
        typ=f"multipart/form-data; boundary={grenze}",
        mit_token=True,
    )
    vergiss()
    return antwort


def meine_plugins() -> dict[str, Any]:
    return _anfrage("/api/me/plugins", mit_token=True)


def zuruecknehmen(slug: str, version: str) -> dict[str, Any]:
    """Nimmt eine eigene Einreichung wieder zurück.

    Was daraus wird, entscheidet der Store und nicht die App: Eine Fassung,
    die noch niemand bekommen hat, verschwindet; eine ausgelieferte fällt nur
    aus dem Katalog. Die Antwort sagt in ``aktion``, welcher Fall es war.
    """
    return _anfrage(
        f"/api/me/plugins/{urllib.parse.quote(slug, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}",
        methode="DELETE",
        mit_token=True,
    )


def packe(ordner: Path) -> bytes:
    """Packt einen Plugin-Ordner so, wie der Store ihn erwartet.

    Der Ordnername wird zur obersten Ebene im Archiv — beide Formen liest
    der Store, aber so sieht ein Mensch beim Hineinschauen sofort, worum
    es geht.
    """
    import io
    import zipfile

    ordner = ordner.resolve()
    if not (ordner / "manifest.json").is_file():
        raise StoreError(f"In {ordner.name} liegt keine manifest.json")

    #: Was nicht mitgehört: Übersetzungsreste, Editorkram, Versionsverlauf.
    UEBERGEHEN = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache", "node_modules"}

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        for pfad in sorted(ordner.rglob("*")):
            if not pfad.is_file() or pfad.is_symlink():
                continue
            relativ = pfad.relative_to(ordner)
            if any(teil in UEBERGEHEN for teil in relativ.parts):
                continue
            if relativ.suffix in (".pyc", ".pyo"):
                continue
            z.write(pfad, f"{ordner.name}/{relativ.as_posix()}")
    return puffer.getvalue()
