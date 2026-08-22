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
TASTE = 132
LUECKE = 14
RAND = 28
RADIUS = 16

#: Der Touchstrip des Stream Deck+ ist 800×100 — hier im selben Verhältnis.
STRIP_HOEHE = 96


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


def _taste(symbol: str | None, text: str, akzent, gross: str = "") -> Image.Image:
    """Eine einzelne Taste, wie das Deck sie zeigt.

    ``gross`` ersetzt das Symbol durch eine große Zahl — so sieht eine Taste
    aus, die einen Wert anzeigt statt eines Zustands.
    """
    bild = Image.new("RGBA", (TASTE, TASTE), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)

    # Die Tastenfläche: fast schwarz, ein Hauch der Akzentfarbe darin.
    flaeche = _mix((24, 24, 28), akzent, 0.10)
    stift.rounded_rectangle((0, 0, TASTE - 1, TASTE - 1), radius=RADIUS, fill=(*flaeche, 255))

    hat_text = bool(text)
    if gross:
        schrift = _schrift(46, fett=True)
        breite = stift.textlength(gross, font=schrift)
        stift.text(
            ((TASTE - breite) / 2, TASTE / 2 - 34), gross, font=schrift, fill=(*akzent, 255)
        )
    else:
        glyph = _glyph(symbol, round(TASTE * (0.42 if hat_text else 0.52)))
        if glyph is not None:
            oben = round(TASTE * (0.16 if hat_text else 0.24))
            bild.alpha_composite(glyph, ((TASTE - glyph.width) // 2, oben))

    if hat_text:
        schrift = _schrift(15)
        # Lange Namen umbrechen statt abschneiden: Auf einer Taste steht
        # sonst „Zufallswiederg…“, und das hilft niemandem.
        worte, zeilen, zeile = text.split(), [], ""
        for wort in worte:
            versuch = f"{zeile} {wort}".strip()
            if stift.textlength(versuch, font=schrift) <= TASTE - 12:
                zeile = versuch
            else:
                if zeile:
                    zeilen.append(zeile)
                zeile = wort
        if zeile:
            zeilen.append(zeile)
        zeilen = zeilen[:2]

        y = TASTE - 12 - len(zeilen) * 17
        for eintrag in zeilen:
            breite = stift.textlength(eintrag, font=schrift)
            stift.text(((TASTE - breite) / 2, y), eintrag, font=schrift, fill=(226, 232, 240, 255))
            y += 17

    return bild


def _blatt(spalten: int, zeilen: int, strip: bool = False) -> Image.Image:
    breite = RAND * 2 + spalten * TASTE + (spalten - 1) * LUECKE
    hoehe = RAND * 2 + zeilen * TASTE + (zeilen - 1) * LUECKE
    if strip:
        hoehe += STRIP_HOEHE + LUECKE
    return Image.new("RGB", (breite, hoehe), HINTERGRUND)


def _setze(blatt: Image.Image, taste: Image.Image, spalte: int, zeile: int) -> None:
    blatt.paste(
        taste,
        (RAND + spalte * (TASTE + LUECKE), RAND + zeile * (TASTE + LUECKE)),
        taste,
    )


def _touchstrip(blatt: Image.Image, akzent, text: str, wert: str) -> None:
    """Der Streifen unter den Tasten — beim Stream Deck+ die zweite Ebene."""
    stift = ImageDraw.Draw(blatt)
    oben = blatt.height - RAND - STRIP_HOEHE
    stift.rounded_rectangle(
        (RAND, oben, blatt.width - RAND - 1, oben + STRIP_HOEHE - 1),
        radius=12,
        fill=(*_mix((20, 20, 24), akzent, 0.08), 255),
    )
    stift.text((RAND + 20, oben + 22), text, font=_schrift(17), fill=(148, 163, 184, 255))
    stift.text((RAND + 20, oben + 46), wert, font=_schrift(28, fett=True), fill=(*akzent, 255))


# --------------------------------------------------------------------------
# Die Bilder je Plugin
# --------------------------------------------------------------------------


def _aktionen_blatt(manifest: dict, akzent) -> Image.Image:
    """Alle Aktionen des Plugins als Tastenfeld."""
    aktionen = manifest.get("actions") or []
    spalten = min(4, max(1, len(aktionen)))
    zeilen = max(1, -(-len(aktionen) // spalten))

    blatt = _blatt(spalten, zeilen)
    for i, aktion in enumerate(aktionen):
        name = aktion.get("name")
        beschriftung = name.get("de") if isinstance(name, dict) else str(name or "")
        _setze(
            blatt,
            _taste(aktion.get("default_icon"), beschriftung, akzent),
            i % spalten,
            i // spalten,
        )
    return blatt


#: Was ein Plugin auf einer Taste zeigt, wenn es läuft. Beispielwerte — sie
#: stehen hier und nicht im Code der Bilder, damit sichtbar bleibt, dass sie
#: erfunden sind.
BEISPIELE = {
    "weather": [
        ("18°", "Berlin", "sun"),
        ("7 %", "Regen morgen", "cloud-rain"),
        ("42", "Luftqualität", "wind"),
    ],
    "spotify": [
        ("", "Sunrise Avenue", "player-pause"),
        ("", "Nächster Titel", "player-track-next"),
        ("65 %", "Lautstärke", "volume"),
    ],
    # Je eine Ziffer pro Taste — genau so, wie die Beschreibung es sagt.
    "clock-saver": [
        ("1", "", ""),
        ("4", "", ""),
        ("3", "", ""),
        ("5", "", ""),
    ],
}


def _beispiel_blatt(kennung: str, akzent) -> Image.Image | None:
    """Ein Blatt mit Beispielwerten — was im Betrieb auf den Tasten steht."""
    eintraege = BEISPIELE.get(kennung)
    if not eintraege:
        return None

    blatt = _blatt(len(eintraege), 1, strip=True)
    for i, (wert, beschriftung, symbol) in enumerate(eintraege):
        _setze(blatt, _taste(symbol, beschriftung, akzent, gross=wert), i, 0)

    strip = {
        "weather": ("Berlin · bedeckt", "18°   max 21°   min 11°"),
        "spotify": ("Sunrise Avenue — Fairytale Gone Bad", "2:31 / 3:14"),
        "clock-saver": ("Freitag, 22. August", "14:35"),
    }[kennung]
    _touchstrip(blatt, akzent, *strip)
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
