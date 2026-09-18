#!/bin/sh
# Check that a freshly-installed Mnemify actually came up, kept its state
# where it was told to, and can be stopped again. Then stop it.
#
#   MNEMIFY_HOME=... MNEMIFY_LAUNCHER_DIR=... \
#   sh .github/scripts/smoke-assert.sh [--port 8789]
#
# Run by .github/workflows/install-smoke.yml after `setup.sh --no-launch` and
# `mnemify.sh --no-browser --port <port> &`. Also runnable by hand on a dev box
# against a scratch MNEMIFY_HOME - that is how it was written.
#
# The server is expected to be starting (or already up) when this runs.
#
# Needs: curl, jq. Both ship on every GitHub-hosted runner and on macOS 13+.
# POSIX sh - no bashisms.

set -eu

PORT=8789
# How long to wait for a freshly-installed server to answer. Generous on
# purpose: this is a cold first start, not a warm restart. Keep in step with
# the -WaitSeconds default in smoke-assert.ps1.
WAIT_SECONDS=180
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT=$2; shift 2 ;;
        --port=*) PORT=${1#--port=}; shift ;;
        --repo) REPO=$2; shift 2 ;;
        --wait) WAIT_SECONDS=$2; shift 2 ;;
        --wait=*) WAIT_SECONDS=${1#--wait=}; shift ;;
        *) printf 'smoke-assert: unknown option %s\n' "$1" >&2; exit 2 ;;
    esac
done

# An empty --port (an unset env var in the workflow) would otherwise swallow
# the next token and poll http://127.0.0.1:/api/health for a silent minute.
case "$PORT" in
    ''|*[!0-9]*)
        printf 'smoke-assert: --port needs a number, got "%s".\n' "$PORT" >&2
        exit 2
        ;;
esac

REPO=${REPO:-$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)}
REPO=$(CDPATH='' cd -- "$REPO" && pwd -P)
BASE="http://127.0.0.1:$PORT"

: "${MNEMIFY_HOME:?smoke-assert: MNEMIFY_HOME must be set}"
: "${MNEMIFY_LAUNCHER_DIR:?smoke-assert: MNEMIFY_LAUNCHER_DIR must be set}"

for tool in curl jq; do
    command -v "$tool" >/dev/null 2>&1 || {
        printf 'smoke-assert: %s is required.\n' "$tool" >&2
        exit 1
    }
done

FAILURES=0

ok() { printf '  PASS  %s\n' "$1"; }
bad() {
    printf '  FAIL  %s\n' "$1" >&2
    FAILURES=$((FAILURES + 1))
}
check() {
    # check <description> <actual> <expected>
    if [ "$2" = "$3" ]; then
        ok "$1 = $2"
    else
        bad "$1: expected '$3', got '$2'"
    fi
}

# `paths.home()` runs `.expanduser().resolve()`, so compare resolved against
# resolved - a symlinked temp root (/tmp -> /private/tmp on macOS) otherwise
# fails a prefix check that is actually fine.
real_path() {
    if [ -d "$1" ]; then
        (CDPATH='' cd -- "$1" && pwd -P)
    else
        printf '%s' "$1"
    fi
}

section() { printf '\n== %s\n' "$1"; }

# ---------------------------------------------------------------- 1. health
# Bound by the clock, not by a try count. `60 tries` was never 60 seconds: a
# refused connection costs real time before --max-time applies (~2s each on
# Windows, where the mirror of this loop advertised 60s and ran for three
# minutes). Report the elapsed time on success too - it is the only place the
# real cold start cost of a fresh install ever gets measured.
section "waiting for $BASE/api/health (up to ${WAIT_SECONDS}s)"
HEALTH=""
STARTED=$(date +%s)
DEADLINE=$((STARTED + WAIT_SECONDS))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if HEALTH=$(curl -fsS --max-time 5 "$BASE/api/health" 2>/dev/null) && [ -n "$HEALTH" ]; then
        break
    fi
    HEALTH=""
    sleep 1
done
WAITED=$(( $(date +%s) - STARTED ))
if [ -z "$HEALTH" ]; then
    printf 'smoke-assert: the server never answered on %s/api/health after %ss.\n' "$BASE" "$WAITED" >&2
    exit 1
fi
printf 'Answered after ~%ss.\n\n' "$WAITED"
printf '%s\n' "$HEALTH" | jq .

section "health assertions"
check "ok"           "$(printf '%s' "$HEALTH" | jq -r '.ok')"          "true"
check "paths.layout" "$(printf '%s' "$HEALTH" | jq -r '.paths.layout')" "env"

EXPECTED_VERSION=$(sed -n 's/^version = "\([^"]*\)".*$/\1/p' "$REPO/backend/pyproject.toml" | head -1)
check "version"      "$(printf '%s' "$HEALTH" | jq -r '.version')"     "$EXPECTED_VERSION"

HOME_REAL=$(real_path "$MNEMIFY_HOME")
DATA_DIR=$(printf '%s' "$HEALTH" | jq -r '.paths.data_dir')
case "$DATA_DIR" in
    "$HOME_REAL"/*) ok "paths.data_dir is under MNEMIFY_HOME ($DATA_DIR)" ;;
    *)              bad "paths.data_dir '$DATA_DIR' is not under MNEMIFY_HOME '$HOME_REAL'" ;;
esac

# ------------------------------------------------------------- 2. launcher
section "launcher"
case "$(uname -s)" in
    Darwin) LAUNCHER="$MNEMIFY_LAUNCHER_DIR/Mnemify.app/Contents/MacOS/Mnemify" ;;
    *)      LAUNCHER="$MNEMIFY_LAUNCHER_DIR/mnemify.desktop" ;;
esac
if [ -f "$LAUNCHER" ]; then
    ok "launcher exists: $LAUNCHER"
    if grep -qF "$REPO" "$LAUNCHER"; then
        ok "launcher points at this checkout"
    else
        bad "launcher does not mention $REPO"
    fi
else
    bad "launcher missing: $LAUNCHER"
fi

# --------------------------------------------------- 3. no writes into cwd
# The whole point of MNEMIFY_HOME. Any of these three under backend/ would
# also flip `paths.layout()` to "legacy" on the *next* run (see paths.py
# _LEGACY_MARKERS), so a stray file here poisons every later assertion.
section "nothing written into the checkout"
for stray in \
    "$REPO/.mnemify" \
    "$REPO/.env" \
    "$REPO/mnemify.yaml" \
    "$REPO/backend/.mnemify" \
    "$REPO/backend/.env" \
    "$REPO/backend/mnemify.yaml"
do
    if [ -e "$stray" ]; then
        bad "created in the checkout: $stray"
    else
        ok "absent: $stray"
    fi
done

# ------------------------------------------------- 4. runtime files in home
section "runtime files under MNEMIFY_HOME"
PID_FILE="$HOME_REAL/server.pid"
PORT_FILE="$HOME_REAL/server.port"
if [ -f "$PID_FILE" ]; then ok "server.pid exists"; else bad "server.pid missing at $PID_FILE"; fi
if [ -f "$PORT_FILE" ]; then
    ok "server.port exists"
    check "server.port contents" "$(tr -d ' \r\n' < "$PORT_FILE")" "$PORT"
else
    bad "server.port missing at $PORT_FILE"
fi

# ------------------------------------------------------------- 5. shutdown
section "POST /api/system/shutdown"
SHUTDOWN_BODY=$(mktemp)
CODE=$(curl -sS -o "$SHUTDOWN_BODY" -w '%{http_code}' -X POST \
    -H 'X-Mnemify-Client: ci' -H 'Content-Type: application/json' \
    --max-time 10 --data '{}' "$BASE/api/system/shutdown" || echo "000")
printf 'HTTP %s  %s\n' "$CODE" "$(cat "$SHUTDOWN_BODY")"
check "shutdown status" "$CODE" "200"
check "shutdown ok" "$(jq -r '.ok' < "$SHUTDOWN_BODY" 2>/dev/null || echo '<unparseable>')" "true"
rm -f "$SHUTDOWN_BODY"

section "server exit (up to 15s)"
gone=0
i=0
while [ "$i" -lt 15 ]; do
    if [ ! -f "$PID_FILE" ] && [ ! -f "$PORT_FILE" ] \
       && ! curl -fsS --max-time 2 "$BASE/api/health" >/dev/null 2>&1; then
        gone=1
        break
    fi
    i=$((i + 1))
    sleep 1
done
if [ "$gone" -eq 1 ]; then
    ok "server.pid + server.port removed and the port stopped answering after ~${i}s"
else
    bad "server did not shut down cleanly within 15s"
    if [ -f "$PID_FILE" ]; then  printf '        server.pid still present\n' >&2; fi
    if [ -f "$PORT_FILE" ]; then printf '        server.port still present\n' >&2; fi
    if curl -fsS --max-time 2 "$BASE/api/health" >/dev/null 2>&1; then
        printf '        still answering on %s/api/health\n' "$BASE" >&2
    fi
fi

printf '\n'
if [ "$FAILURES" -eq 0 ]; then
    printf 'smoke-assert: all checks passed.\n'
    exit 0
fi
printf 'smoke-assert: %s check(s) failed.\n' "$FAILURES" >&2
exit 1
