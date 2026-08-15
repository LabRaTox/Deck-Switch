#!/usr/bin/env python
"""Generates a handful of ready-made touch strip wallpapers.

The strip is 800 x 100 pixels, so the motifs are built wide and flat and
have to survive being cut into four 200 x 100 segments. Anything with a
single centre of interest would end up hidden behind one dial, so these are
all patterns that read the same across the whole width.

    ./scripts/make-wallpapers.py

The files land in the user's upload folder and show up in the picker right
away. Delete them like any other upload if you do not want them.
"""

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from deckswitch import paths  # noqa: E402

WIDTH, HEIGHT = 800, 100
PREFIX = "wallpaper-"


def _canvas(colour=(0, 0, 0)) -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), colour)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(left, right) -> Image.Image:
    image = _canvas()
    draw = ImageDraw.Draw(image)
    for x in range(WIDTH):
        draw.line([(x, 0), (x, HEIGHT)], fill=_lerp(left, right, x / (WIDTH - 1)))
    return image


def aurora() -> Image.Image:
    """Soft bands of colour — quiet enough to put labels on top of."""
    image = gradient((10, 14, 40), (40, 12, 48))
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index, (colour, phase, amplitude) in enumerate(
        [((30, 110, 190), 0.0, 18), ((110, 50, 160), 1.7, 24), ((20, 140, 130), 3.1, 14)]
    ):
        points = [
            (x, HEIGHT / 2 + math.sin(x / 110 + phase) * amplitude + index * 6 - 8)
            for x in range(0, WIDTH + 1, 8)
        ]
        draw.line(points, fill=colour, width=26, joint="curve")
    overlay = overlay.filter(ImageFilter.GaussianBlur(22))
    return Image.blend(image, Image.blend(image, overlay, 0.85), 0.75)


def carbon() -> Image.Image:
    """Fine diagonal weave. Dark, so bright icons stand out."""
    image = _canvas((18, 18, 22))
    draw = ImageDraw.Draw(image)
    for x in range(-HEIGHT, WIDTH + HEIGHT, 8):
        draw.line([(x, 0), (x + HEIGHT, HEIGHT)], fill=(30, 30, 36), width=3)
        draw.line([(x, HEIGHT), (x + HEIGHT, 0)], fill=(25, 25, 30), width=3)
    return image


def grid() -> Image.Image:
    """Technical grid with a brighter line on every segment boundary."""
    image = _canvas((12, 16, 20))
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 25):
        draw.line([(x, 0), (x, HEIGHT)], fill=(24, 34, 44))
    for y in range(0, HEIGHT, 25):
        draw.line([(0, y), (WIDTH, y)], fill=(24, 34, 44))
    # Every 200 px a dial begins — showing that is useful, not decorative.
    # WIDTH itself is included so the right edge is framed like the left one;
    # drawn one pixel inwards, because a line centred on x=800 falls off the
    # canvas and would leave that edge bare.
    for x in range(0, WIDTH + 1, 200):
        px = min(x, WIDTH - 2)
        draw.rectangle([(px, 0), (px + 1, HEIGHT)], fill=(45, 80, 110))
    return image


def grid_depth() -> Image.Image:
    """The same grid, tipped into perspective — a floor running to a horizon.

    Depth needs a vanishing point, and a single one would sit between the
    middle two dials where it is hardest to see. Each 200 px segment gets its
    own instead, so every dial shows the same amount of depth and the strip
    still reads the same across its width.
    """
    image = _canvas((8, 11, 15))
    draw = ImageDraw.Draw(image)
    horizon = 32
    segment = 200

    # Sky: a faint band right above the horizon, so the floor has something
    # to run towards instead of ending in flat black.
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    ImageDraw.Draw(glow).rectangle(
        [(0, horizon - 12), (WIDTH, horizon + 2)], fill=(18, 46, 66)
    )
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(9)), 0.9)
    draw = ImageDraw.Draw(image)

    # Rails converging on each segment's vanishing point. They stop at the
    # segment border rather than fanning out across the whole strip: letting
    # neighbouring fans overlap draws diamonds where the lines cross, and the
    # eye reads those as a flat pattern instead of distance.
    for index in range(WIDTH // segment):
        vanish = index * segment + segment / 2
        for offset in range(-segment // 2, segment // 2 + 1, 25):
            draw.line(
                [(vanish, horizon), (vanish + offset, HEIGHT)],
                fill=(30, 46, 60),
            )

    # Floor lines on top of the rails. Squaring the step crowds them towards
    # the horizon, and the brightening towards the front is what carries the
    # depth once the rails are this sparse.
    rows = 11
    for i in range(1, rows + 1):
        t = i / rows
        y = horizon + (HEIGHT - horizon) * (t**2.1)
        shade = round(24 + 52 * t)
        draw.line([(0, y), (WIDTH, y)], fill=(shade, shade + 16, shade + 26))

    # Horizon and segment borders — the only bright lines, as in `grid`.
    draw.line([(0, horizon), (WIDTH, horizon)], fill=(70, 120, 155))
    for x in range(0, WIDTH + 1, segment):
        px = min(x, WIDTH - 2)
        draw.rectangle([(px, 0), (px + 1, HEIGHT)], fill=(45, 80, 110))
    return image


def sunset() -> Image.Image:
    return gradient((190, 70, 40), (60, 20, 90))


def deep_blue() -> Image.Image:
    return gradient((8, 24, 58), (12, 60, 92))


def graphite() -> Image.Image:
    """Almost black with a slow sheen — the least intrusive of the set."""
    image = gradient((14, 14, 16), (34, 34, 40))
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse((-200, -140, WIDTH + 200, HEIGHT + 40), fill=(60, 62, 74))
    overlay = overlay.filter(ImageFilter.GaussianBlur(40))
    return Image.blend(image, overlay, 0.35)


def scanlines() -> Image.Image:
    """Horizontal lines, the classic display look."""
    image = gradient((10, 30, 26), (8, 18, 30))
    draw = ImageDraw.Draw(image)
    for y in range(0, HEIGHT, 4):
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0))
    return image


WALLPAPERS = {
    "aurora": aurora,
    "carbon": carbon,
    "grid": grid,
    "grid-depth": grid_depth,
    "sunset": sunset,
    "deep-blue": deep_blue,
    "graphite": graphite,
    "scanlines": scanlines,
}


def main(argv: list[str]) -> int:
    wanted = set(argv[1:]) or set(WALLPAPERS)
    unknown = wanted - set(WALLPAPERS)
    if unknown:
        print(f"Unknown: {', '.join(sorted(unknown))}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(WALLPAPERS))}", file=sys.stderr)
        return 1

    paths.WALLPAPERS_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(wanted):
        target = paths.WALLPAPERS_DIR / f"{PREFIX}{name}.png"
        WALLPAPERS[name]().save(target)
        size = target.stat().st_size / 1024
        print(f"  ✔ {target.name}  ({WIDTH}x{HEIGHT}, {size:.0f} KB)")

    print(f"\n{len(wanted)} wallpaper(s) in {paths.WALLPAPERS_DIR}")
    print("  Pick one in the editor: select a page (no key) → Properties")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
