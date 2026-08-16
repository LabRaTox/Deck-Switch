#!/usr/bin/env sh
#
# Starts the backend. Arguments are passed straight through, e.g.:
#   ./scripts/start-backend.sh --port 8888 --verbose

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -x "$REPO/.venv/bin/python" ]; then
    printf '\033[31mNo .venv found — run ./scripts/setup.sh first.\033[0m\n' >&2
    exit 1
fi

# No activation needed: the direct path works in any shell.
exec "$REPO/.venv/bin/python" -m deckswitch "$@"
