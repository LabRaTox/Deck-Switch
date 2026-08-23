"""Plugins für das Elgato Stream Deck hier laufen lassen.

Elgato-Plugins sind eigene Programme. Die Stream-Deck-Software startet sie
mit ein paar Argumenten, sie verbinden sich per WebSocket zurück und reden
danach in JSON: Die Software schickt Ereignisse (``keyDown``, ``dialRotate``),
das Plugin schickt Anweisungen (``setImage``, ``setTitle``). Das Protokoll ist
dokumentiert und stabil — genau deshalb lässt es sich nachbauen.

Diese Datei ist die Gegenstelle. Sie tut dreierlei:

1. **Einlesen.** Ein ``.streamDeckPlugin`` ist ein ZIP mit einem Ordner
   ``<uuid>.sdPlugin``. Daraus wird ein ganz gewöhnliches Plugin für uns:
   übersetztes Manifest, der Elgato-Ordner unverändert daneben.
2. **Starten.** Node-Plugins über ``node``. Für Windows-Binärdateien und
   HTML-Plugins ist die Stelle vorbereitet, aber noch nicht belegt — der
   Startbefehl ist der einzige Unterschied, alles danach ist dasselbe.
3. **Übersetzen.** Unsere Hooks werden zu ihren Ereignissen, ihre Anweisungen
   zu Bildern auf unseren Tasten.

**Was hier bewusst nicht passiert: vertrauen.** Ein Elgato-Plugin ist fremder
Programmcode, der mit den Rechten des Benutzers läuft — wie jedes unserer
eigenen Plugins auch. Der Prozess bekommt aber keinen Zugriff auf unsere
Konfiguration, sondern nur die Einstellungen seiner eigenen Belegungen.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import logging
import mimetypes
import os
import shutil
import signal
import tempfile
import zipfile
from urllib.parse import unquote
from pathlib import Path
from typing import Any

from PIL import Image
from websockets.datastructures import Headers

from .base import ActionPlugin, SlotContext, localize

log = logging.getLogger(__name__)

#: Endung, an der ein Elgato-Archiv zu erkennen ist.
ARCHIV_ENDUNG = ".streamdeckplugin"

#: Der Ordner, in dem das fremde Plugin unverändert liegt.
UNTERORDNER = "sdPlugin"

#: Bildendungen, die Elgato-Manifeste weglassen dürfen. Dort steht
#: ``"Icon": "imgs/pluginIcon"``, die Datei heißt ``imgs/pluginIcon.png``
#: oder ``imgs/pluginIcon@2x.png``.
BILDENDUNGEN = (".png", ".svg", ".jpg", ".jpeg", ".gif")

#: Farbe für Kacheln eines eingelesenen Plugins. Elgato-Manifeste kennen
#: keine Akzentfarbe, und eine geratene wäre eine Behauptung.
AKZENT = "#6b7280"

#: Wie lange eine Rückmeldung (``showOk``/``showAlert``) stehen bleibt.
MELDUNG_S = 1.5


#: Der Koordinatenraum, in dem Elgato-Layouts beschrieben sind: ein
#: Dial-Segment des Stream Deck+ mit 200×100 Pixeln. Unsere Segmente haben
#: dieselbe Größe; ein virtuelles Deck darf abweichen, dann wird skaliert.
LAYOUT_RAUM = (200, 100)


class ElgatoError(RuntimeError):
    """Das Archiv ist keines, das sich einlesen lässt."""


# --------------------------------------------------------------------------
# Einlesen und übersetzen
# --------------------------------------------------------------------------


def ist_elgato_archiv(daten: bytes, dateiname: str = "") -> bool:
    """Ob dieses Archiv ein Elgato-Plugin ist.

    Entschieden wird am Inhalt und nicht am Dateinamen: Wer ein
    ``.streamDeckPlugin`` in ``.zip`` umbenennt, meint trotzdem dasselbe.
    """
    if dateiname.lower().endswith(ARCHIV_ENDUNG):
        return True
    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
            return _sdplugin_wurzel(archiv.namelist()) is not None
    except zipfile.BadZipFile:
        return False


def _sdplugin_wurzel(namen: list[str]) -> str | None:
    """Der Ordner ``<uuid>.sdPlugin`` im Archiv — oder ``None``."""
    for name in namen:
        teile = name.split("/")
        if len(teile) >= 2 and teile[0].endswith(".sdPlugin") and teile[1] == "manifest.json":
            return teile[0]
    return None


def _bildpfad(ordner: Path, angabe: str | None) -> str | None:
    """Löst eine Elgato-Bildangabe zu einer wirklich vorhandenen Datei auf.

    Elgato lässt die Endung weg und liefert zusätzlich eine ``@2x``-Fassung.
    Bevorzugt wird die große: Unsere Tasten sind 120 Pixel breit, die
    einfache Fassung hat 72.
    """
    if not angabe:
        return None
    angabe = angabe.replace("\\", "/").lstrip("/")
    kandidaten = [f"{angabe}@2x{e}" for e in BILDENDUNGEN]
    kandidaten += [f"{angabe}{e}" for e in BILDENDUNGEN]
    kandidaten.append(angabe)
    for kandidat in kandidaten:
        ziel = ordner / kandidat
        if ziel.is_file() and ordner.resolve() in ziel.resolve().parents:
            return kandidat
    return None


def _datei(ordner: Path, angabe: str | None) -> str | None:
    """Prüft einen Pfad aus dem fremden Manifest gegen den Plugin-Ordner."""
    if not angabe:
        return None
    pfad = angabe.replace("\\", "/").lstrip("/")
    ziel = ordner / pfad
    if ziel.is_file() and ordner.resolve() in ziel.resolve().parents:
        return pfad
    return None


def _eingaben(aktion: dict[str, Any]) -> list[str]:
    """``Controllers`` übersetzen. Fehlt die Angabe, ist es eine Taste."""
    steuerung = aktion.get("Controllers") or ["Keypad"]
    eingaben = []
    if "Keypad" in steuerung:
        eingaben.append("key")
    if "Encoder" in steuerung:
        eingaben.append("dial")
    return eingaben or ["key"]


def uebersetze_manifest(
    elgato: dict[str, Any], ordner: Path, kennung: str = ""
) -> dict[str, Any]:
    """Aus einem Elgato-Manifest eines in unserem Format.

    Übernommen wird nur, was beide Seiten kennen. Alles Elgato-Eigene
    (``CodePath``, ``Encoder``-Layouts, Property Inspector) bleibt im
    Originalmanifest, das daneben liegen bleibt — es hier hineinzufalten
    hieße, es zweimal zu pflegen.
    """
    # Ältere Manifeste (SDK 2) nennen keine UUID — dort ist der Ordnername
    # die Kennung: ``com.elgato.analogclock.sdPlugin``. Beides kommt vor.
    kennung = str(elgato.get("UUID") or "").strip() or kennung.strip()
    if not kennung:
        raise ElgatoError("Weder UUID im Manifest noch Kennung im Ordnernamen")

    aktionen = []
    for eintrag in elgato.get("Actions") or []:
        uuid = str(eintrag.get("UUID") or "").strip()
        if not uuid:
            continue
        zustaende = eintrag.get("States") or [{}]
        # Die Einstellungsseite steht an der Aktion oder — als Vorgabe für
        # alle — am Plugin. Was es nicht gibt, wird auch nicht eingetragen:
        # Die GUI entscheidet daran, ob sie überhaupt einen Rahmen zeigt.
        seite = eintrag.get("PropertyInspectorPath") or elgato.get("PropertyInspectorPath")
        seite = _datei(ordner, seite)
        aktionen.append({
            "id": uuid,
            "property_inspector": seite,
            "name": eintrag.get("Name") or uuid.rsplit(".", 1)[-1],
            "description": eintrag.get("Tooltip") or "",
            "inputs": _eingaben(eintrag),
            # Die Zustände heißen bei Elgato nicht, sie sind durchnummeriert.
            # Das Bild dazu liefert das Plugin zur Laufzeit; steht dort
            # nichts, greifen wir auf das Manifestbild zurück.
            "states": [
                {"id": str(i), "name": zustand.get("Name") or f"Zustand {i}"}
                for i, zustand in enumerate(zustaende)
            ] if len(zustaende) > 1 else [],
        })

    return {
        "id": kennung,
        "name": elgato.get("Name") or kennung,
        "version": str(elgato.get("Version") or "0.0.0"),
        "type": "action",
        "author": elgato.get("Author") or "",
        "category": "other",
        "accent": AKZENT,
        "description": elgato.get("Description") or "",
        "support": elgato.get("URL") or "",
        "icon": _bildpfad(ordner, elgato.get("Icon")) and
                f"{UNTERORDNER}/{_bildpfad(ordner, elgato.get('Icon'))}",
        "entry": "plugin.py",
        "class": "Plugin",
        "actions": aktionen,
    }


#: Der Ableger, der beim Einlesen entsteht. Er enthält keine Logik — die
#: steht hier in der App und wird mit ihr gepflegt, nicht mit dem Archiv.
SHIM = '''"""Beim Einlesen erzeugt. Die Arbeit macht die Brücke in der App."""

from deckswitch.plugins.elgato import ElgatoPlugin


class Plugin(ElgatoPlugin):
    pass
'''


def lies_ein(daten: bytes, ziel: Path) -> dict[str, Any]:
    """Packt ein Elgato-Archiv nach ``ziel`` aus und legt unser Manifest an.

    ``ziel`` wird angelegt und muss leer sein oder nicht existieren. Zurück
    kommt unser übersetztes Manifest.
    """
    from .installer import _extract  # dieselben Schranken wie sonst auch

    ziel.mkdir(parents=True, exist_ok=True)
    roh = ziel / UNTERORDNER
    if roh.exists():
        shutil.rmtree(roh)
    roh.mkdir()

    _extract(daten, roh)
    wurzel = next((p for p in roh.iterdir() if p.is_dir() and p.name.endswith(".sdPlugin")), None)
    if wurzel is None:
        raise ElgatoError("Im Archiv fehlt ein Ordner '<uuid>.sdPlugin'")

    kennung_aus_ordner = wurzel.name[: -len(".sdPlugin")]
    # Den Zwischenordner abschneiden: sonst hieße jeder Pfad zweimal dasselbe.
    for eintrag in list(wurzel.iterdir()):
        shutil.move(str(eintrag), str(roh / eintrag.name))
    wurzel.rmdir()

    datei = roh / "manifest.json"
    if not datei.is_file():
        raise ElgatoError("Im Archiv fehlt die manifest.json")
    elgato = json.loads(datei.read_text(encoding="utf-8"))

    manifest = uebersetze_manifest(elgato, roh, kennung=kennung_aus_ordner)
    (ziel / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ziel / "plugin.py").write_text(SHIM, encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------
# Die Anzeige über einem Dial
# --------------------------------------------------------------------------

#: Die Anordnungen, die Elgato mitbringt und die ein Plugin über ihren Namen
#: verlangen kann (``"layout": "$B1"``).
#:
#: Was worin steht, ist beschrieben — Elgatos Manifest-Schema erklärt jede
#: der sechs in einem Satz, und danach sind sie hier gebaut:
#:
#: * ``$X1`` Titel oben, Symbol darunter in der Mitte
#: * ``$A0`` Titel oben, darunter eine Bildfläche über die volle Breite
#: * ``$A1`` Titel oben, Symbol links, Wert rechts
#: * ``$B1`` wie ``$A1``, darunter ein Pegelbalken
#: * ``$B2`` wie ``$B1``, der Balken mit Verlauf
#: * ``$C1`` Titel oben, darunter zwei Reihen aus Symbol und Pegel
#:
#: Die **Maße** sind unsere: Wie viele Pixel Elgato wofür vorsieht, steht
#: nirgends. Wer es genau haben will, legt seinem Plugin eine eigene
#: Layoutdatei bei — die wird Pixel für Pixel befolgt.
def _titel_oben() -> dict[str, Any]:
    return {"key": "title", "type": "text", "rect": [8, 4, 184, 18],
            "font": {"size": 14, "weight": 600}, "alignment": "center"}


EINGEBAUTE_LAYOUTS: dict[str, dict[str, Any]] = {
    "$X1": {"items": [
        _titel_oben(),
        {"key": "icon", "type": "pixmap", "rect": [70, 26, 60, 60]},
    ]},
    "$A0": {"items": [
        _titel_oben(),
        {"key": "canvas", "type": "pixmap", "rect": [0, 24, 200, 76]},
    ]},
    "$A1": {"items": [
        _titel_oben(),
        {"key": "icon", "type": "pixmap", "rect": [10, 30, 52, 52]},
        {"key": "value", "type": "text", "rect": [72, 40, 118, 32],
         "font": {"size": 22, "weight": 600}, "alignment": "left"},
    ]},
    "$B1": {"items": [
        _titel_oben(),
        {"key": "icon", "type": "pixmap", "rect": [10, 30, 52, 52]},
        {"key": "value", "type": "text", "rect": [72, 28, 118, 28],
         "font": {"size": 20, "weight": 600}, "alignment": "left"},
        {"key": "indicator", "type": "bar", "rect": [72, 64, 118, 12],
         "bar_bg_c": "0:#1b1b1b,1:#1b1b1b", "bar_fill_c": "#3b82f6"},
    ]},
    "$C1": {"items": [
        _titel_oben(),
        {"key": "icon1", "type": "pixmap", "rect": [10, 28, 30, 30]},
        {"key": "indicator1", "type": "bar", "rect": [50, 36, 140, 12],
         "bar_bg_c": "0:#1b1b1b,1:#1b1b1b", "bar_fill_c": "#3b82f6"},
        {"key": "icon2", "type": "pixmap", "rect": [10, 64, 30, 30]},
        {"key": "indicator2", "type": "bar", "rect": [50, 72, 140, 12],
         "bar_bg_c": "0:#1b1b1b,1:#1b1b1b", "bar_fill_c": "#3b82f6"},
    ]},
}
# ``$B2`` unterscheidet sich von ``$B1`` allein im Verlauf des Balkens.
EINGEBAUTE_LAYOUTS["$B2"] = {"items": [
    *(eintrag for eintrag in EINGEBAUTE_LAYOUTS["$B1"]["items"] if eintrag["key"] != "indicator"),
    {"key": "indicator", "type": "gbar", "rect": [72, 64, 118, 12],
     "bar_bg_c": "0:#1b1b1b,1:#1b1b1b", "bar_fill_c": "#3b82f6"},
]}


def _farbe(angabe: Any, vorgabe: str = "#ffffff") -> str:
    """Eine Farbangabe aus einem Layout.

    Verläufe stehen als ``"0:#111,1:#222"`` darin. Gezeichnet wird die erste
    Stufe — ein Verlauf über zwölf Pixel Balkenhöhe ist nicht zu sehen, und
    ein falsch geratener wäre schlechter als keiner.
    """
    text = str(angabe or "").strip()
    if not text:
        return vorgabe
    if ":" in text:
        text = text.split(",")[0].split(":", 1)[1].strip()
    return text or vorgabe


def _wert(eintrag: Any) -> Any:
    """``setFeedback`` erlaubt einen nackten Wert oder ein Objekt mit ``value``."""
    if isinstance(eintrag, dict):
        return eintrag.get("value")
    return eintrag


def zeichne_layout(
    bild: Image.Image,
    layout: dict[str, Any],
    werte: dict[str, Any],
    ordner: Path,
) -> None:
    """Malt eine Encoder-Anzeige nach dem Layout des Plugins.

    Die Maße im Layout gelten für 200×100; ist unser Segment anders groß,
    wird mitskaliert. Gezeichnet werden Text, Balken und Bilder — mehr
    kennen die Layouts nicht.
    """
    from PIL import ImageDraw

    from ..services.backgrounds import parse_color
    from ..services.render import load_font

    stift = ImageDraw.Draw(bild)
    fx = bild.width / LAYOUT_RAUM[0]
    fy = bild.height / LAYOUT_RAUM[1]

    for eintrag in layout.get("items") or []:
        schluessel = str(eintrag.get("key") or "")
        gesetzt = werte.get(schluessel, eintrag.get("value"))
        if isinstance(werte.get(schluessel), dict) and werte[schluessel].get("enabled") is False:
            continue
        wert = _wert(gesetzt)
        rechteck = eintrag.get("rect") or [0, 0, LAYOUT_RAUM[0], LAYOUT_RAUM[1]]
        x, y, breite, hoehe = (
            round(rechteck[0] * fx), round(rechteck[1] * fy),
            round(rechteck[2] * fx), round(rechteck[3] * fy),
        )
        art = str(eintrag.get("type") or "text")

        if art == "text":
            text = "" if wert is None else str(wert)
            if not text:
                continue
            schrift_angabe = eintrag.get("font") or {}
            groesse = max(7, round(float(schrift_angabe.get("size") or 14) * fy))
            fett = int(schrift_angabe.get("weight") or 400) >= 600
            schrift = load_font(groesse, bold=fett)
            breite_text = stift.textlength(text, font=schrift)
            ausrichtung = str(eintrag.get("alignment") or "center")
            if ausrichtung == "left":
                tx = x
            elif ausrichtung == "right":
                tx = x + breite - breite_text
            else:
                tx = x + (breite - breite_text) / 2
            stift.text(
                (tx, y + max(0, (hoehe - groesse * 1.2) / 2)),
                text, font=schrift,
                fill=parse_color(str(eintrag.get("color") or "#ffffff"), (255, 255, 255, 255)),
            )

        elif art in ("bar", "gbar"):
            try:
                anteil = max(0.0, min(1.0, float(wert or 0) / 100.0))
            except (TypeError, ValueError):
                anteil = 0.0
            radius = max(1, hoehe // 2)
            # Der ``subtype`` beschreibt bei Elgato die Form (Nut, Trapez,
            # doppeltes Trapez). Welche Zahl welche Form meint, ist nicht
            # dokumentiert; gezeichnet wird deshalb durchgehend ein Balken.
            stift.rounded_rectangle(
                (x, y, x + breite, y + hoehe), radius=radius,
                fill=parse_color(_farbe(eintrag.get("bar_bg_c"), "#1b1b1b"), (27, 27, 27, 255)),
            )
            gefuellt = round(breite * anteil)
            if gefuellt > 2:
                stift.rounded_rectangle(
                    (x, y, x + gefuellt, y + hoehe), radius=radius,
                    fill=parse_color(_farbe(eintrag.get("bar_fill_c"), "#3b82f6"),
                                     (59, 130, 246, 255)),
                )

        elif art == "pixmap":
            quelle = _lade_pixmap(wert, ordner)
            if quelle is None:
                continue
            passend = quelle.copy()
            passend.thumbnail((max(1, breite), max(1, hoehe)), Image.LANCZOS)
            bild.alpha_composite(
                passend,
                (x + (breite - passend.width) // 2, y + (hoehe - passend.height) // 2),
            )


def _lade_pixmap(wert: Any, ordner: Path) -> Image.Image | None:
    """Ein Bild aus einem Layout — entweder mitgeschickt oder aus dem Plugin."""
    if not isinstance(wert, str) or not wert:
        return None
    if wert.startswith("data:") or len(wert) > 256:
        roh = wert.split(",", 1)[1] if wert.startswith("data:") else wert
        try:
            bild = Image.open(io.BytesIO(base64.b64decode(roh, validate=False)))
            bild.load()
            return bild.convert("RGBA")
        except Exception:  # noqa: BLE001 — fremde Bytes
            return None
    pfad = _bildpfad(ordner, wert)
    if pfad is None:
        return None
    try:
        with Image.open(ordner / pfad) as bild:
            return bild.convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Der Prozess und das Protokoll
# --------------------------------------------------------------------------


#: Browser, in denen ein HTML-Plugin laufen kann — in dieser Reihenfolge
#: gesucht. Gebraucht wird nur ein Chromium-Abkömmling mit ``--headless``;
#: Firefox fehlt hier, weil sein Kopflos-Betrieb keine dauerhaft laufende
#: Seite mit Netzzugriff in derselben Form anbietet.
BROWSER = ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave")


def _browser() -> str | None:
    for name in BROWSER:
        pfad = shutil.which(name)
        if pfad:
            return pfad
    return None


def wine_prefix() -> Path:
    """Die Windows-Umgebung, in der Windows-Plugins laufen.

    Eine für alle, nicht eine je Plugin: Darin liegt die Laufzeit (.NET oder
    was sonst gebraucht wird), und die achtzig Megabyte je Plugin abzulegen
    wäre Verschwendung. Getrennt bleiben die Plugins trotzdem — jedes hat
    seinen eigenen Prozess, und darum ging es.
    """
    from .. import paths

    return paths.DATA_DIR / "wine"


def art_des_plugins(elgato: dict[str, Any]) -> str:
    """``node``, ``html`` oder ``windows`` — woran der Start hängt."""
    pfad = str(elgato.get("CodePath") or "").replace("\\", "/")
    if elgato.get("Nodejs") or pfad.endswith(".js"):
        return "node"
    if pfad.endswith((".html", ".htm")):
        return "html"
    if pfad.endswith(".exe") or elgato.get("CodePathWin"):
        return "windows"
    return "unbekannt"


def startbefehl(
    ordner: Path, elgato: dict[str, Any], port: int = 0, profil: Path | None = None
) -> list[str]:
    """Womit dieses Plugin gestartet wird.

    Drei Sorten, drei Startbefehle — alles danach ist dasselbe Protokoll.

    Ein HTML-Plugin bekommt einen **eigenen Browser-Prozess** mit eigenem
    Profil. Nicht aus Vorsicht allein: Hängt eine Seite, hängt sie für sich.
    Ein gemeinsamer Browser nähme beim Absturz alle anderen Plugins mit.
    """
    pfad = str(elgato.get("CodePath") or "").replace("\\", "/")
    art = art_des_plugins(elgato)

    if art == "node":
        node = shutil.which("node")
        if not node:
            raise ElgatoError("Für dieses Plugin wird node gebraucht, es ist nicht installiert")
        return [node, str(ordner / pfad)]

    if art == "html":
        browser = _browser()
        if not browser:
            raise ElgatoError(
                "Dieses Plugin läuft im Browser. Dafür wird Chromium gebraucht "
                f"(gesucht: {', '.join(BROWSER)})"
            )
        return [
            browser,
            "--headless=new",
            f"--user-data-dir={profil}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            # Ohne das drosselt der Browser eine Seite, die er für unsichtbar
            # hält: Ein Plugin mit Uhr oder Abfrage bliebe stehen.
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            f"http://127.0.0.1:{port}/{pfad}?deckswitch=plugin",
        ]

    if art == "windows":
        wine = shutil.which("wine")
        if not wine:
            raise ElgatoError(
                "Dieses Plugin ist ein Windows-Programm. Dafür wird wine gebraucht, "
                "es ist nicht installiert"
            )
        exe = pfad or str(elgato.get("CodePathWin") or "")
        return [wine, str(ordner / exe.replace("\\", "/"))]
    raise ElgatoError(f"Unbekannte Art von Plugin: CodePath={pfad!r}")


def _freier_port() -> int:
    """Ein freier Port, den wir gleich auf mehreren Adressen belegen.

    Nötig, weil ``0`` je Adresse einen *anderen* Port zöge; das Plugin
    bekommt aber nur eine Nummer genannt.
    """
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Bruecke:
    """Spielt für ein Elgato-Plugin die Stream-Deck-Software.

    Der WebSocket-Server läuft auf einem freien Port auf 127.0.0.1. Mehr
    Absicherung braucht es nicht und mehr gibt das Protokoll auch nicht her:
    Elgato kennt keine Anmeldung, nur die UUID als Erkennungszeichen.
    """

    def __init__(
        self, plugin: "ElgatoPlugin", ordner: Path, elgato: dict[str, Any], kennung: str = ""
    ) -> None:
        self.plugin = plugin
        self.ordner = ordner
        self.elgato = elgato
        # Ältere Plugins (SDK 2) nennen keine UUID im Manifest. Ohne diesen
        # Rückgriff meldeten sie sich mit leerer Kennung an, und ihr
        # Browserprofil hieße nach niemandem.
        self.uuid = str(elgato.get("UUID") or "") or kennung
        self.verbindung: Any = None
        #: Offene Einstellungsseiten, nach Belegung. Elgato lässt sie auf
        #: denselben Port verbinden wie das Plugin; unterschieden werden sie
        #: allein an ihrer Anmeldung.
        self.inspektoren: dict[str, Any] = {}
        self._server: Any = None
        self._port = 0
        self._prozess: asyncio.subprocess.Process | None = None
        #: Eigenes Browserprofil, falls dieses Plugin im Browser läuft.
        self._profil: Path | None = None
        self._leser: asyncio.Task | None = None
        self.bereit = asyncio.Event()
        #: Die zuletzt ausgegebene Zeile des Prozesses.
        self.letzte_ausgabe = ""

    # -- Aufbau ------------------------------------------------------------

    async def start(self) -> None:
        import websockets

        art = art_des_plugins(self.elgato)

        # Derselbe Port bedient beides: den WebSocket und die Dateien des
        # Plugins. Das ist kein Kunstgriff, sondern eine Grenze — eine Seite,
        # die von hier kommt, hat einen anderen Ursprung als unsere API und
        # kann sie deshalb nicht als wir aufrufen.
        # Auf beiden Stacks: Ein Plugin verbindet sich nach ``localhost``,
        # und wer das zuerst als ``::1`` auflöst, liefe bei einem Server, der
        # nur auf 127.0.0.1 lauscht, ins Leere. Genau daran hing das erste
        # Windows-Plugin, das hier laufen sollte.
        port = _freier_port()
        try:
            self._server = await websockets.serve(
                self._bediene, ["127.0.0.1", "::1"], port, process_request=self._http,
            )
        except OSError:
            # Kein IPv6 auf diesem Rechner — dann eben nur IPv4.
            self._server = await websockets.serve(
                self._bediene, "127.0.0.1", port, process_request=self._http,
            )
        self._port = port

        if art == "html":
            self._profil = Path(tempfile.mkdtemp(prefix=f"deckswitch-{self.uuid}-"))
        befehl = startbefehl(self.ordner, self.elgato, port, self._profil)

        # Ein Browser bekommt seine Angaben über die Adresse, ein Programm
        # über die Kommandozeile.
        argumente = befehl if art == "html" else [
            *befehl,
            "-port", str(port),
            "-pluginUUID", self.uuid,
            "-registerEvent", "registerPlugin",
            "-info", json.dumps(self._info()),
        ]
        self._prozess = await asyncio.create_subprocess_exec(
            *argumente,
            cwd=str(self.ordner),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # Eigene Prozessgruppe: Ein Browser startet Kindprozesse, und die
            # überleben das Ende des Elternprozesses. Ohne diese Gruppe
            # blieben nach jedem Neustart Chrome-Reste stehen — samt ihrem
            # Profilordner, den niemand mehr aufräumt. Wine tut dasselbe.
            start_new_session=True,
            env=self._umgebung(art),
        )
        self._leser = asyncio.create_task(self._protokolliere())
        log.info("Elgato-Plugin '%s' gestartet als %s (Port %d, PID %s)",
                 self.uuid, art, port, self._prozess.pid)

    def _umgebung(self, art: str) -> dict[str, str]:
        """Die Umgebung des Plugin-Prozesses."""
        umgebung = dict(os.environ)
        if art == "windows":
            prefix = wine_prefix()
            prefix.mkdir(parents=True, exist_ok=True)
            umgebung["WINEPREFIX"] = str(prefix)
            # Wine schreibt sonst seitenweise fixme-Zeilen in unser Protokoll.
            umgebung.setdefault("WINEDEBUG", "-all")
            # .NET sucht unter Windows die ICU-Bibliothek und findet sie in
            # einem Wine-Prefix nicht. Es fällt dann in den invarianten Modus
            # und lehnt jede Sprachangabe ab — ein Plugin, das aus
            # ``application.language`` eine CultureInfo baut, stürzt beim
            # Start ab. Mit NLS nimmt es die Windows-Wege, die Wine kennt.
            umgebung.setdefault("DOTNET_SYSTEM_GLOBALIZATION_USENLS", "1")
        return umgebung

    def _http(self, verbindung: Any, anfrage: Any) -> Any:
        """Dateien des Plugins ausliefern — alles außer dem WebSocket.

        Nur lesend, nur aus dem Plugin-Ordner, nur bekannte Dateitypen. Der
        Pfad kommt aus der Seite selbst und wird deshalb geprüft, als käme er
        von einem Fremden — er tut es ja auch.
        """
        from websockets.http11 import Response

        if anfrage.headers.get("Upgrade", "").lower() == "websocket":
            return None  # das ist der Draht, nicht die Seite

        pfad = anfrage.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        mit_anschluss = "deckswitch=plugin" in anfrage.path

        ziel = (self.ordner / unquote(pfad)).resolve()
        if not pfad or self.ordner.resolve() not in ziel.parents or not ziel.is_file():
            return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}),
                            b"Nicht gefunden")

        typ = mimetypes.guess_type(ziel.name)[0] or "application/octet-stream"
        try:
            inhalt = ziel.read_bytes()
        except OSError:
            return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}), b"")

        if mit_anschluss and ziel.suffix.lower() in (".html", ".htm"):
            inhalt = inhalt.decode("utf-8", "replace").encode("utf-8")
            inhalt += self.plugin.anschluss_seite().encode("utf-8")
            typ = "text/html; charset=utf-8"

        kopf = Headers({
            "Content-Type": typ,
            "Content-Length": str(len(inhalt)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        })
        return Response(200, "OK", kopf, inhalt)

    def _info(self) -> dict[str, Any]:
        """Was die Software beim Start über sich und das Gerät erzählt.

        ``platform`` nennt das System, für das das Plugin gebaut wurde, und
        nicht unseres. Elgatos SDK kennt in diesem Feld genau zwei Werte,
        ``mac`` und ``windows``; Bibliotheken lesen es in eine Aufzählung
        ein und werfen bei allem anderen. Mit ``linux`` stürzte ein
        .NET-Plugin beim Start ab, noch bevor es sich anmelden konnte —
        gemessen am 2026-08-23. Wir sagen dem Plugin also, in welcher der
        beiden Welten es sich wähnen soll; alles andere hieße für es „gar
        nicht laufen".

        ``language`` bleibt englisch. Unter WINE fehlen die ICU-Daten, und
        ein Plugin, das daraus eine ``CultureInfo`` baut, stürzt bei jedem
        anderen Wert ab.
        """
        return {
            "application": {
                "font": "Noto Sans",
                "language": "en",
                "platform": self._plattform(),
                "platformVersion": "10.0.0",
                "version": "6.5.0.20770",
            },
            "colors": {
                "buttonPressedBackgroundColor": "#303030FF",
                "buttonPressedBorderColor": "#646464FF",
                "buttonPressedTextColor": "#969696FF",
                "disabledColor": "#F7821B59",
                "highlightColor": "#F7821BFF",
                "mouseDownColor": "#CF6304FF",
            },
            "devicePixelRatio": 2,
            "devices": [{
                "id": "DECKSWITCH",
                "name": "DECK//SWITCH",
                "size": {"columns": 4, "rows": 2},
                # 7 = Stream Deck +. Ein Plugin, das Dials anbietet, prüft das.
                "type": 7,
            }],
            "plugin": {"uuid": self.uuid, "version": str(self.elgato.get("Version") or "")},
        }

    def _plattform(self) -> str:
        """``windows`` oder ``mac`` — je nachdem, wofür das Plugin gebaut ist."""
        if art_des_plugins(self.elgato) == "windows":
            return "windows"
        genannt = [
            str(eintrag.get("Platform") or "").lower()
            for eintrag in self.elgato.get("OS") or []
        ]
        if "windows" in genannt or not genannt:
            return "windows"
        return genannt[0]

    async def _protokolliere(self) -> None:
        """Was das Plugin auf stdout schreibt, landet in unserem Protokoll."""
        if self._prozess is None or self._prozess.stdout is None:
            return
        async for zeile in self._prozess.stdout:
            text = zeile.decode("utf-8", "replace").rstrip()
            if text:
                # Die letzte Zeile bleibt stehen: Meldet sich ein Plugin nie
                # an, ist sie die einzige Spur, die der Benutzer sieht.
                self.letzte_ausgabe = text[:200]
            log.debug("[%s] %s", self.uuid, text)

    async def stop(self) -> None:
        for aufgabe in (self._leser,):
            if aufgabe is not None:
                aufgabe.cancel()
        if self._prozess is not None and self._prozess.returncode is None:
            self._beende_gruppe(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._prozess.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._beende_gruppe(signal.SIGKILL)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._prozess.wait(), timeout=3)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._profil is not None:
            shutil.rmtree(self._profil, ignore_errors=True)
            self._profil = None
        self.verbindung = None
        self.bereit.clear()

    def _beende_gruppe(self, zeichen: int) -> None:
        """Beendet den Prozess samt seiner Kinder."""
        if self._prozess is None:
            return
        try:
            os.killpg(os.getpgid(self._prozess.pid), zeichen)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError):
                self._prozess.send_signal(zeichen)

    # -- Der Draht ---------------------------------------------------------

    @property
    def port(self) -> int:
        """Der Port des Servers — die GUI braucht ihn für die Seite."""
        return self._port

    async def _bediene(self, verbindung: Any) -> None:
        """Eine Gegenstelle — welche, sagt erst ihre Anmeldung.

        Plugin und Einstellungsseiten verbinden sich auf denselben Port. Wer
        hier ankommt, ist deshalb zunächst niemand; erst ``registerPlugin``
        bzw. ``registerPropertyInspector`` ordnet die Verbindung zu.
        """
        import websockets

        try:
            async for roh in verbindung:
                try:
                    nachricht = json.loads(roh)
                except json.JSONDecodeError:
                    log.warning("[%s] unlesbare Nachricht", self.uuid)
                    continue
                try:
                    await self._verarbeite(nachricht, verbindung)
                except Exception:  # noqa: BLE001
                    # Eine Anweisung, die uns aus dem Tritt bringt, darf nicht
                    # die Verbindung kosten — sonst nimmt ein einziges
                    # unerwartetes Feld das ganze Plugin mit.
                    log.exception("[%s] Anweisung nicht verarbeitet: %s",
                                  self.uuid, nachricht.get("event"))
        except websockets.exceptions.ConnectionClosed:
            # Beim Beenden fällt der Draht ohne Abschiedsrahmen. Das ist der
            # Normalfall und kein Fehler — laut wäre es nur Rauschen.
            log.debug("[%s] Verbindung beendet", self.uuid)
        finally:
            if self.verbindung is verbindung:
                self.verbindung = None
                self.bereit.clear()
            for kontext, offen in list(self.inspektoren.items()):
                if offen is verbindung:
                    del self.inspektoren[kontext]
                    await self.plugin.inspektor_da(kontext, False)

    async def sende(self, ereignis: dict[str, Any]) -> None:
        """Ein Ereignis an das Plugin. Ohne Verbindung passiert nichts."""
        await self._sende_an(self.verbindung, ereignis)

    async def sende_an_inspektor(self, kontext: str, ereignis: dict[str, Any]) -> None:
        """Ein Ereignis an die offene Einstellungsseite dieser Belegung."""
        await self._sende_an(self.inspektoren.get(kontext), ereignis)

    async def _sende_an(self, verbindung: Any, ereignis: dict[str, Any]) -> None:
        if verbindung is None:
            return
        try:
            await verbindung.send(json.dumps(ereignis))
        except Exception as exc:  # noqa: BLE001 — ein toter Draht ist kein Absturz
            log.debug("[%s] senden fehlgeschlagen: %s", self.uuid, exc)

    async def _verarbeite(self, nachricht: dict[str, Any], verbindung: Any = None) -> None:
        ereignis = nachricht.get("event")
        if ereignis == "registerPlugin":
            self.verbindung = verbindung
            self.bereit.set()
            log.info("Elgato-Plugin '%s' hat sich angemeldet", self.uuid)
            return
        if ereignis == "registerPropertyInspector":
            # Die Seite meldet sich mit der Belegung an, zu der sie gehört.
            kontext = str(nachricht.get("uuid") or "")
            self.inspektoren[kontext] = verbindung
            log.info("[%s] Einstellungsseite offen für %s", self.uuid, kontext)
            await self.plugin.inspektor_da(kontext, True)
            return
        # Alles Weitere kann von beiden Seiten kommen. Woher es kam,
        # entscheidet, wohin die Antwort geht.
        vom_inspektor = verbindung is not None and verbindung is not self.verbindung
        await self.plugin.vom_plugin(ereignis or "", nachricht, vom_inspektor=vom_inspektor)


# --------------------------------------------------------------------------
# Das Plugin aus unserer Sicht
# --------------------------------------------------------------------------


class ElgatoPlugin(ActionPlugin):
    """Ein eingelesenes Elgato-Plugin als ganz gewöhnliches Action-Plugin.

    Von außen sieht es aus wie jedes andere: Aktionen, Zustände, Tasten. Nach
    innen wird jeder Hook zu einem Ereignis auf dem Draht, und was von dort
    zurückkommt, landet als Bild oder Beschriftung auf der Kachel.
    """

    def __init__(self, manifest, services) -> None:
        super().__init__(manifest, services)
        self.ordner = services.plugin_dir / UNTERORDNER
        datei = self.ordner / "manifest.json"
        self.elgato: dict[str, Any] = (
            json.loads(datei.read_text(encoding="utf-8")) if datei.is_file() else {}
        )
        self.bruecke = Bruecke(self, self.ordner, self.elgato, kennung=manifest.id)
        self.fehler: str = ""

        #: Was das Plugin zu einer Belegung geschickt hat, nach ``ctx.key``.
        #: Bilder liegen fertig als PIL-Objekt darin — das Umwandeln aus
        #: base64 gehört nicht in die Zeichenschleife.
        self._bilder: dict[str, Image.Image] = {}
        self._titel: dict[str, str] = {}
        self._zustaende: dict[str, int] = {}
        self._meldungen: dict[str, tuple[str, float]] = {}
        #: Werte der Encoder-Anzeige je Belegung (``setFeedback``).
        self._anzeige: dict[str, dict[str, Any]] = {}
        #: Ein zur Laufzeit gewechseltes Layout (``setFeedbackLayout``).
        self._layoutwahl: dict[str, str] = {}
        #: Schon gelesene Layoutdateien, nach ihrem Pfad.
        self._layouts: dict[str, dict[str, Any]] = {}
        #: Belegungen, denen wir schon ``willAppear`` geschickt haben.
        self._angemeldet: set[str] = set()
        self._kontexte: dict[str, SlotContext] = {}

    # -- Leben ------------------------------------------------------------

    async def setup(self) -> None:
        try:
            await self.bruecke.start()
        except ElgatoError as exc:
            self.fehler = str(exc)
            log.warning("Elgato-Plugin '%s': %s", self.manifest.id, exc)
        except Exception as exc:  # noqa: BLE001
            self.fehler = f"{type(exc).__name__}: {exc}"
            log.exception("Elgato-Plugin '%s' startet nicht", self.manifest.id)

    async def teardown(self) -> None:
        await self.bruecke.stop()

    def get_status(self) -> dict[str, Any] | None:
        if self.fehler:
            return {"connected": False, "detail": self.fehler}
        verbunden = self.bruecke.bereit.is_set()
        if verbunden:
            return {"connected": True, "detail": "verbunden"}

        ausgabe = self.bruecke.letzte_ausgabe
        # Die häufigste Hürde bei Windows-Plugins hat einen Namen und eine
        # Lösung. Sie hier zu nennen erspart die Suche in einer englischen
        # Meldung, die auf eine Microsoft-Seite zeigt.
        if "must install" in ausgabe.lower() and ".net" in ausgabe.lower():
            return {
                "connected": False,
                "detail": "Diesem Plugin fehlt die .NET-Laufzeit — einmalig "
                          "einrichten mit scripts/setup-wine-dotnet.py",
            }
        return {"connected": False, "detail": ausgabe or "startet …"}

    # -- Unsere Hooks werden ihre Ereignisse -------------------------------

    async def _melde_an(self, action_id: str, settings: dict, ctx: SlotContext) -> None:
        """``willAppear``, sobald wir eine Belegung das erste Mal sehen.

        Die Software schickt das, wenn eine Taste sichtbar wird. Wir haben
        keinen eigenen Haken dafür, also holen wir es nach — beim ersten
        Zeichnen oder beim ersten Druck, je nachdem, was zuerst kommt.
        """
        self._kontexte[ctx.key] = ctx
        if ctx.key in self._angemeldet:
            return
        self._angemeldet.add(ctx.key)
        await self.bruecke.sende({
            "event": "willAppear",
            "action": action_id,
            "context": ctx.key,
            "device": "DECKSWITCH",
            "payload": self._nutzlast(settings, ctx),
        })

    def _nutzlast(self, settings: dict, ctx: SlotContext) -> dict[str, Any]:
        spalten = 4
        return {
            "settings": settings.get("elgato") or {},
            "coordinates": {"column": ctx.index % spalten, "row": ctx.index // spalten},
            "controller": "Encoder" if ctx.input_type == "dial" else "Keypad",
            # Elgato-Plugins verhalten sich in einer Multi-Aktion anders: Ein
            # Umschalter schaltet dort nicht um, sondern setzt den Zustand,
            # den der Benutzer im Schritt gewählt hat. Wer das immer mit
            # ``false`` beantwortet, bekommt in Ketten falsches Verhalten.
            "isInMultiAction": ":step-" in ctx.key,
            "state": self._zustaende.get(ctx.key, 0),
            **({"userDesiredState": ctx.desired_state}
               if getattr(ctx, "desired_state", None) is not None else {}),
        }

    async def on_key_down(self, action_id, settings, ctx):
        await self._melde_an(action_id, settings, ctx)
        await self.bruecke.sende({
            "event": "keyDown", "action": action_id, "context": ctx.key,
            "device": "DECKSWITCH", "payload": self._nutzlast(settings, ctx),
        })

    async def on_key_up(self, action_id, settings, ctx):
        await self._melde_an(action_id, settings, ctx)
        await self.bruecke.sende({
            "event": "keyUp", "action": action_id, "context": ctx.key,
            "device": "DECKSWITCH", "payload": self._nutzlast(settings, ctx),
        })

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        await self._melde_an(action_id, settings, ctx)
        nutzlast = self._nutzlast(settings, ctx)
        nutzlast["ticks"] = delta
        nutzlast["pressed"] = False
        await self.bruecke.sende({
            "event": "dialRotate", "action": action_id, "context": ctx.key,
            "device": "DECKSWITCH", "payload": nutzlast,
        })

    async def on_dial_push(self, action_id, settings, ctx):
        """Ein Druck auf den Dial ist bei Elgato zweiteilig: down und up."""
        await self._melde_an(action_id, settings, ctx)
        for ereignis in ("dialDown", "dialUp"):
            await self.bruecke.sende({
                "event": ereignis, "action": action_id, "context": ctx.key,
                "device": "DECKSWITCH", "payload": self._nutzlast(settings, ctx),
            })

    async def on_touch(self, action_id, settings, x, y, ctx):
        await self._melde_an(action_id, settings, ctx)
        nutzlast = self._nutzlast(settings, ctx)
        nutzlast["tapPos"] = [x, y]
        nutzlast["hold"] = False
        await self.bruecke.sende({
            "event": "touchTap", "action": action_id, "context": ctx.key,
            "device": "DECKSWITCH", "payload": nutzlast,
        })

    async def on_tick(self, action_id, settings, ctx):
        await self._melde_an(action_id, settings, ctx)
        # Abgelaufene Rückmeldungen abräumen.
        eintrag = self._meldungen.get(ctx.key)
        if eintrag is not None:
            import time
            if time.monotonic() > eintrag[1]:
                self._meldungen.pop(ctx.key, None)
                ctx.request_redraw()

    # -- Ihre Anweisungen werden unsere Anzeige ----------------------------

    def anschluss_seite(self) -> str:
        """Der Anschluss für ein Plugin, das selbst eine Seite ist.

        Anders als bei der Einstellungsseite bekommt die Plugin-Seite vier
        Angaben statt fünf: Sie gehört keiner einzelnen Belegung, sondern
        dem ganzen Plugin.
        """
        daten = {
            "port": self.bruecke.port,
            "uuid": self.bruecke.uuid,
            "ereignis": "registerPlugin",
            "info": json.dumps(self.bruecke._info()),
        }
        return (
            "\n<script>(function(){var d=" + json.dumps(daten) + ";"
            "function start(){"
            "var f=window.connectElgatoStreamDeckSocket||window.connectSocket;"
            "if(typeof f!=='function'){console.warn('DECK//SWITCH: Diese Seite bietet "
            "keinen Anschluss (connectElgatoStreamDeckSocket fehlt).');return;}"
            "f(d.port,d.uuid,d.ereignis,d.info);}"
            "if(document.readyState==='complete'){start();}"
            "else{window.addEventListener('load',start);}})();</script>\n"
        )

    def anschluss(self, kontext: str, action_id: str = "") -> str:
        """Das Stück, das die Einstellungsseite mit der Brücke verbindet.

        Elgato sieht dafür ``connectElgatoStreamDeckSocket`` vor: Die
        Software ruft es mit Port, Kennung und dem Zustand der Belegung auf.
        Ältere Seiten heißen dieselbe Funktion ``connectSocket`` — beide
        werden versucht, sonst stünde eine sonst brauchbare Seite tot da.

        ``info`` und ``actionInfo`` gehen als JSON-*Zeichenketten* hinein.
        Das ist keine Marotte: Die Seiten rufen darauf ``JSON.parse`` auf.
        """
        aktion = action_id or self._aktion_von(kontext) or self._aktion_aus_belegung(kontext)
        belegung = self._belegung(kontext)
        art = "Encoder" if kontext.split(":")[1:2] == ["dial"] else "Keypad"
        index = int(kontext.split(":")[2]) if kontext.count(":") >= 2 and kontext.split(":")[2].isdigit() else 0

        aktionsinfo = {
            "action": aktion,
            "context": kontext,
            "device": "DECKSWITCH",
            "payload": {
                "settings": self._einstellungen(kontext),
                "coordinates": {"column": index % 4, "row": index // 4},
                "controller": art,
                "state": self._zustaende.get(kontext, 0),
                "isInMultiAction": False,
            },
        }
        if belegung is None and kontext not in self._kontexte:
            log.debug("[%s] Einstellungsseite für unbekannte Belegung %s",
                      self.manifest.id, kontext)

        daten = {
            "port": self.bruecke.port,
            "uuid": kontext,
            "ereignis": "registerPropertyInspector",
            "info": json.dumps(self.bruecke._info()),
            "aktionsinfo": json.dumps(aktionsinfo),
        }
        return (
            "\n<script>(function(){var d=" + json.dumps(daten) + ";"
            "function start(){"
            "var f=window.connectElgatoStreamDeckSocket||window.connectSocket;"
            "if(typeof f!=='function'){console.warn('DECK//SWITCH: Diese Seite bietet "
            "keinen Anschluss (connectElgatoStreamDeckSocket fehlt).');return;}"
            "f(d.port,d.uuid,d.ereignis,d.info,d.aktionsinfo);}"
            "if(document.readyState==='complete'){start();}"
            "else{window.addEventListener('load',start);}})();</script>\n"
        )

    async def inspektor_da(self, kontext: str, offen: bool) -> None:
        """Eine Einstellungsseite wurde geöffnet oder geschlossen.

        Das Plugin erfährt es: Manche schicken erst dann ihre Auswahllisten
        (Geräte, Szenen, Kanäle) an die Seite.
        """
        await self.bruecke.sende({
            "event": "propertyInspectorDidAppear" if offen else "propertyInspectorDidDisappear",
            "action": self._aktion_von(kontext) or self._aktion_aus_belegung(kontext),
            "context": kontext,
            "device": "DECKSWITCH",
        })
        if offen:
            # Die Seite bekommt ungefragt den aktuellen Stand — Elgato macht
            # das genauso, sonst stünde sie beim Öffnen leer da.
            await self.bruecke.sende_an_inspektor(kontext, {
                "event": "didReceiveSettings",
                "action": self._aktion_von(kontext) or self._aktion_aus_belegung(kontext),
                "context": kontext,
                "device": "DECKSWITCH",
                "payload": {"settings": self._einstellungen(kontext)},
            })

    async def vom_plugin(
        self, ereignis: str, nachricht: dict[str, Any], vom_inspektor: bool = False
    ) -> None:
        """Eine Anweisung — vom Plugin oder von einer Einstellungsseite."""
        kontext = str(nachricht.get("context") or "")
        nutzlast = nachricht.get("payload") or {}

        if vom_inspektor:
            await self._von_der_seite(ereignis, nachricht, kontext, nutzlast)
            return

        if ereignis == "setImage":
            self._setze_bild(kontext, nutzlast.get("image"))
        elif ereignis == "setTitle":
            self._titel[kontext] = str(nutzlast.get("title") or "")
        elif ereignis == "setState":
            self._zustaende[kontext] = int(nutzlast.get("state") or 0)
        elif ereignis == "showOk":
            self._merke_meldung(kontext, "ok")
        elif ereignis == "showAlert":
            self._merke_meldung(kontext, "alarm")
        elif ereignis == "setSettings":
            self._schreibe_einstellungen(kontext, nutzlast)
            return
        elif ereignis == "getSettings":
            ctx = self._kontexte.get(kontext)
            await self.bruecke.sende({
                "event": "didReceiveSettings",
                "action": self._aktion_von(kontext), "context": kontext,
                "device": "DECKSWITCH",
                "payload": self._nutzlast(ctx.settings if ctx else {}, ctx) if ctx else {},
            })
            return
        elif ereignis == "setGlobalSettings":
            self.plugin_config.update(nutzlast if isinstance(nutzlast, dict) else {})
            return
        elif ereignis == "getGlobalSettings":
            await self.bruecke.sende({
                "event": "didReceiveGlobalSettings",
                "context": kontext,
                "payload": {"settings": dict(self.plugin_config)},
            })
            return
        elif ereignis == "openUrl":
            # Denselben Weg wie das System-Plugin: xdg-open, abgekoppelt.
            adresse = str(nutzlast.get("url") or "")
            if adresse.startswith(("http://", "https://")):
                import subprocess
                subprocess.Popen(
                    ["xdg-open", adresse],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif adresse:
                # Ein Plugin, das file:// oder einen eigenen Handler öffnen
                # will, bekommt das nicht — dafür ist es zu fremd.
                log.warning("[%s] openUrl abgelehnt: %s", self.manifest.id, adresse[:80])
            return
        elif ereignis == "logMessage":
            log.info("[%s] %s", self.manifest.id, nutzlast.get("message"))
            return
        elif ereignis == "setFeedback":
            # Die Werte kommen einzeln und ersetzen nur, was dasteht: Ein
            # Plugin, das nur den Pegel neu schickt, will nicht den Titel
            # löschen.
            if isinstance(nutzlast, dict):
                self._anzeige.setdefault(kontext, {}).update(nutzlast)
        elif ereignis == "setFeedbackLayout":
            gewaehlt = str((nutzlast or {}).get("layout") or "")
            if gewaehlt:
                self._layoutwahl[kontext] = gewaehlt
        elif ereignis == "switchToProfile":
            self._wechsle_profil(nutzlast)
            return
        elif ereignis == "sendToPropertyInspector":
            # Antwort des Plugins an seine offene Einstellungsseite —
            # darüber laufen die Auswahllisten (Geräte, Szenen, Kanäle).
            await self.bruecke.sende_an_inspektor(kontext, {
                "event": "sendToPropertyInspector",
                "action": self._aktion_von(kontext) or self._aktion_aus_belegung(kontext),
                "context": kontext,
                "payload": nutzlast,
            })
            return
        else:
            # setFeedback, sendToPropertyInspector, switchToProfile: kennen
            # wir noch nicht. Sichtbar im Protokoll, damit man weiß, was ein
            # Plugin erwartet hätte.
            log.debug("[%s] noch nicht unterstützt: %s", self.manifest.id, ereignis)
            return

        ctx = self._kontexte.get(kontext)
        if ctx is not None:
            ctx.request_redraw()

    async def _von_der_seite(
        self, ereignis: str, nachricht: dict[str, Any], kontext: str, nutzlast: Any
    ) -> None:
        """Anweisungen einer Einstellungsseite.

        Die Seite ist fremdes HTML in einem abgeschotteten Rahmen. Sie darf
        genau das, was das Protokoll vorsieht: Einstellungen ihrer eigenen
        Belegung lesen und schreiben, mit dem Plugin reden, eine Adresse
        öffnen. Alles andere fällt hier durch.
        """
        aktion = self._aktion_von(kontext) or self._aktion_aus_belegung(kontext)

        if ereignis == "setSettings" and isinstance(nutzlast, dict):
            self._speichere(kontext, nutzlast)
            # Beide Seiten erfahren davon: das Plugin, damit es die Taste neu
            # zeichnet, die Seite, damit ihre Felder den gespeicherten Stand
            # zeigen.
            for ziel in (self.bruecke.sende, lambda e: self.bruecke.sende_an_inspektor(kontext, e)):
                await ziel({
                    "event": "didReceiveSettings", "action": aktion, "context": kontext,
                    "device": "DECKSWITCH", "payload": {"settings": nutzlast},
                })
        elif ereignis == "getSettings":
            await self.bruecke.sende_an_inspektor(kontext, {
                "event": "didReceiveSettings", "action": aktion, "context": kontext,
                "device": "DECKSWITCH", "payload": {"settings": self._einstellungen(kontext)},
            })
        elif ereignis == "setGlobalSettings" and isinstance(nutzlast, dict):
            self.plugin_config.update(nutzlast)
            self.services.runtime.save_config()
            await self.bruecke.sende({
                "event": "didReceiveGlobalSettings",
                "payload": {"settings": dict(self.plugin_config)},
            })
        elif ereignis == "getGlobalSettings":
            await self.bruecke.sende_an_inspektor(kontext, {
                "event": "didReceiveGlobalSettings",
                "payload": {"settings": dict(self.plugin_config)},
            })
        elif ereignis == "sendToPlugin":
            await self.bruecke.sende({
                "event": "sendToPlugin", "action": aktion, "context": kontext,
                "payload": nutzlast,
            })
        elif ereignis == "logMessage":
            log.info("[%s/PI] %s", self.manifest.id, (nutzlast or {}).get("message"))
        else:
            log.debug("[%s/PI] nicht unterstützt: %s", self.manifest.id, ereignis)

    def _belegung(self, kontext: str):
        """Die Belegung zu einer Kontext-Kennung ``seite:art:index``.

        Gesucht wird in der Konfiguration und nicht unter den bekannten
        Kontexten: Eine Einstellungsseite kann offen sein, bevor die Taste
        je gezeichnet wurde.
        """
        teile = kontext.split(":")
        if len(teile) < 3:
            return None
        seiten_id, art, index = teile[0], teile[1], teile[2]
        if not index.isdigit():
            return None
        for profil in self.services.config.profiles.values():
            seite = profil.pages.get(seiten_id)
            if seite is None:
                continue
            belegungen = seite.keys if art == "key" else seite.dials
            return belegungen.get(int(index))
        return None

    def _aktion_aus_belegung(self, kontext: str) -> str:
        belegung = self._belegung(kontext)
        return belegung.action_id if belegung is not None else ""

    def _einstellungen(self, kontext: str) -> dict[str, Any]:
        """Was zu dieser Belegung gespeichert ist.

        Gelesen wird an der Belegung und nicht am Kontext: Der Kontext trägt
        die Einstellungen nur mit, die Belegung besitzt sie. Beim Schreiben
        gehen sie an dieselbe Stelle, sonst zeigte die Seite einen Stand,
        den niemand mehr hat.
        """
        belegung = self._belegung(kontext)
        if belegung is None:
            ctx = self._kontexte.get(kontext)
            belegung = ctx.slot if ctx is not None else None
        if belegung is None:
            return {}
        return dict(belegung.settings.get("elgato") or {})

    def _speichere(self, kontext: str, werte: dict[str, Any]) -> None:
        """Einstellungen einer Belegung ablegen — und zwar dauerhaft."""
        belegung = self._belegung(kontext)
        if belegung is None:
            ctx = self._kontexte.get(kontext)
            belegung = ctx.slot if ctx is not None else None
        if belegung is None:
            log.debug("[%s] keine Belegung zu '%s'", self.manifest.id, kontext)
            return
        belegung.settings["elgato"] = werte
        self.services.runtime.save_config()
        ctx = self._kontexte.get(kontext)
        if ctx is not None:
            ctx.request_redraw()

    def _wechsle_profil(self, nutzlast: Any) -> None:
        """``switchToProfile`` — das Plugin will ein anderes Profil sehen.

        Bei Elgato bringen Plugins eigene Profile als Datei mit; die legt die
        Software beim Installieren an. Solche Dateien lesen wir nicht, also
        gilt: Ein leerer Name führt zurück zum vorigen Profil, ein Name, den
        es bei uns gibt, führt dorthin. Verlangt ein Plugin sein eigenes
        mitgebrachtes Profil, sagen wir das — statt stumm nichts zu tun.
        """
        name = str((nutzlast or {}).get("profile") or "").strip()
        if self.services.runtime.switch_profile(name):
            log.info("[%s] Profil gewechselt nach '%s'", self.manifest.id, name or "zurück")
            return
        if name:
            self.notify_info(
                f"'{localize(self.manifest.name)}' wollte auf das Profil '{name}' "
                "wechseln. Ein Profil dieses Namens gibt es hier nicht."
            )

    def _merke_meldung(self, kontext: str, art: str) -> None:
        import time
        self._meldungen[kontext] = (art, time.monotonic() + MELDUNG_S)

    def _aktion_von(self, kontext: str) -> str:
        ctx = self._kontexte.get(kontext)
        return ctx.action_id if ctx is not None else ""

    def _schreibe_einstellungen(self, kontext: str, nutzlast: Any) -> None:
        """``setSettings`` — das Plugin merkt sich etwas an einer Belegung.

        Abgelegt wird es unter ``elgato`` in unseren Slot-Einstellungen. Damit
        bleibt es beim Export sichtbar und wird beim nächsten Start wieder
        mitgeschickt, ohne sich mit unseren eigenen Feldern zu mischen.
        """
        if isinstance(nutzlast, dict):
            self._speichere(kontext, nutzlast)

    def _setze_bild(self, kontext: str, angabe: Any) -> None:
        if not isinstance(angabe, str) or not angabe:
            self._bilder.pop(kontext, None)
            return
        roh = angabe.split(",", 1)[1] if angabe.startswith("data:") else angabe
        try:
            daten = base64.b64decode(roh, validate=False)
            bild = Image.open(io.BytesIO(daten))
            bild.load()
        except Exception as exc:  # noqa: BLE001 — fremde Bytes
            log.debug("[%s] Bild nicht lesbar: %s", self.manifest.id, exc)
            return
        self._bilder[kontext] = bild.convert("RGBA")

    # -- Zeichnen ----------------------------------------------------------

    def get_label(self, action_id, settings, ctx):
        return self._titel.get(ctx.key)

    def render(self, action_id, settings, ctx):
        render = self.services.render

        # Über einem Dial hat das Plugin eine eigene Anzeige mit Titel, Wert
        # und Pegel. Sie hat Vorrang vor einem Tastenbild: Ein Plugin, das
        # beides schickt, meint auf dem Streifen die Anzeige.
        if ctx.input_type == "dial" and self._anzeige.get(ctx.key):
            layout = self._layout_fuer(action_id, ctx)
            if layout is not None:
                kachel = render.background(ctx.size, ctx.appearance, accent=AKZENT)
                zeichne_layout(kachel, layout, self._anzeige[ctx.key], self.ordner)
                meldung = self._meldungen.get(ctx.key)
                if meldung is not None:
                    render.draw_badge(
                        kachel, "#22c55e" if meldung[0] == "ok" else "#ef4444", width=4
                    )
                return kachel

        bild = self._bilder.get(ctx.key) or self._manifestbild(action_id, ctx)

        if bild is None:
            # Noch nichts geschickt: gewöhnliche Kachel, damit die Taste nicht
            # schwarz bleibt, während das Plugin startet.
            return render.render_slot(
                ctx, label_override=self._titel.get(ctx.key), accent=AKZENT
            )

        kachel = render.background(ctx.size, ctx.appearance, accent=AKZENT)
        passend = bild.copy()
        passend.thumbnail(ctx.size, Image.LANCZOS)
        kachel.alpha_composite(
            passend,
            ((ctx.size[0] - passend.width) // 2, (ctx.size[1] - passend.height) // 2),
        )

        titel = self._titel.get(ctx.key)
        if titel:
            render.compose(
                kachel, icon=None, label=titel,
                label_size=ctx.appearance.label_size,
                label_color=ctx.appearance.label_color,
                label_position=ctx.appearance.label_position,
                label_font=ctx.appearance.label_font,
                label_bold=ctx.appearance.label_bold,
                label_italic=ctx.appearance.label_italic,
                label_underline=ctx.appearance.label_underline,
                label_align=ctx.appearance.label_align,
            )

        meldung = self._meldungen.get(ctx.key)
        if meldung is not None:
            render.draw_badge(kachel, "#22c55e" if meldung[0] == "ok" else "#ef4444", width=4)
        return kachel

    def _layout_fuer(self, action_id: str, ctx: SlotContext) -> dict[str, Any] | None:
        """Welche Anordnung diese Anzeige benutzt.

        Zur Laufzeit gewählt schlägt Manifest; ein Name mit ``$`` meint eine
        von Elgatos Anordnungen, alles andere eine Datei im Plugin.
        """
        angabe = self._layoutwahl.get(ctx.key)
        if not angabe:
            for eintrag in self.elgato.get("Actions") or []:
                if eintrag.get("UUID") == action_id:
                    angabe = str((eintrag.get("Encoder") or {}).get("layout") or "")
                    break
        if not angabe:
            angabe = "$B1"

        if angabe.startswith("$"):
            return EINGEBAUTE_LAYOUTS.get(angabe) or EINGEBAUTE_LAYOUTS["$B1"]

        if angabe in self._layouts:
            return self._layouts[angabe]
        pfad = _datei(self.ordner, angabe)
        if pfad is None:
            log.debug("[%s] Layout '%s' liegt nicht im Plugin", self.manifest.id, angabe)
            return EINGEBAUTE_LAYOUTS["$B1"]
        try:
            layout = json.loads((self.ordner / pfad).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — fremde Datei
            log.debug("[%s] Layout '%s' unlesbar: %s", self.manifest.id, angabe, exc)
            return EINGEBAUTE_LAYOUTS["$B1"]
        self._layouts[angabe] = layout
        return layout

    def _manifestbild(self, action_id: str, ctx: SlotContext) -> Image.Image | None:
        """Das Bild aus dem Elgato-Manifest, solange das Plugin keines schickt."""
        for eintrag in self.elgato.get("Actions") or []:
            if eintrag.get("UUID") != action_id:
                continue
            zustaende = eintrag.get("States") or []
            nummer = min(self._zustaende.get(ctx.key, 0), max(0, len(zustaende) - 1))
            angabe = (zustaende[nummer].get("Image") if zustaende else None) or eintrag.get("Icon")
            pfad = _bildpfad(self.ordner, angabe)
            if pfad is None:
                return None
            try:
                with Image.open(self.ordner / pfad) as bild:
                    return bild.convert("RGBA")
            except Exception:  # noqa: BLE001
                return None
        return None
