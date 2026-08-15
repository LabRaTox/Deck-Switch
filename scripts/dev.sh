#!/usr/bin/env sh
#
# Development mode: backend in the background plus the Vite dev server with
# hot reload. The GUI then lives on http://localhost:5173 and talks to the
# backend on 127.0.0.1:8770.
#
# Stop with Ctrl-C — the backend is stopped along with it.

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)

"$REPO/.venv/bin/python" -m deckswitch --verbose &
BACKEND_PID=$!

# Do not leave the backend orphaned, however we leave this script.
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

sleep 2
cd "$REPO/gui" && npm run dev
