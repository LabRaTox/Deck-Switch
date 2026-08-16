#!/usr/bin/env python
"""Generates the app icon in every format the project needs.

The geometry lives in ``deckswitch.services.brand``; this script turns
it into files. The tray icon is deliberately absent — it draws itself at
runtime, in exactly the size the panel asks for.

    ./scripts/make-icon.py

Rebuild the GUI afterwards so the favicon ends up in the build.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from deckswitch.services import brand  # noqa: E402

SVG = REPO / "gui" / "public" / "icon.svg"
TAURI = REPO / "gui" / "src-tauri" / "icons"

#: What tauri.conf.json references, plus icon.png as the window image.
PNGS = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
}
#: Sizes packed into the .ico file.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> int:
    SVG.parent.mkdir(parents=True, exist_ok=True)
    SVG.write_text(brand.icon_svg(), encoding="utf-8")
    print(f"✔ {SVG.relative_to(REPO)}  ({SVG.stat().st_size} bytes)")

    if not TAURI.is_dir():
        print("… no Tauri folder, skipping the window icons")
        return 0

    for name, size in PNGS.items():
        path = TAURI / name
        brand.icon_image(size).save(path)
        print(f"✔ {path.relative_to(REPO)}  ({size}×{size})")

    ico = TAURI / "icon.ico"
    largest = brand.icon_image(max(ICO_SIZES))
    largest.save(ico, sizes=[(s, s) for s in ICO_SIZES])
    print(f"✔ {ico.relative_to(REPO)}  ({', '.join(str(s) for s in ICO_SIZES)})")

    print("\nNext: cd gui && npm run build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
