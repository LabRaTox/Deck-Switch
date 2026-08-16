#!/usr/bin/env sh
#
# Installs the backend as a systemd user service so it starts at login.
#
#   ./scripts/install-service.sh            install and start
#   ./scripts/install-service.sh --remove   remove again
#
# The same thing is available as a switch in the app's settings; both write
# the same unit.

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/deckswitch.service"

if [ "${1:-}" = "--remove" ]; then
    systemctl --user disable --now deckswitch.service 2>/dev/null || true
    rm -f "$UNIT"
    systemctl --user daemon-reload
    printf '\033[32m✔ Service removed\033[0m\n'
    exit 0
fi

if [ ! -x "$REPO/.venv/bin/python" ]; then
    printf '\033[31mNo .venv found — run ./scripts/setup.sh first.\033[0m\n' >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    printf '\033[31msystemd not found. This project targets CachyOS and Arch Linux, where it is standard.\033[0m\n' >&2
    exit 1
fi

mkdir -p "$UNIT_DIR"
sed "s|__REPO__|$REPO|g" "$REPO/packaging/deckswitch.service" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now deckswitch.service

printf '\033[32m✔ Service installed and started\033[0m\n'
echo "  Status:  systemctl --user status deckswitch"
echo "  Log:     journalctl --user -u deckswitch -f"
echo "  Stop:    systemctl --user stop deckswitch"
