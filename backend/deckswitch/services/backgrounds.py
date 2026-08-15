"""Hintergründe für Tasten und Touchstrip-Segmente.

Wird immer *zuerst* gezeichnet, der Content der Action kommt darüber. Ohne
das wären die Dial-Segmente schlicht schwarz.

Bewusst kein eigenes Plugin — das ist eine Handvoll Pixel-Funktionen, die zum
Render-Service gehören.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from ..config import Background

DEFAULT_COLOR = "#000000"


def parse_color(value: str | None, fallback: tuple[int, int, int, int] = (0, 0, 0, 255)):
    """``#rgb`` / ``#rrggbb`` / ``#rrggbbaa`` → RGBA-Tupel."""
    if not value:
        return fallback
    text = value.strip().lstrip("#")
    try:
        if len(text) == 3:
            r, g, b = (int(c * 2, 16) for c in text)
            return (r, g, b, 255)
        if len(text) == 6:
            return (*(int(text[i : i + 2], 16) for i in (0, 2, 4)), 255)
        if len(text) == 8:
            return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4, 6))
    except ValueError:
        pass
    return fallback


def _mix(a, b, t: float):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))


def _darken(color, factor: float):
    return (
        round(color[0] * factor),
        round(color[1] * factor),
        round(color[2] * factor),
        color[3],
    )


@lru_cache(maxsize=64)
def _noise_layer(width: int, height: int, seed: str) -> Image.Image:
    """Reproduzierbares Rauschen ohne numpy-Abhängigkeit.

    Aus einem Hash gezogen, damit dasselbe Segment nicht bei jedem Frame
    flimmert.
    """
    digest = hashlib.sha256(seed.encode()).digest()
    total = width * height
    # Hash-Bytes zyklisch strecken und einmal weichzeichnen — reicht optisch
    # völlig für eine dezente Textur.
    data = bytes(digest[i % len(digest)] for i in range(total))
    layer = Image.frombytes("L", (width, height), data)
    return layer.filter(ImageFilter.GaussianBlur(0.6))


def render_background(
    size: tuple[int, int],
    background: Background | None,
    *,
    accent: str | None = None,
    upload_loader=None,
) -> Image.Image:
    """Erzeugt das Hintergrundbild einer Kachel.

    ``accent`` ist die Akzentfarbe der Action/des Plugins, die die Variante
    ``accent`` als schwachen Verlauf einsetzt (Audio bläulich, Discord
    lila …) — rein zur Wiedererkennung.
    """
    width, height = size
    background = background or Background()
    kind = background.kind

    if kind == "transparent":
        # Nichts zeichnen. Auf einem Touchstrip-Segment scheint dadurch das
        # Hintergrundbild der Seite durch; auf einer Taste, hinter der nichts
        # liegt, bleibt es schwarz — das ist dort dasselbe wie vorher.
        return Image.new("RGBA", size, (0, 0, 0, 0))

    if kind == "image" and background.upload and upload_loader is not None:
        image = upload_loader(background.upload)
        if image is not None:
            return _fit_cover(image.convert("RGBA"), size)
        kind = "solid"

    base = parse_color(background.color, (0, 0, 0, 255))

    if kind == "solid":
        return Image.new("RGBA", size, base)

    if kind == "gradient":
        return _gradient(size, base, parse_color(background.color2, (26, 26, 26, 255)),
                         background.direction)

    if kind == "noise":
        image = Image.new("RGBA", size, base)
        strength = max(0, min(100, background.intensity)) / 100 * 0.35
        if strength > 0:
            layer = _noise_layer(width, height, f"{width}x{height}")
            overlay = Image.new("RGBA", size, (255, 255, 255, 0))
            overlay.putalpha(layer.point(lambda v: int(v * strength)))
            image = Image.alpha_composite(image, overlay)
        return image

    if kind == "accent":
        tint = parse_color(background.accent or accent or "#3b82f6", (59, 130, 246, 255))
        # Dezent: dunkler Grundton, der zur Oberkante hin leicht Richtung
        # Akzentfarbe kippt. Soll das Icon nicht überstrahlen.
        top = _mix((14, 14, 16, 255), tint, 0.28)
        bottom = _darken(_mix((10, 10, 12, 255), tint, 0.06), 1.0)
        return _gradient(size, top, bottom, "vertical")

    return Image.new("RGBA", size, base)


def _gradient(size, start, end, direction: str) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    if direction == "horizontal":
        for x in range(width):
            draw.line([(x, 0), (x, height)], fill=_mix(start, end, x / max(1, width - 1)))
    else:
        for y in range(height):
            draw.line([(0, y), (width, y)], fill=_mix(start, end, y / max(1, height - 1)))
    return image


def _fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Bild formatfüllend skalieren und mittig beschneiden."""
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new = image.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))),
                       Image.LANCZOS)
    left = (new.width - target_w) // 2
    top = (new.height - target_h) // 2
    return new.crop((left, top, left + target_w, top + target_h))


#: Startvarianten, die die GUI im Hintergrund-Picker anbietet.
PRESETS: list[dict] = [
    {
        "id": "transparent",
        "name": {"de": "Transparent", "en": "Transparent"},
        "background": {"kind": "transparent"},
    },
    {
        "id": "dark",
        "name": {"de": "Dunkel", "en": "Dark"},
        "background": {"kind": "solid", "color": "#000000"},
    },
    {
        "id": "graphite",
        "name": {"de": "Graphit", "en": "Graphite"},
        "background": {"kind": "solid", "color": "#1c1c1f"},
    },
    {
        "id": "gradient-dark",
        "name": {"de": "Verlauf dunkel", "en": "Dark gradient"},
        "background": {
            "kind": "gradient",
            "color": "#2a2a2e",
            "color2": "#0a0a0b",
            "direction": "vertical",
        },
    },
    {
        "id": "noise",
        "name": {"de": "Textur", "en": "Texture"},
        "background": {"kind": "noise", "color": "#141416", "intensity": 14},
    },
    {
        "id": "accent",
        "name": {"de": "Akzent", "en": "Accent"},
        "background": {"kind": "accent", "accent": None},
    },
]
