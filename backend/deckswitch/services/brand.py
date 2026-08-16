"""Das App-Symbol — an einer Stelle definiert, an dreien verwendet.

Tray-Symbol, Favicon und das Logo in der Kopfzeile sollen dasselbe Bild
zeigen. Die Geometrie steht deshalb hier als reine Verhältniszahlen, und
beide Ausgabewege leiten sich daraus ab:

* :func:`icon_image` zeichnet mit Pillow — das braucht das Tray, das seine
  Symbole als Pixmap über D-Bus reicht.
* :func:`icon_svg` schreibt dieselben Rechtecke als SVG — das braucht die
  GUI. ``scripts/make-icon.py`` legt die Datei nach ``gui/public/``.

Das Motiv: drei mal zwei Tasten über einem Touchstrip, auf einem
abgerundeten Korpus mit Farbverlauf. Bewusst *nicht* die echten vier mal
zwei Tasten des Geräts — bei 16 Pixeln (Favicon) verschmelzen acht Tasten
zu einem Punktmuster, sechs bleiben lesbar.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# -- Farben ----------------------------------------------------------------

GRADIENT_TOP = (59, 130, 246)  # --accent der GUI
GRADIENT_BOTTOM = (139, 92, 246)
KEY_COLOR = (255, 255, 255)
#: Der Streifen tritt bewusst zurück — er ist Beiwerk, keine Taste.
STRIP_ALPHA = 185

#: Ohne Gerät wird das Symbol entsättigt statt umgeformt: Die Form bleibt
#: wiedererkennbar, der Zustand liest sich trotzdem auf einen Blick.
OFFLINE_GRAY = (122, 122, 132)
DIMMED_MIX = 0.55

# -- Geometrie (alles als Anteil der Kantenlänge) --------------------------

COLS, ROWS = 3, 2
CASE_RADIUS = 0.24
#: Abstand zwischen Korpusrand und Motiv.
PADDING = 0.17
GAP = 0.075          # relativ zur Motivbreite
KEY_RADIUS = 0.24    # relativ zur Tastenbreite
STRIP_HEIGHT = 0.42  # relativ zur Tastenbreite
STRIP_GAP = 1.1      # relativ zum Tastenabstand
STRIP_RADIUS = 0.4   # relativ zur Streifenhöhe

#: Ab dieser Kantenlänge (in Pixeln) bekommt eine Form runde Ecken. Darunter
#: bliebe von ihr nichts übrig: Ein Radius von einem Pixel schneidet aus
#: einer drei Pixel großen Taste alle vier Ecken heraus — übrig bleibt ein
#: Pluszeichen, und bei sechs Pixeln wirkt die Taste wie ein Kreis. Scharfe
#: Kanten sind in dieser Größe das kleinere Übel.
MIN_ROUNDED = 8


def _shapes(size: int) -> tuple[list[tuple[int, int, int, int, int]], tuple]:
    """Liefert (Tasten, Streifen) als ``(x, y, breite, höhe, radius)``.

    Alles ganzzahlig und aufs Pixelraster eingerastet. Das ist bei einem
    Tray-Symbol keine Kosmetik: Bei 22 Pixeln ist eine Taste vier Pixel
    breit und die Lücke daneben genau einen. Rechnet man in Bruchteilen,
    fällt diese Lücke beim Zeichnen weg und die sechs Tasten verschmelzen
    zu einem weißen Klotz.

    Die Maße sind Breite und Höhe — *nicht* Endkoordinaten. Pillow zeichnet
    Rechtecke einschließlich ihres Endpunkts, ein direkt durchgereichtes
    ``x + breite`` wäre also einen Pixel zu breit und würde ebenfalls die
    Lücken schließen.
    """
    padding = max(1, round(size * PADDING))
    span = size - 2 * padding

    gap = max(1, round(span * GAP))
    key = max(1, (span - (COLS - 1) * gap) // COLS)
    strip_height = max(1, round(key * STRIP_HEIGHT))
    strip_gap = max(1, round(gap * STRIP_GAP))
    radius = round(key * KEY_RADIUS) if key >= MIN_ROUNDED else 0

    # Was durch das Abrunden übrig bleibt, kommt gleichmäßig an die Ränder.
    used_width = COLS * key + (COLS - 1) * gap
    left = padding + (span - used_width) // 2

    block = ROWS * key + (ROWS - 1) * gap + strip_gap + strip_height
    top = padding + (span - block) // 2

    keys = [
        (left + col * (key + gap), top + row * (key + gap), key, key, radius)
        for row in range(ROWS)
        for col in range(COLS)
    ]

    strip = (
        left,
        top + ROWS * key + (ROWS - 1) * gap + strip_gap,
        used_width,
        strip_height,
        round(strip_height * STRIP_RADIUS) if strip_height >= MIN_ROUNDED else 0,
    )
    return keys, strip


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# -- Pillow (Tray) ---------------------------------------------------------


def icon_image(size: int, *, connected: bool = True, dimmed: bool = False) -> Image.Image:
    """Das Symbol als Bild — für das Tray über D-Bus."""
    if connected:
        top, bottom = GRADIENT_TOP, GRADIENT_BOTTOM
        if dimmed:
            top = _mix(top, OFFLINE_GRAY, DIMMED_MIX)
            bottom = _mix(bottom, OFFLINE_GRAY, DIMMED_MIX)
    else:
        top = bottom = OFFLINE_GRAY

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Verlauf zeilenweise zeichnen und mit der abgerundeten Form maskieren —
    # Pillow kann keinen Verlauf in ein rounded_rectangle füllen.
    gradient = Image.new("RGBA", (size, size))
    pen = ImageDraw.Draw(gradient)
    for row in range(size):
        t = row / max(1, size - 1)
        pen.line([(0, row), (size, row)], fill=(*_mix(top, bottom, t), 255))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * CASE_RADIUS), fill=255
    )
    image.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    keys, strip = _shapes(size)
    for x, y, width, height, radius in keys:
        # -1, weil Pillow den Endpunkt mitzeichnet.
        draw.rounded_rectangle(
            (x, y, x + width - 1, y + height - 1), radius=radius, fill=(*KEY_COLOR, 255)
        )

    # Der Streifen ist halbdurchsichtig und muss deshalb über den Korpus
    # *gemischt* werden. ``ImageDraw`` ersetzt die Pixel stattdessen — direkt
    # gezeichnet risse er ein halbtransparentes Loch ins Symbol, durch das im
    # Tray der Hintergrund der Leiste schiene.
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x, y, width, height, radius = strip
    ImageDraw.Draw(overlay).rounded_rectangle(
        (x, y, x + width - 1, y + height - 1), radius=radius, fill=(*KEY_COLOR, STRIP_ALPHA)
    )
    image.alpha_composite(overlay)
    return image


# -- SVG (GUI) -------------------------------------------------------------


def icon_svg(size: int = 64) -> str:
    """Dasselbe Symbol als SVG — Quelle für Favicon und Kopfzeilen-Logo."""
    keys, strip = _shapes(size)

    def rect(x, y, width, height, radius, opacity=1.0) -> str:
        # Kein -1 wie bei Pillow: SVG-Rechtecke haben eine echte Breite.
        attrs = (
            f'x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{radius}" fill="#ffffff"'
        )
        if opacity < 1.0:
            attrs += f' fill-opacity="{opacity:.3f}"'
        return f"  <rect {attrs}/>"

    body = "\n".join(rect(*k) for k in keys)
    body += "\n" + rect(*strip, opacity=STRIP_ALPHA / 255)

    top = "#%02x%02x%02x" % GRADIENT_TOP
    bottom = "#%02x%02x%02x" % GRADIENT_BOTTOM

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" \
width="{size}" height="{size}" role="img" aria-label="DECK//SWITCH">
  <defs>
    <linearGradient id="case" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{top}"/>
      <stop offset="1" stop-color="{bottom}"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{round(size * CASE_RADIUS)}" fill="url(#case)"/>
{body}
</svg>
"""
