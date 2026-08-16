#!/usr/bin/env sh
#
# Registers the streamdeck:// scheme with the desktop so that links like
#
#   streamdeck://install?url=https://example.com/plugin.zip
#
# work from a browser. The handler installs nothing by itself — it hands the
# request to the backend, which shows it in the GUI for confirmation.
#
#   ./scripts/install-url-handler.sh            register
#   ./scripts/install-url-handler.sh --remove   unregister

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
APPS="$HOME/.local/share/applications"
ENTRY="$APPS/streamdeck-url-handler.desktop"

if [ "${1:-}" = "--remove" ]; then
    rm -f "$ENTRY"
    update-desktop-database "$APPS" 2>/dev/null || true
    printf '\033[32m✔ streamdeck:// unregistered\033[0m\n'
    exit 0
fi

HANDLER="$REPO/packaging/streamdeck-url-handler.py"
chmod +x "$HANDLER"

mkdir -p "$APPS"
sed "s|__HANDLER__|$HANDLER|" "$REPO/packaging/streamdeck-url-handler.desktop" > "$ENTRY"
update-desktop-database "$APPS" 2>/dev/null || true

if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default streamdeck-url-handler.desktop x-scheme-handler/streamdeck
else
    printf '\033[33m! xdg-mime missing (package xdg-utils) — entry created, but not set as the default\033[0m\n'
fi

printf '\033[32m✔ streamdeck:// registered\033[0m\n'
echo "  Handler: $HANDLER"
echo
echo "  Try it out:"
echo "    xdg-open 'streamdeck://install?url=https://example.com/plugin.zip'"
echo
printf '\033[33m  Note: clicking such a link installs nothing on its own —\n  the request has to be confirmed in the Stream Deck interface.\033[0m\n'
