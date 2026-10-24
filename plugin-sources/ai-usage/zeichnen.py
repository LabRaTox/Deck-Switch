"""Zeichenbausteine für Tasten und Touchstrip.

Alle Maße richten sich nach der tatsächlichen Kachelgröße. Das Gerät hat
120 × 120 (Taste) und 200 × 100 (Segment), ein virtuelles Deck kann andere
Größen haben. ``scale`` liefert den Faktor, 1.0 entspricht 120 px Höhe.

Halbtransparente Flächen werden auf einer eigenen Ebene gezeichnet und mit
``alpha_composite`` aufgelegt, weil ``ImageDraw`` Pixel ersetzt und Alpha
nicht verrechnet.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from deckswitch.services.backgrounds import parse_color
from deckswitch.services.render import load_font

TRACK = "#3f3f46"
MUTED = "#9ca3af"
SOFT = "#c7c7d1"


def scale(size: tuple[int, int], base: int = 120) -> float:
    return max(0.4, size[1] / base)


def px(value: float, factor: float) -> int:
    return max(1, round(value * factor))


def ring(image: Image.Image, centre: tuple[float, float], radius: float, width: int,
         fraction: float | None, color: str) -> None:
    """Kreisring, im Uhrzeigersinn ab zwölf Uhr gefüllt."""
    draw = ImageDraw.Draw(image)
    cx, cy = centre
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(box, outline=parse_color(TRACK), width=width)
    if fraction is None:
        return
    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0:
        return
    if fraction >= 1:
        draw.ellipse(box, outline=parse_color(color), width=width)
        return
    draw.arc(box, start=-90, end=-90 + 360 * fraction, fill=parse_color(color), width=width)


def bar(image: Image.Image, box: tuple[int, int, int, int], fraction: float | None,
        color: str) -> None:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    radius = max(1, (y1 - y0) // 2)
    draw.rounded_rectangle(box, radius=radius, fill=parse_color(TRACK))
    if fraction is None:
        return
    filled = round((x1 - x0) * max(0.0, min(1.0, fraction)))
    if filled >= 2:
        draw.rounded_rectangle((x0, y0, x0 + filled, y1), radius=radius, fill=parse_color(color))


def tint(image: Image.Image, color: str, strength: int = 70) -> None:
    """Färbt den Hintergrund leicht in der Zustandsfarbe ein. Der Text bleibt lesbar."""
    r, g, b, _ = parse_color(color)
    layer = Image.new("RGBA", image.size, (r, g, b, max(0, min(255, strength))))
    image.alpha_composite(layer)


def dim(image: Image.Image, strength: int = 140) -> None:
    image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, strength)))


def pulse_frame(image: Image.Image, color: str, width: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1),
        radius=max(4, image.width // 12),
        outline=parse_color(color),
        width=width,
    )


def dot(image: Image.Image, centre: tuple[int, int], radius: int, color: str) -> None:
    cx, cy = centre
    ImageDraw.Draw(image).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                  fill=parse_color(color))


def wrap(text: str, size: int, max_width: int, *, lines: int = 2, bold: bool = False) -> list[str]:
    """Bricht ``text`` auf höchstens ``lines`` Zeilen um, der Rest wird gekürzt."""
    font = load_font(max(6, size), bold=bold)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words = text.split()
    result: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if measure.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            result.append(current)
            current = word
            if len(result) == lines:
                break
    if current and len(result) < lines:
        result.append(current)
    if len(result) == lines and " ".join(result) != " ".join(words):
        # Der Text war zu lang. Die letzte Zeile endet deshalb mit „…“.
        last = result[-1]
        while last and measure.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        result[-1] = last.rstrip() + "…"
    return result
