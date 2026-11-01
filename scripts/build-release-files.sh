#!/usr/bin/env bash
#
# Builds what a release carries for machines without Node, Rust or a compiler:
# the window, the built interface and the two Python packages that have no
# finished wheels on PyPI.
#
#   scripts/build-release-files.sh <output folder>
#
# Runs on the oldest Ubuntu that has webkit2gtk-4.1 on purpose, see
# .github/workflows/release-files.yml: a binary runs on the glibc it was built
# against and anything newer.

set -euo pipefail

OUT=$(mkdir -p "$1" && cd "$1" && pwd)
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${REPO}/backend/deckswitch/__init__.py")
#: Must match PYTHON_VERSION in install.sh: wheels fit one Python only.
PYTHON_VERSION="3.13"
ASSET="deckswitch-${VERSION}-x86_64-linux.tar.gz"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

(cd "${REPO}/gui" && npm ci && npx tauri build --no-bundle)
install -m755 "${REPO}/gui/src-tauri/target/release/deckswitch" "${WORK}/deckswitch"
cp -a "${REPO}/gui/dist" "${WORK}/dist"

uv venv --quiet --python "$PYTHON_VERSION" "${WORK}/build"
uv pip install --quiet --python "${WORK}/build/bin/python" pip
# xkbcommon folgt der Fassung der Bibliothek und ruft ab 1.5 Funktionen auf, die
# Ubuntu 22.04 nicht hat. Die ältere Fassung läuft auch gegen jede neuere.
"${WORK}/build/bin/python" -m pip wheel --quiet --no-deps --wheel-dir "${WORK}/wheels" \
    evdev "xkbcommon<1.5"
rm -rf "${WORK}/build"

tar -C "$WORK" -czf "${OUT}/${ASSET}" deckswitch dist wheels
(cd "$OUT" && sha256sum "$ASSET" > "${ASSET}.sha256")
echo "${OUT}/${ASSET}"
