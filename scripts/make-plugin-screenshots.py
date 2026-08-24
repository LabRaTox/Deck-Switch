#!/usr/bin/env python
"""Erzeugt die Bilder für die Detailansicht eines Plugins.

    ./scripts/make-plugin-screenshots.py            alle unter plugin-sources/
    ./scripts/make-plugin-screenshots.py weather    nur dieses

**Auf diesen Bildern steht nichts Erfundenes.** Jeder Name und jedes Symbol
stammt aus dem Manifest des Plugins: die Aktionen, ihre Zustände, deren
Symbole. Damit veralten die Bilder gemeinsam mit dem Plugin, statt eine
Fassung zu zeigen, die es längst nicht mehr gibt.

Hier standen einmal auch „Deck-Blätter" mit Beispielwerten — 18 Grad, ein
laufendes Lied, eine Aufnahme seit 12 Minuten. Die sind am 2026-08-23
ersatzlos geflogen: Ein Bild, das eine Szene „Kamera" zeigt, behauptet etwas
über ein fremdes OBS, das niemand geprüft hat. Was ein Plugin im Betrieb
anzeigt, hängt an Konten, Kanälen und Geräten, die dieses Skript nicht kennt
— und was es nicht kennt, malt es nicht.

Ein Schoner ist die Ausnahme, und zwar keine halbe: Er wird wirklich
ausgeführt. Was auf ``schoner.png`` steht, hat das Plugin selbst gezeichnet.

**Plugins, die ihre Kacheln selbst zeichnen, machen auch ihre Bilder selbst.**
Das Tastenfeld hier oben baut jede Kachel aus Symbol und Namen — richtig für
alle, die die gewöhnliche Darstellung nutzen, falsch für eines, das
``render`` überschreibt. Der Timer zeigt eine Uhrzeit, einen Balken und einen
farbigen Rahmen; ein Bild mit Sanduhr und dem Wort „Countdown" behauptete
etwas, das auf keinem Deck steht. Liegt im Plugin-Ordner ein
``screenshots.py`` mit einer Funktion ``erzeuge(ziel, werkzeug)``, wird die
gerufen und ihr Ergebnis genommen — das Plugin führt sich mit seinem eigenen
Zeichencode vor. ``werkzeug`` ist dieses Modul, damit Maße und Blattlayout
dieselben bleiben.
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
    rahmen_farbe=None,
    farbe=None,
    grund=None,
) -> Image.Image:
    """Eine einzelne Taste, wie das Deck sie zeigt.

    Die Teile sind dieselben, aus denen die Plugins ihre Tasten bauen: eine
    kleine Kopfzeile (``oben``), ein Symbol, eine große Zahl (``gross``), eine
    kräftige Zeile darüber (``mittel``), eine Beschriftung am unteren Rand, ein Pegelbalken und ein Rahmen für einen
    aktiven Zustand. Welche davon vorkommen, entscheidet das Beispiel — je
    nachdem, was das Plugin an dieser Stelle wirklich zeichnet.

    ``rahmen_farbe`` färbt allein den Rahmen. Das ist die Farbe, die
    ``draw_badge`` bekommt — und nur die: Ein Zustandsrahmen färbt im Betrieb
    weder die Kachelfläche noch den Text. Über ``farbe`` liefe genau das,
    denn sie tönt den Grund und die große Zahl mit.
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
            (1, 1, TASTE - 2, TASTE - 2),
            radius=RADIUS - 1,
            outline=(*(rahmen_farbe or farbe), 255),
            width=3,
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


def _text(wert) -> str:
    """Deutscher Text aus einem Manifest-Eintrag — oder was da steht."""
    if isinstance(wert, dict):
        return wert.get("de") or wert.get("en") or ""
    return str(wert or "")


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
        beschriftung = _text(aktionen[i].get("name"))
        _setze(blatt, _taste(aktionen[i].get("default_icon"), beschriftung, akzent), spalte, zeile)
    return blatt


def _zustaende_blatt(manifest: dict, akzent) -> Image.Image | None:
    """Die Zustände, in denen eine Taste ein anderes Symbol trägt.

    Alles darauf steht im Manifest: der Name der Aktion, der Name des
    Zustands, sein Symbol. Nichts ist erfunden — deshalb taugt dieses Blatt
    auch für Plugins, deren Tasten im Betrieb Namen aus einem fremden Konto
    tragen (Kanäle, Server, Szenen). Ein Bild mit ausgedachten Kanalnamen
    zeigte ein Discord, das es nicht gibt.

    Gezeigt werden nur Zustände mit eigenem Symbol. Ein Zustand, der sich
    allein durch einen Rahmen oder einen Schleier unterscheidet, sähe hier
    aus wie sein Nachbar — und woher der Rahmen seine Farbe nimmt, steht im
    Quelltext des Plugins und nicht im Manifest.
    """
    eintraege: list[tuple[str, str, str]] = []
    for aktion in manifest.get("actions") or []:
        zustaende = [z for z in aktion.get("states") or [] if z.get("default_icon")]
        if len(zustaende) < 2:
            # Ein einzelner Zustand sagt nichts: Er sieht aus wie die Aktion
            # selbst, und die steht schon auf dem anderen Blatt.
            continue
        for zustand in zustaende:
            eintraege.append((
                _text(aktion.get("name")),
                _text(zustand.get("name")),
                zustand["default_icon"],
            ))

    if not eintraege:
        return None

    zeilen = max(1, -(-len(eintraege) // SPALTEN))
    blatt = _blatt(zeilen)
    for i in range(zeilen * SPALTEN):
        spalte, zeile = i % SPALTEN, i // SPALTEN
        if i >= len(eintraege):
            _setze(blatt, _leere_taste(akzent), spalte, zeile)
            continue
        aktion, zustand, symbol = eintraege[i]
        _setze(blatt, _taste(symbol, zustand, akzent, oben=aktion), spalte, zeile)
    return blatt


def _schoner_blatt(ordner: Path, manifest: dict) -> Image.Image | None:
    """Der Schoner, wie er wirklich aussieht — vom Plugin selbst gezeichnet.

    Kein Nachbau: Das Plugin wird geladen und gerufen, genau wie im Betrieb.
    Die Uhr zeigt deshalb die Uhrzeit dieses Laufs. Anschließend wird die
    Leinwand so zerschnitten, wie die App es tut — sonst sähe man ein
    durchgehendes Bild statt acht Tasten und einen Streifen.
    """
    import importlib.util

    from deckswitch.config import default_config
    from deckswitch.plugins.base import Manifest, Services
    from deckswitch.services import screensaver as schoner
    from deckswitch.services.icons import IconService
    from deckswitch.services.render import RenderService

    eintrag = ordner / manifest.get("entry", "plugin.py")
    if not eintrag.is_file() or not manifest.get("class"):
        return None

    spec = importlib.util.spec_from_file_location(f"schoner_{manifest['id']}", eintrag)
    if spec is None or spec.loader is None:
        return None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    klasse = getattr(modul, manifest["class"], None)
    if klasse is None:
        return None

    icons = IconService()
    config = default_config()
    # Die Vorgaben aus dem Schema, wie sie eine frische Installation hätte.
    config.plugin_settings[manifest["id"]] = {
        feld["key"]: feld["default"]
        for feld in manifest.get("config_schema") or []
        if feld.get("default") is not None
    }
    dienste = Services(
        audio=None, icons=icons, render=RenderService(icons),
        runtime=None, config=config, plugin_dir=ordner,
    )

    plugin = klasse(Manifest.model_validate(manifest), dienste)
    # Dieselbe Geometrie wie am Stream Deck+: acht Tasten zu 120×120 und ein
    # Touchstrip von 800×100.
    layout = plugin.deck_layout = schoner.layout((120, 120), 8, STRIP_PIXEL)
    leinwand = plugin.render(layout.canvas, 0.0)
    tasten, streifen = schoner.split(leinwand, layout)

    blatt = _blatt(2, strip=True)
    for i, taste in enumerate(tasten[: 2 * SPALTEN]):
        _setze(blatt, taste.convert("RGBA"), i % SPALTEN, i // SPALTEN)
    links, breite, hoehe = RAND, _breite(), _strip_hoehe()
    blatt.paste(streifen.convert("RGB").resize((breite, hoehe), Image.LANCZOS),
                (links, blatt.height - RAND - hoehe))
    return blatt


def _eigene_bilder(ordner: Path, ziel: Path) -> list[str] | None:
    """Lässt das Plugin seine Bilder selbst machen, wenn es das anbietet."""
    datei = ordner / "screenshots.py"
    if not datei.is_file():
        return None

    import importlib.util

    spec = importlib.util.spec_from_file_location(f"bilder_{ordner.name}", datei)
    if spec is None or spec.loader is None:
        return None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    erzeuge = getattr(modul, "erzeuge", None)
    if erzeuge is None:
        print(f"  ! {ordner.name}: screenshots.py ohne erzeuge(), übersprungen")
        return None
    return list(erzeuge(ziel, sys.modules[__name__]))


def baue(ordner: Path) -> bool:
    datei = ordner / "manifest.json"
    if not datei.is_file():
        return False

    manifest = json.loads(datei.read_text(encoding="utf-8"))
    akzent = _parse(manifest.get("accent"))
    ziel = ordner / UNTERORDNER
    ziel.mkdir(exist_ok=True)

    bilder: list[str] = []

    eigene = _eigene_bilder(ordner, ziel)
    if eigene is not None:
        manifest["screenshots"] = eigene[:3]
        datei.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
        print(f"  ✔ {ordner.name:14} {len(eigene)} Bild(er) vom Plugin selbst: "
              f"{', '.join(eigene)}")
        return True

    if manifest.get("type") in ("screensaver", "wallpaper"):
        try:
            schoner = _schoner_blatt(ordner, manifest)
        except Exception as exc:  # noqa: BLE001 — ein Plugin darf hier scheitern
            print(f"  ! {ordner.name}: Schoner nicht zu zeichnen ({exc})")
            schoner = None
        if schoner is not None:
            schoner.save(ziel / "schoner.png")
            bilder.append(f"{UNTERORDNER}/schoner.png")

    if manifest.get("actions"):
        _aktionen_blatt(manifest, akzent).save(ziel / "aktionen.png")
        bilder.append(f"{UNTERORDNER}/aktionen.png")

    zustaende = _zustaende_blatt(manifest, akzent)
    if zustaende is not None:
        zustaende.save(ziel / "zustaende.png")
        bilder.append(f"{UNTERORDNER}/zustaende.png")

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
