#!/usr/bin/env python
"""Generates the 256x256 icons for the bundled plugins.

Third-party plugins bring their own ``icon`` file; the bundled ones would
otherwise be the only ones without a face. Each icon is built from what the
manifest already declares — the plugin's accent colour plus the symbol of
its first action — so the overview stays coherent instead of looking like a
collection of unrelated logos.

    ./scripts/make-plugin-icons.py            all bundled plugins
    ./scripts/make-plugin-icons.py audio obs  only these
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Rasterising SVGs needs cairosvg, which lives in the project venv rather
# than in the system Python. Re-exec there instead of making every caller
# remember the right interpreter.
VENV = REPO / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
# Compare sys.prefix, not the interpreter path: .venv/bin/python is a symlink
# to the system interpreter, so resolving both makes them look identical and
# the re-exec would never happen.
if VENV_PYTHON.is_file() and Path(sys.prefix).resolve() != VENV.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(REPO / "backend"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

SIZE = 256
FILENAME = "icon.png"

#: Wie beim App-Symbol: abgerundetes Quadrat mit Verlauf, Motiv in Weiss.
CORNER_RADIUS = 0.22
GLYPH_SCALE = 0.52

SEARCH = [REPO / "backend" / "plugins", REPO / "plugin-sources"]

#: Fallback symbol for plugin types that have no actions to borrow from.
BY_TYPE = {
    "iconset": "palette",
    "screensaver": "photo",
    "wallpaper": "picture-in-picture",
}


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _parse(colour: str):
    text = (colour or "#4b5563").lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (75, 85, 99)


def _case(accent) -> Image.Image:
    """Abgerundetes Quadrat, oben die Akzentfarbe, unten abgedunkelt."""
    top = accent
    bottom = _mix(accent, (12, 12, 16), 0.55)

    gradient = Image.new("RGBA", (SIZE, SIZE))
    pen = ImageDraw.Draw(gradient)
    for row in range(SIZE):
        pen.line([(0, row), (SIZE, row)], fill=(*_mix(top, bottom, row / (SIZE - 1)), 255))

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, SIZE - 1, SIZE - 1), radius=round(SIZE * CORNER_RADIUS), fill=255
    )
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    image.paste(gradient, (0, 0), mask)
    return image


def _glyph(name: str, iconset: Path) -> Image.Image | None:
    """Rasters a Tabler SVG in white.

    Uses cairosvg directly rather than the app's IconService: that one only
    exposes rasterising through a private helper, and a build script has no
    business depending on internals.
    """
    if not name:
        return None
    source = iconset / f"{name}.svg"
    if not source.is_file():
        return None

    import io

    import cairosvg

    # Tabler icons are stroked in currentColor — set it before rasterising.
    markup = source.read_text(encoding="utf-8").replace(
        "<svg", '<svg color="#ffffff"', 1
    )
    target = round(SIZE * GLYPH_SCALE)
    try:
        png = cairosvg.svg2png(
            bytestring=markup.encode(), output_width=target, output_height=target
        )
    except Exception:
        return None
    return Image.open(io.BytesIO(png)).convert("RGBA")


def build(directory: Path, iconset: Path) -> bool:
    manifest_file = directory / "manifest.json"
    if not manifest_file.is_file():
        return False
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    accent = _parse(manifest.get("accent"))
    image = _case(accent)

    # An explicit icon_symbol wins; otherwise borrow the first action's
    # symbol. Plugin types without actions get a symbol for their kind.
    symbol = manifest.get("icon_symbol")
    if not symbol:
        actions = manifest.get("actions") or []
        symbol = actions[0].get("default_icon") if actions else None
    if not symbol:
        symbol = BY_TYPE.get(manifest.get("type", "action"))

    glyph = _glyph(symbol, iconset)
    if glyph is not None:
        # Weicher Schatten, damit das Motiv auch auf hellem Akzent steht.
        shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow.paste(glyph, ((SIZE - glyph.width) // 2, (SIZE - glyph.height) // 2 + 4), glyph)
        image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
        image.alpha_composite(glyph, ((SIZE - glyph.width) // 2, (SIZE - glyph.height) // 2))

    target = directory / FILENAME
    image.save(target)

    if manifest.get("icon") != FILENAME:
        manifest["icon"] = FILENAME
        manifest_file.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"  ✔ {directory.name:18} accent {manifest.get('accent', '—'):8} symbol {symbol or '—'}")
    return True


def main(argv: list[str]) -> int:
    iconset = REPO / "backend" / "plugins" / "iconset-tabler" / "icons"
    if not iconset.is_dir():
        print(f"Icon set not found: {iconset}", file=sys.stderr)
        return 1

    wanted = set(argv[1:])
    built = 0
    for root in SEARCH:
        if not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            if wanted and directory.name not in wanted:
                continue
            if build(directory, iconset):
                built += 1

    print(f"\n{built} icon(s) written as {FILENAME}, manifests updated.")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
