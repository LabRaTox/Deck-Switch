#!/usr/bin/env python
"""Erzeugt die Bilder für die Detailansicht eines Plugins.

    ./scripts/make-plugin-screenshots.py            alle unter plugin-sources/
    ./scripts/make-plugin-screenshots.py weather    nur dieses

**Was diese Bilder sind — und was nicht.** Sie zeigen, wie die Tasten eines
Plugins aussehen: dieselben Symbole, dieselbe Akzentfarbe, dieselbe Schrift
wie im Betrieb. Sie sind aber *gebaut* und nicht abfotografiert — es läuft
kein Deck dabei, und die Werte darauf sind Beispiele. Ein Wetter-Plugin ohne
Netz kann nun einmal keine echten 18 Grad anzeigen.

Alles, was auf den Bildern steht, stammt aus dem Manifest: die Aktionen, ihre
Namen, ihre Symbole. Damit veralten die Bilder gemeinsam mit dem Plugin,
statt eine Fassung zu zeigen, die es längst nicht mehr gibt.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Das Rastern der SVGs braucht cairosvg, das in der Projektumgebung liegt und
# nicht im System-Python. Statt jedem Aufrufer den richtigen Interpreter
# aufzubürden, wechseln wir hier hinein.
VENV = REPO / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
if VENV_PYTHON.is_file() and Path(sys.prefix).resolve() != VENV.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(REPO / "backend"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SEARCH = [REPO / "plugin-sources", REPO / "backend" / "plugins"]
ICONSET = REPO / "backend" / "plugins" / "iconset-tabler" / "icons"

#: Der Ordner im Plugin, in dem die Bilder landen.
UNTERORDNER = "screenshots"

#: Ein Deck ist dunkel und die Tasten sind quadratisch — das Bild soll
#: aussehen wie das Gerät und nicht wie eine Webseite.
HINTERGRUND = (16, 16, 20)
TASTE = 150
LUECKE = 14
RAND = 28
RADIUS = 16

#: Das Stream Deck+ hat vier Spalten. Ein Blatt mit drei Tasten nebeneinander
#: sähe nach einem Gerät aus, das es nicht gibt — und der Streifen darunter
#: hätte die falsche Breite.
SPALTEN = 4

#: Der Touchstrip ist ein einziger Bildschirm von 800×100, den die App in
#: vier Segmente teilt — eines je Dial. Ein Plugin auf einem Dial zeichnet
#: also in 200×100 und nicht über die ganze Breite. Beides steht in
#: ``device.py`` (``touchscreen_size``, ``segment_size``).
STRIP_PIXEL = (800, 100)
SEGMENTE = 4


def _parse(colour: str, vorgabe=(75, 85, 99)):
    text = (colour or "").lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return vorgabe


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _schrift(groesse: int, fett: bool = False):
    """Die Schrift der Oberfläche, sonst die von PIL."""
    from deckswitch.services.render import load_font

    try:
        return load_font(size=groesse, bold=fett)
    except Exception:
        return ImageFont.load_default(groesse)


def _glyph(name: str, groesse: int, farbe="#ffffff"):
    """Ein Tabler-Symbol als Bild — oder ``None``."""
    if not name:
        return None
    quelle = ICONSET / f"{name}.svg"
    if not quelle.is_file():
        return None

    import io

    import cairosvg

    # Tabler zeichnet in currentColor — die Farbe wird vor dem Rastern gesetzt.
    markup = quelle.read_text(encoding="utf-8").replace("<svg", f'<svg color="{farbe}"', 1)
    try:
        png = cairosvg.svg2png(
            bytestring=markup.encode(), output_width=groesse, output_height=groesse
        )
    except Exception:
        return None
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _taste(
    symbol: str | None,
    text: str,
    akzent,
    gross: str = "",
    oben: str = "",
    mittel: str = "",
    balken: float | None = None,
    rahmen: bool = False,
    farbe=None,
    grund=None,
) -> Image.Image:
    """Eine einzelne Taste, wie das Deck sie zeigt.

    Die Teile sind dieselben, aus denen die Plugins ihre Tasten bauen: eine
    kleine Kopfzeile (``oben``), ein Symbol, eine große Zahl (``gross``), eine
    kräftige Zeile darüber (``mittel``), eine Beschriftung am unteren Rand, ein Pegelbalken und ein Rahmen für einen
    aktiven Zustand. Welche davon vorkommen, entscheidet das Beispiel — je
    nachdem, was das Plugin an dieser Stelle wirklich zeichnet.
    """
    bild = Image.new("RGBA", (TASTE, TASTE), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)
    farbe = farbe or akzent

    # Die Tastenfläche: fast schwarz, ein Hauch der Akzentfarbe darin. Ein
    # Bildschirmschoner bekommt das Deck als ein Bild und schwärzt es — der
    # gibt seinen eigenen Grund vor.
    flaeche = grund if grund else _mix((24, 24, 28), farbe, 0.10)
    stift.rounded_rectangle((0, 0, TASTE - 1, TASTE - 1), radius=RADIUS, fill=(*flaeche, 255))

    # Von unten nach oben: Beschriftung sitzt am Rand, alles andere füllt den
    # Platz darüber. So bleiben Tasten mit und ohne Zahl auf einer Höhe.
    unterkante = TASTE - 12 - (10 if balken is not None else 0)

    zeilen: list[str] = []
    if text:
        schrift_text = _schrift(15)
        zeile = ""
        for wort in text.split():
            versuch = f"{zeile} {wort}".strip()
            # Lange Namen umbrechen statt abschneiden: Auf einer Taste steht
            # sonst „Zufallswiederg…“, und das hilft niemandem.
            if stift.textlength(versuch, font=schrift_text) <= TASTE - 12:
                zeile = versuch
            else:
                if zeile:
                    zeilen.append(zeile)
                zeile = wort
        if zeile:
            zeilen.append(zeile)
        zeilen = zeilen[:2]

    raum_unten = unterkante - len(zeilen) * 17 - (24 if mittel else 0)
    raum_oben = 8
    if oben:
        stift.text(
            ((TASTE - stift.textlength(oben, font=_schrift(13))) / 2, raum_oben),
            oben,
            font=_schrift(13),
            fill=(199, 199, 209, 255),
        )
        raum_oben += 20

    glyph = None
    if symbol and not (gross and not oben and not zeilen):
        kleiner = bool(gross or oben or zeilen)
        glyph = _glyph(symbol, round(TASTE * (0.36 if gross else 0.42 if kleiner else 0.52)))

    schrift_gross = _schrift(38 if glyph is not None else 46, fett=True)
    hoehe_gross = 42 if gross else 0
    hoehe_glyph = glyph.height + (6 if gross else 0) if glyph is not None else 0

    y = raum_oben + max(0, (raum_unten - raum_oben - hoehe_glyph - hoehe_gross)) // 2
    if glyph is not None:
        bild.alpha_composite(glyph, ((TASTE - glyph.width) // 2, round(y)))
        y += hoehe_glyph
    if gross:
        stift.text(
            ((TASTE - stift.textlength(gross, font=schrift_gross)) / 2, y),
            gross,
            font=schrift_gross,
            fill=(*farbe, 255),
        )

    y = unterkante - len(zeilen) * 17 - (24 if mittel else 0)
    if mittel:
        breite = stift.textlength(mittel, font=_schrift(19, fett=True))
        stift.text(
            ((TASTE - breite) / 2, y), mittel, font=_schrift(19, fett=True), fill=(240, 244, 248, 255)
        )
        y += 24
    for eintrag in zeilen:
        breite = stift.textlength(eintrag, font=_schrift(15))
        stift.text(((TASTE - breite) / 2, y), eintrag, font=_schrift(15), fill=(226, 232, 240, 255))
        y += 17

    if balken is not None:
        # Dieselbe Geometrie wie ``render.draw_bar``: zehn Pixel Abstand zu
        # den Seiten, sechs Pixel hoch, direkt über der unteren Kante.
        links, rechts = 10, TASTE - 10
        kopf, fuss = TASTE - 16, TASTE - 10
        stift.rounded_rectangle((links, kopf, rechts, fuss), radius=3, fill=(255, 255, 255, 38))
        breite = round((rechts - links) * max(0.0, min(1.0, balken)))
        if breite > 3:
            stift.rounded_rectangle(
                (links, kopf, links + breite, fuss), radius=3, fill=(*farbe, 255)
            )

    if rahmen:
        stift.rounded_rectangle(
            (1, 1, TASTE - 2, TASTE - 2), radius=RADIUS - 1, outline=(*farbe, 255), width=3
        )

    return bild


def _breite() -> int:
    """Die Innenbreite eines Blattes — vier Tasten und die Lücken dazwischen."""
    return SPALTEN * TASTE + (SPALTEN - 1) * LUECKE


def _strip_hoehe() -> int:
    """Der Streifen im Verhältnis des echten: 800 breit, 100 hoch."""
    return round(_breite() * STRIP_PIXEL[1] / STRIP_PIXEL[0])


def _blatt(zeilen: int, strip: bool = False) -> Image.Image:
    breite = RAND * 2 + _breite()
    hoehe = RAND * 2 + zeilen * TASTE + (zeilen - 1) * LUECKE
    if strip:
        hoehe += _strip_hoehe() + LUECKE
    return Image.new("RGB", (breite, hoehe), HINTERGRUND)


def _setze(blatt: Image.Image, taste: Image.Image, spalte: int, zeile: int) -> None:
    blatt.paste(
        taste,
        (RAND + spalte * (TASTE + LUECKE), RAND + zeile * (TASTE + LUECKE)),
        taste,
    )


def _leere_taste(akzent, grund=None) -> Image.Image:
    """Eine Taste, auf der nichts liegt. Gehört dazu: Ein Deck hat acht."""
    bild = Image.new("RGBA", (TASTE, TASTE), (0, 0, 0, 0))
    ImageDraw.Draw(bild).rounded_rectangle(
        (0, 0, TASTE - 1, TASTE - 1),
        radius=RADIUS,
        fill=(*(grund if grund else _mix((20, 20, 23), akzent, 0.04)), 255),
    )
    return bild


def _streifen(
    blatt: Image.Image, akzent, geteilt: bool = True, grund=None
) -> tuple[int, int, int, int]:
    """Zeichnet den Touchstrip und gibt sein Rechteck zurück.

    ``geteilt`` zieht die Trennlinien zwischen den vier Segmenten ein. Ein
    Bildschirmschoner malt über den ganzen Streifen und braucht sie nicht —
    ein Plugin auf einem Dial hat nur sein Viertel.
    """
    stift = ImageDraw.Draw(blatt)
    links, breite, hoehe = RAND, _breite(), _strip_hoehe()
    oben = blatt.height - RAND - hoehe
    stift.rounded_rectangle(
        (links, oben, links + breite - 1, oben + hoehe - 1),
        radius=10,
        fill=(*(grund if grund else _mix((20, 20, 24), akzent, 0.08)), 255),
    )
    if geteilt:
        for i in range(1, SEGMENTE):
            x = links + round(breite * i / SEGMENTE)
            stift.line((x, oben + 6, x, oben + hoehe - 6), fill=(255, 255, 255, 22))
    return links, oben, breite, hoehe


def _segment(blatt: Image.Image, akzent, nummer: int) -> tuple[int, int, int, int, float]:
    """Das Rechteck eines Segments samt Maßstab zu den echten 200×100."""
    links, oben, breite, hoehe = _streifen(blatt, akzent)
    seg = breite / SEGMENTE
    return (
        round(links + seg * nummer),
        oben,
        round(seg),
        hoehe,
        hoehe / STRIP_PIXEL[1],
    )


def _segment_medien(blatt, akzent, symbol: str, titel: str, kuenstler: str) -> None:
    """Was Spotify auf einem Dial zeigt: Symbol links, Titel, Künstler.

    Im Betrieb liegt dahinter noch das Albumbild, weichgezeichnet. Das hier
    zeigt den Fall ohne Cover — ein erfundenes Album wäre ein fremdes Bild in
    unserem Repository.
    """
    x, y, breite, hoehe, f = _segment(blatt, akzent, 0)
    stift = ImageDraw.Draw(blatt)

    glyph = _glyph(symbol, round(55 * f))
    if glyph is not None:
        blatt.paste(glyph, (x + round(10 * f), y + (hoehe - glyph.height) // 2), glyph)

    text = x + round(75 * f)
    platz = breite - round(87 * f)
    stift.text((text, y + round(14 * f)), _kuerze(stift, titel, _schrift(round(16 * f)), platz),
               font=_schrift(round(16 * f)), fill=(240, 244, 248, 255))
    stift.text((text, y + round(36 * f)), _kuerze(stift, kuenstler, _schrift(round(13 * f)), platz),
               font=_schrift(round(13 * f)), fill=(199, 199, 209, 255))


def _segment_wetter(blatt, akzent, symbol: str, kopf: str, gross: str, rechts: str) -> None:
    """Und was das Wetter auf einem Dial zeigt: die Stundenansicht."""
    x, y, breite, hoehe, f = _segment(blatt, akzent, 0)
    stift = ImageDraw.Draw(blatt)

    glyph = _glyph(symbol, round(56 * f))
    if glyph is not None:
        blatt.paste(glyph, (x + round(10 * f), y + (hoehe - glyph.height) // 2), glyph)

    links = x + round(76 * f)
    platz = breite - round(88 * f)
    stift.text((links, y + round(8 * f)), _kuerze(stift, kopf, _schrift(round(12 * f)), platz),
               font=_schrift(round(12 * f)), fill=(199, 199, 209, 255))
    stift.text((links, y + round(30 * f)), gross, font=_schrift(round(24 * f), fett=True),
               fill=(226, 232, 240, 255))

    schrift = _schrift(round(12 * f))
    stift.text((x + breite - round(12 * f) - stift.textlength(rechts, font=schrift),
                y + round(36 * f)), rechts, font=schrift, fill=(147, 197, 253, 255))


def _streifen_text(blatt, akzent, text: str, grund=None) -> None:
    """Ein Wort über den ganzen Streifen — so macht es der Bildschirmschoner.

    Er bekommt das Deck als *ein* Bild und darf überall hinmalen. Das ist der
    einzige Fall, in dem eine Darstellung über die Segmentgrenzen geht.
    """
    _, oben, breite, hoehe = _streifen(blatt, akzent, geteilt=False, grund=grund)
    stift = ImageDraw.Draw(blatt)
    schrift = _schrift(round(hoehe * 0.5), fett=True)
    stift.text(
        (RAND + (breite - stift.textlength(text, font=schrift)) / 2, oben + hoehe * 0.22),
        text,
        font=schrift,
        fill=(226, 232, 240, 160),
    )


def _kuerze(stift, text: str, schrift, platz: int) -> str:
    """Kürzt mit Auslassungszeichen, wie es die Anzeige auch tut."""
    if stift.textlength(text, font=schrift) <= platz:
        return text
    while text and stift.textlength(text + "…", font=schrift) > platz:
        text = text[:-1]
    return text + "…"


# --------------------------------------------------------------------------
# Die Bilder je Plugin
# --------------------------------------------------------------------------


def _aktionen_blatt(manifest: dict, akzent) -> Image.Image:
    """Alle Aktionen des Plugins als Tastenfeld."""
    aktionen = manifest.get("actions") or []
    zeilen = max(1, -(-len(aktionen) // SPALTEN))

    blatt = _blatt(zeilen)
    for i in range(zeilen * SPALTEN):
        spalte, zeile = i % SPALTEN, i // SPALTEN
        if i >= len(aktionen):
            _setze(blatt, _leere_taste(akzent), spalte, zeile)
            continue
        name = aktionen[i].get("name")
        beschriftung = name.get("de") if isinstance(name, dict) else str(name or "")
        _setze(blatt, _taste(aktionen[i].get("default_icon"), beschriftung, akzent), spalte, zeile)
    return blatt


#: Was ein Plugin auf einem laufenden Deck zeigt.
#:
#: Die Werte sind erfunden — es gibt keine 18 Grad und kein laufendes Lied,
#: während dieses Skript läuft. Der Aufbau ist es nicht: Was hier steht, hält
#: sich an das, was ``render()`` im jeweiligen Plugin zeichnet. Die
#: Wiedergabe-Taste zeigt deshalb den Titel und nicht den Künstler (Vorgabe
#: von ``show_track``), die Lautstärke hat einen Balken statt einer
#: Prozentzahl, und was auf einem Dial läuft, füllt ein Viertel des Streifens
#: und nicht den ganzen.
BEISPIELE = {
    "weather": {
        # _render_current_key, _render_forecast_key, _render_air_key
        "tasten": [
            {"symbol": "cloud", "gross": "18°", "text": "bedeckt"},
            {"oben": "Sa", "symbol": "cloud-rain", "mittel": "21° / 11°", "text": "40 % Regen"},
            {"oben": "AQI", "gross": "42", "text": "Gut", "farbe": (34, 197, 94)},
        ],
        # _render_hourly — die Vorgabe für ein Dial-Segment
        "segment": ("wetter", "cloud", "Berlin · 14:00", "18°", "40 % Regen"),
    },
    "spotify": {
        # Die Wiedergabe läuft: Titel als Beschriftung, Akzentrahmen darum.
        # „Nächster Titel“ und „Lautstärke“ tragen den Namen, den man der
        # Taste selbst gibt — das Plugin liefert dort keine Beschriftung.
        "tasten": [
            {"symbol": "player-pause", "text": "Fairytale Gone Bad", "rahmen": True},
            {"symbol": "player-track-prev", "text": "Vorheriger Titel"},
            {"symbol": "player-track-next", "text": "Nächster Titel"},
            {"symbol": "volume", "text": "Lautstärke", "balken": 0.65},
        ],
        # _render_multimedia
        "segment": ("medien", "player-pause", "Fairytale Gone Bad", "Sunrise Avenue"),
    },
    # Der Bildschirmschoner malt über das ganze Deck: obere Reihe Uhrzeit,
    # untere das Datum, je eine Ziffer pro Taste, und der Wochentag über den
    # Streifen.
    "clock-saver": {
        # Schwarz und ein helles Grau — die Vorgaben des Schoners, nicht die
        # Akzentfarbe des Plugins.
        "grund": (0, 0, 0),
        "farbe": (226, 232, 240),
        "tasten": [
            {"gross": "1"}, {"gross": "4"}, {"gross": "3"}, {"gross": "5"},
            {"gross": "2"}, {"gross": "2"}, {"gross": "0"}, {"gross": "8"},
        ],
        "segment": ("ganz", "Freitag"),
    },
}


def _beispiel_blatt(kennung: str, akzent) -> Image.Image | None:
    """Ein Blatt mit Beispielwerten — was im Betrieb auf dem Deck steht."""
    beispiel = BEISPIELE.get(kennung)
    if not beispiel:
        return None

    grund = beispiel.get("grund")
    vorgabe = beispiel.get("farbe")
    tasten = beispiel["tasten"]
    zeilen = max(1, -(-len(tasten) // SPALTEN))
    blatt = _blatt(zeilen, strip=True)

    for i in range(zeilen * SPALTEN):
        spalte, zeile = i % SPALTEN, i // SPALTEN
        if i >= len(tasten):
            _setze(blatt, _leere_taste(akzent, grund), spalte, zeile)
            continue
        taste = tasten[i]
        _setze(
            blatt,
            _taste(
                taste.get("symbol"),
                taste.get("text", ""),
                akzent,
                gross=taste.get("gross", ""),
                oben=taste.get("oben", ""),
                mittel=taste.get("mittel", ""),
                balken=taste.get("balken"),
                rahmen=taste.get("rahmen", False),
                farbe=taste.get("farbe", vorgabe),
                grund=grund,
            ),
            spalte,
            zeile,
        )

    art, *rest = beispiel["segment"]
    if art == "medien":
        _segment_medien(blatt, akzent, *rest)
    elif art == "wetter":
        _segment_wetter(blatt, akzent, *rest)
    else:
        _streifen_text(blatt, akzent, *rest, grund=grund)
    return blatt


def baue(ordner: Path) -> bool:
    datei = ordner / "manifest.json"
    if not datei.is_file():
        return False

    manifest = json.loads(datei.read_text(encoding="utf-8"))
    akzent = _parse(manifest.get("accent"))
    ziel = ordner / UNTERORDNER
    ziel.mkdir(exist_ok=True)

    bilder: list[str] = []

    beispiel = _beispiel_blatt(manifest["id"], akzent)
    if beispiel is not None:
        beispiel.save(ziel / "deck.png")
        bilder.append(f"{UNTERORDNER}/deck.png")

    if manifest.get("actions"):
        _aktionen_blatt(manifest, akzent).save(ziel / "aktionen.png")
        bilder.append(f"{UNTERORDNER}/aktionen.png")

    if not bilder:
        print(f"  – {ordner.name}: nichts zu zeigen")
        return False

    # Höchstens drei nimmt die Detailansicht an — mehr wäre eine Diashow.
    manifest["screenshots"] = bilder[:3]
    datei.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  ✔ {ordner.name:14} {len(bilder)} Bild(er): {', '.join(bilder)}")
    return True


def main(argv: list[str]) -> int:
    if not ICONSET.is_dir():
        print(f"Symbolsatz nicht gefunden: {ICONSET}", file=sys.stderr)
        return 1

    gewuenscht = set(argv)
    gebaut = 0
    for wurzel in SEARCH:
        if not wurzel.is_dir():
            continue
        for ordner in sorted(p for p in wurzel.iterdir() if p.is_dir()):
            if gewuenscht and ordner.name not in gewuenscht:
                continue
            if not gewuenscht and wurzel.name != "plugin-sources":
                continue
            if baue(ordner):
                gebaut += 1

    print(f"\n{gebaut} Plugin(s) mit Bildern versehen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
