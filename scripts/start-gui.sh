#!/usr/bin/env sh
#
# Opens the configuration interface as a Tauri window.
# The backend has to be running (start-backend.sh or the systemd service).

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
BINARY="$REPO/gui/src-tauri/target/release/deckswitch"

if [ ! -x "$BINARY" ]; then
    printf '\033[33mTauri binary not built yet — building now (the first build takes a few minutes) …\033[0m\n'
    (cd "$REPO/gui" && npx tauri build --no-bundle)
fi

if ! curl -sf -o /dev/null http://127.0.0.1:8770/api/device 2>/dev/null; then
    printf '\033[33mNote: the backend does not appear to be running. Start it with:\n  ./scripts/start-backend.sh\033[0m\n'
fi

# Gestartet wird über dasselbe Skript, das im Paket als `deckswitch-gui`
# landet — nur mit der selbst gebauten Datei statt der installierten. So
# gibt es die Behandlung des Wayland-Fehlstarts genau einmal, und was hier
# im Checkout läuft, ist dasselbe, was Nutzer des Pakets bekommen.
DECKSWITCH_GUI_BINARY="$BINARY"
export DECKSWITCH_GUI_BINARY
exec "$REPO/packaging/deckswitch-gui.sh" "$@"
