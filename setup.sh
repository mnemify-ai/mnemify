#!/bin/sh
# Mnemify — one-time setup (macOS / Linux).
#
#   sh setup.sh              install everything, create the desktop icon, start the app
#   sh setup.sh --no-launch  install only
#   sh setup.sh --skip-frontend   skip the web build (developers; needs a dist/ already)
#
# Re-running this script is also how you update: get the new code
# (git pull, or unzip a fresh download over the folder) and run it again.
# Every step below is safe to repeat. Your data lives outside this folder.
#
# POSIX sh — tested with dash and bash. No bashisms.

set -eu

STEP="startup"
HINT=""

on_exit() {
    st=$?
    if [ "$st" -ne 0 ]; then
        printf '\n%s\n' '---------------------------------------------------------------' >&2
        printf 'Setup failed during: %s\n' "$STEP" >&2
        if [ -n "$HINT" ]; then
            printf 'What to do: %s\n' "$HINT" >&2
        fi
        printf '%s\n' '---------------------------------------------------------------' >&2
    fi
    exit "$st"
}
trap on_exit EXIT

step() {
    STEP="$1"
    HINT="$2"
    printf '\n==> %s\n' "$1"
}

# ---------------------------------------------------------------- 0. arguments
NO_LAUNCH=0
SKIP_FRONTEND=0
for arg in "$@"; do
    case "$arg" in
        --no-launch) NO_LAUNCH=1 ;;
        --skip-frontend) SKIP_FRONTEND=1 ;;
        -h|--help)
            cat <<'HELP'
Mnemify - one-time setup (macOS / Linux).

  sh setup.sh                  install everything, create the desktop icon, start the app
  sh setup.sh --no-launch      install only
  sh setup.sh --skip-frontend  skip the web build (developers; needs a dist/ already)

Re-running this script is also how you update: get the new code
(git pull, or unzip a fresh download over the folder) and run it again.
Every step is safe to repeat, and your data lives outside this folder.
HELP
            trap - EXIT
            exit 0
            ;;
        *)
            printf 'Unknown option: %s (try: sh setup.sh --help)\n' "$arg" >&2
            trap - EXIT
            exit 2
            ;;
    esac
done
if [ -n "${MNEMIFY_NONINTERACTIVE:-}" ]; then
    NO_LAUNCH=1
fi

# --------------------------------------------- 1. work from the repo root always
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
cd "$SCRIPT_DIR"
REPO="$SCRIPT_DIR"

printf 'Mnemify setup\n'
printf '%s\n' "-------------"
printf 'Folder: %s\n' "$REPO"

if [ ! -f backend/pyproject.toml ] || [ ! -f frontend/web/package.json ]; then
    step "locating the repo" "Run this script from inside the mnemify folder (sh setup.sh)."
    printf 'This does not look like a Mnemify checkout.\n' >&2
    exit 1
fi

# ------------------------------------------------ 2. macOS: the download flag
# Files that arrive in a downloaded ZIP are tagged com.apple.quarantine. It makes
# macOS second-guess every script in the folder. Clearing it on files you chose to
# download is a per-file change; it is NOT a system or security setting.
step "clearing the macOS download flag" "Nothing to do — this step is macOS-only and never fatal."
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
    found=""
    for probe in . setup.sh mnemify.sh README.md backend frontend; do
        if [ -e "$probe" ] && xattr -p com.apple.quarantine "$probe" >/dev/null 2>&1; then
            found=1
            break
        fi
    done
    if [ -n "$found" ]; then
        printf 'Removing the download flag (com.apple.quarantine) from these files — not a system setting.\n'
        xattr -dr com.apple.quarantine . 2>/dev/null || true
    else
        printf 'No download flag set — nothing to clear.\n'
    fi
else
    printf 'Not macOS — skipped.\n'
fi

# --------------------------------------------------------------------- 3. uv
step "installing uv" "Install uv yourself (https://docs.astral.sh/uv/getting-started/installation/) and re-run this script."
if command -v uv >/dev/null 2>&1; then
    printf 'uv already installed: %s\n' "$(uv --version)"
else
    if ! command -v curl >/dev/null 2>&1; then
        HINT="Install curl (macOS: it ships with the system; Linux: sudo apt install curl), then re-run."
        printf 'curl is required to install uv.\n' >&2
        exit 1
    fi
    printf 'uv is not installed. Mnemify uses it to manage Python.\n'
    printf 'Installer: https://astral.sh/uv/install.sh\n'
    printf 'It installs into %s/.local/bin — user-only, no sudo, nothing system-wide.\n' "$HOME"
    if [ -z "${MNEMIFY_NONINTERACTIVE:-}" ]; then
        printf 'Press Enter to continue, or Ctrl-C to stop and install uv yourself: '
        read -r _answer || true
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
    if ! command -v uv >/dev/null 2>&1; then
        HINT="uv installed but is not on PATH. Open a new terminal and re-run, or add \$HOME/.local/bin to your PATH."
        printf 'uv is still not on PATH.\n' >&2
        exit 1
    fi
    printf 'Installed: %s\n' "$(uv --version)"
fi

# ------------------------------------------------------------------- 4. Node
step "checking Node.js" "Install Node.js 18 or newer, then re-run this script."
NODE_MAJOR=0
NODE_RAW=""
if command -v node >/dev/null 2>&1; then
    NODE_RAW=$(node --version 2>/dev/null || echo "")
    NODE_MAJOR=$(printf '%s' "$NODE_RAW" | sed 's/^v//' | cut -d. -f1)
    case "$NODE_MAJOR" in
        ''|*[!0-9]*) NODE_MAJOR=0 ;;
    esac
fi
if [ "$NODE_MAJOR" -lt 18 ]; then
    if [ "$NODE_MAJOR" -eq 0 ]; then
        printf 'Node.js was not found.\n' >&2
    else
        printf 'Node.js %s is too old — Mnemify needs 18 or newer.\n' "$NODE_RAW" >&2
    fi
    printf '\nInstall it, then run this script again:\n' >&2
    if [ "$(uname -s)" = "Darwin" ]; then
        printf '  brew install node        (or download from https://nodejs.org)\n' >&2
    else
        printf '  sudo apt install nodejs npm    (Debian/Ubuntu)\n' >&2
        printf '  sudo dnf install nodejs        (Fedora)\n' >&2
        printf '  or download from https://nodejs.org\n' >&2
    fi
    printf '\nWe do not install it for you on purpose — system packages are your call.\n' >&2
    exit 1
fi
printf 'Node.js %s — ok.\n' "$NODE_RAW"
if ! command -v npm >/dev/null 2>&1; then
    HINT="npm is missing. On Debian/Ubuntu: sudo apt install npm. Otherwise reinstall Node.js from https://nodejs.org."
    printf 'npm was not found.\n' >&2
    exit 1
fi

# --------------------------------------------------------------- 5. backend
step "installing the backend (uv sync)" "Check the uv output above. A failed download is usually a network or proxy problem — re-run the script."
printf 'Creating backend/.venv and installing dependencies. First run takes a minute or two.\n'
( cd backend && uv sync )
printf 'Backend ready: %s/backend/.venv\n' "$REPO"

# -------------------------------------------------------------- 6. frontend
step "building the web app (npm ci && npm run build)" "Check the npm output above. If it complains about node_modules, delete frontend/web/node_modules and re-run."
if [ "$SKIP_FRONTEND" -eq 1 ]; then
    printf 'Skipped (--skip-frontend).\n'
    if [ ! -d frontend/web/dist ]; then
        printf 'Note: frontend/web/dist does not exist, so the app will have no UI to serve.\n'
    fi
else
    printf 'Installing web dependencies and building the app.\n'
    printf 'This is the slow step: roughly 1-3 minutes the first time, and it runs again on every update.\n'
    ( cd frontend/web && npm ci --no-audit --no-fund && npm run build )
    printf 'Web app built: %s/frontend/web/dist\n' "$REPO"
fi

# --------------------------------------------------------------- 7. launcher
step "creating the desktop launcher" "Not fatal — you can always start Mnemify with: sh mnemify.sh"
if ! sh "$REPO/scripts/make-launcher.sh" "$REPO"; then
    printf 'Could not create the launcher. Start Mnemify with: sh mnemify.sh\n' >&2
fi

# ------------------------------------------------------------ 8. done summary
STEP="printing the summary"
HINT=""
MNEMIFY_DATA_HOME=$( (cd backend && uv run --no-sync python -c "from src import paths; print(paths.describe()['home'])" 2>/dev/null) || echo "" )
if [ -z "$MNEMIFY_DATA_HOME" ]; then
    MNEMIFY_DATA_HOME="(run 'cd backend && uv run mnemify up' once to create it)"
fi

printf '\n%s\n' '---------------------------------------------------------------'
printf 'Done. Mnemify is installed.\n\n'
printf '  Start    the Mnemify icon (Launchpad / your app menu), or: sh mnemify.sh\n'
printf '  Fallback cd backend && uv run mnemify up\n'
printf '  Data     %s\n' "$MNEMIFY_DATA_HOME"
printf '  Update   get the new code (git pull, or unzip a fresh download), then: sh setup.sh\n'
printf '  Stop     Settings -> General -> Quit Mnemify, or: cd backend && uv run mnemify stop\n'
printf '  Keys     enter them in the app: Settings -> AI & Models, Build -> Sources\n'
printf '%s\n' '---------------------------------------------------------------'

# ---------------------------------------------------------------- 9. launch
if [ "$NO_LAUNCH" -eq 1 ]; then
    printf '\nNot launching (--no-launch). Start it whenever you like.\n'
    trap - EXIT
    exit 0
fi
printf '\nStarting Mnemify...\n'
trap - EXIT
exec sh "$REPO/mnemify.sh"
