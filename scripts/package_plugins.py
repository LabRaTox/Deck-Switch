#!/usr/bin/env python3
"""Packs plugin sources into distributable ZIP archives.

The archives can be installed from a file, from a URL, or through a
``streamdeck://`` link.

    ./scripts/package_plugins.py            pack everything
    ./scripts/package_plugins.py weather    pack just one

Written in Python rather than shell on purpose: ``zip`` is not installed
everywhere, and the version should be parsed out of the manifest instead of
guessed with grep.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "plugin-sources"
TARGET = REPO / "dist" / "plugins"

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# Build-time helpers that live in the repo, not on the user's machine.
# ``screenshots.py`` draws a plugin's own store images and is run by
# ``make-plugin-screenshots.py``; shipping it would put a script into every
# installation that never runs there.
SKIP_NAMES = {"screenshots.py"}


def package(directory: Path) -> Path | None:
    manifest_file = directory / "manifest.json"
    if not manifest_file.is_file():
        print(f"  ! {directory.name}: no manifest.json, skipped")
        return None

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ✘ {directory.name}: manifest.json unreadable ({exc})")
        return None

    plugin_id = manifest.get("id") or directory.name
    version = manifest.get("version", "0.0.0")

    TARGET.mkdir(parents=True, exist_ok=True)
    archive_path = TARGET / f"{plugin_id}-{version}.zip"

    files = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not SKIP_DIRS.intersection(path.parts)
        and path.suffix not in SKIP_SUFFIXES
        and path.name not in SKIP_NAMES
    ]

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            # Plugin folder as the top level — that way the installer can
            # tell the ID without relying on the archive's file name.
            archive.write(path, f"{plugin_id}/{path.relative_to(directory)}")

    size = archive_path.stat().st_size / 1024
    print(
        f"  ✔ {plugin_id} v{version} → dist/plugins/{archive_path.name} "
        f"({size:.0f} KB, {len(files)} files)"
    )
    return archive_path


def main(argv: list[str]) -> int:
    if not SOURCE.is_dir():
        print(f"plugin-sources/ not found ({SOURCE})", file=sys.stderr)
        return 1

    wanted = set(argv[1:])
    built = 0
    for directory in sorted(p for p in SOURCE.iterdir() if p.is_dir()):
        if wanted and directory.name not in wanted:
            continue
        if package(directory) is not None:
            built += 1

    if built == 0:
        print("Nothing packed.")
        return 1

    print(f"\n{built} archive(s) in dist/plugins/. Install them via:")
    print("  • Plugins → Install → drop the file here")
    print("  • a URL you host them under")
    print("  • streamdeck://install?url=https://…/<file>.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
