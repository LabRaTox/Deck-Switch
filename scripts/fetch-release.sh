#!/usr/bin/env bash
#
# Downloads the finished files of a release, for machines without Node, Rust
# or a compiler. The release builds them on an old Ubuntu, see
# scripts/build-release-files.sh.
#
#   scripts/fetch-release.sh <version> <target folder>
#
# Exits non-zero, with the target left alone, when there is nothing to fetch.
# The checksum comes from the same release, so it catches a broken download
# and not a compromised release.

set -euo pipefail

VERSION="$1"
TARGET="$2"
BASE="${DECKSWITCH_REPOSITORY:-https://github.com/LabRaTox/Deck-Switch}/releases/download"
ASSET="deckswitch-${VERSION}-x86_64-linux.tar.gz"

[ "$(uname -m)" = "x86_64" ] || { echo "no build for $(uname -m)" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

curl -fsSL -o "${WORK}/${ASSET}" "${BASE}/v${VERSION}/${ASSET}"
curl -fsSL -o "${WORK}/${ASSET}.sha256" "${BASE}/v${VERSION}/${ASSET}.sha256"
(cd "$WORK" && sha256sum --quiet -c "${ASSET}.sha256")

mkdir -p "$TARGET"
tar -C "$TARGET" -xzf "${WORK}/${ASSET}"
