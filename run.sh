#!/usr/bin/env bash
#
# Mnemify — one-command launcher (run from the project root).
#
#   ./run.sh             Build the web UI and serve EVERYTHING from the
#                        backend on http://127.0.0.1:8783 — one process,
#                        no HMR, no npm needed at run time. Use this to hand
#                        alpha testers a "run and fire" app.
#
#   ./run.sh --dev       Run the FastAPI backend (auto-reload) and the Vite
#                        dev server (HMR) side by side. Open http://localhost:5173.
#                        Ctrl-C stops both.
#
#   ./run.sh --no-browser    Don't auto-open a browser tab.
#
# Env overrides:  PYTHON=path/to/python   PORT=8800   ./run.sh
# First run installs deps automatically (pip install -e backend; npm install).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/web"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8783}"

MODE="serve"
NO_BROWSER=""
for arg in "$@"; do
  case "$arg" in
    --dev) MODE="dev" ;;
    --no-browser) NO_BROWSER="--no-browser" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "run.sh: unknown option '$arg' (try --dev, --no-browser, --help)" >&2; exit 2 ;;
  esac
done

command -v "$PYTHON" >/dev/null 2>&1 || { echo "run.sh: '$PYTHON' not found — set PYTHON=... to your interpreter." >&2; exit 1; }
command -v npm      >/dev/null 2>&1 || { echo "run.sh: 'npm' not found — install Node.js (>= 18)." >&2; exit 1; }

# --- dependencies (first run) --------------------------------------------
if ! ( cd "$BACKEND" && "$PYTHON" -c "import src.api" ) >/dev/null 2>&1; then
  echo "==> Installing backend dependencies ($PYTHON -m pip install -e .) …"
  ( cd "$BACKEND" && "$PYTHON" -m pip install -e . )
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "==> Installing frontend dependencies (npm install) …"
  ( cd "$FRONTEND" && npm install )
fi

# --- serve: build once, backend serves the bundle ------------------------
if [ "$MODE" = "serve" ]; then
  echo "==> Building the web UI (npm run build) …"
  ( cd "$FRONTEND" && npm run build )
  echo "==> Mnemify is up on http://127.0.0.1:$PORT  (Ctrl-C to stop)"
  cd "$BACKEND"
  exec "$PYTHON" -m src up --port "$PORT" $NO_BROWSER
fi

# --- dev: FastAPI (--reload) + Vite dev server, side by side -------------
echo "==> Dev mode: FastAPI (:$PORT, --reload) + Vite (:5173). Open http://localhost:5173  (Ctrl-C to stop both)"
pids=()
cleanup() {
  trap - INT TERM EXIT
  for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

( cd "$BACKEND"  && exec "$PYTHON" -m src up --port "$PORT" --reload --no-browser ) & pids+=("$!")
( cd "$FRONTEND" && exec npm run dev ) & pids+=("$!")

# Exit (and clean up) as soon as either side dies.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
