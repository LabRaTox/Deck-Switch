#!/usr/bin/env sh
#
# Opens the configuration interface as a Tauri window. The backend comes
# along automatically — deckswitch-gui.sh starts it if it isn't running.

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
BINARY="$REPO/gui/src-tauri/target/release/deckswitch"

if [ ! -x "$BINARY" ]; then
    printf '\033[33mTauri binary not built yet — building now (the first build takes a few minutes) …\033[0m\n'
    (cd "$REPO/gui" && npx tauri build --no-bundle)
fi

# Gestartet wird über dasselbe Skript, das im Paket als `deckswitch-gui`
# landet — nur mit der selbst gebauten Datei statt der installierten. So
# gibt es die Behandlung des Wayland-Fehlstarts und das Mitbringen des
# Backends genau einmal, und was hier im Checkout läuft, ist dasselbe,
# was Nutzer des Pakets bekommen.
DECKSWITCH_GUI_BINARY="$BINARY"
export DECKSWITCH_GUI_BINARY
exec "$REPO/packaging/deckswitch-gui.sh" "$@"
