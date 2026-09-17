#!/bin/sh
# Mnemify — start the app (macOS / Linux). This is what the desktop icon runs.
#
#   sh mnemify.sh                 start, open a browser tab
#   sh mnemify.sh --gui           same, but log to a file and report errors in a dialog
#   sh mnemify.sh --no-browser --port 8793     anything else is passed to `mnemify up`
#
# Deliberately dumb: no git, no network, no updates. It resolves a usable PATH,
# checks that setup has been run, and hands over to the server. The server owns
# everything else — picking a port, noticing it is already running, opening the
# browser, and shutting itself down when idle.
#
# POSIX sh — tested with dash and bash. No bashisms.

set -eu

# --------------------------------------------------------------- repo root
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
cd "$SCRIPT_DIR"
REPO="$SCRIPT_DIR"

# ------------------------------------------------------------------- args
# Pull --gui out; everything else goes through to `mnemify up`.
GUI=0
argc=$#
i=0
while [ "$i" -lt "$argc" ]; do
    a="$1"
    shift
    if [ "$a" = "--gui" ]; then
        GUI=1
    else
        set -- "$@" "$a"
    fi
    i=$((i + 1))
done

# ------------------------------------------------------------------- PATH
# A process started from Finder or a .desktop file inherits a minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin) — none of the places uv, node or the `claude`
# CLI actually live. Put the usual ones back.
prepend_path() {
    _d=$1
    [ -d "$_d" ] || return 0
    case ":$PATH:" in
        *":$_d:"*) return 0 ;;
    esac
    PATH="$_d:$PATH"
}

for _d in \
    "$HOME/bin" \
    "$HOME/.npm-global/bin" \
    "$HOME/.volta/bin" \
    "$HOME/.local/state/fnm_multishells" \
    /usr/local/bin \
    /opt/homebrew/bin \
    "$HOME/.cargo/bin" \
    "$HOME/.local/bin"
do
    prepend_path "$_d"
done
# Version managers keep node under a per-version directory; no fixed bin dir.
for _d in "$HOME"/.nvm/versions/node/*/bin \
          "$HOME"/.local/share/fnm/node-versions/*/installation/bin \
          "$HOME"/Library/Application\ Support/fnm/node-versions/*/installation/bin
do
    prepend_path "$_d"
done
export PATH

# ------------------------------------------------------------------ logging
default_log_dir() {
    if [ "$(uname -s)" = "Darwin" ]; then
        printf '%s\n' "$HOME/Library/Logs/Mnemify"
    else
        printf '%s\n' "${XDG_STATE_HOME:-$HOME/.local/state}/mnemify"
    fi
}

LOG_FILE=""
if [ "$GUI" -eq 1 ]; then
    LOG_DIR=${MNEMIFY_LOG_DIR:-$(default_log_dir)}
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    if [ -d "$LOG_DIR" ]; then
        LOG_FILE="$LOG_DIR/launcher.log"
        # Keep one generation, so the log cannot grow without bound.
        if [ -f "$LOG_FILE" ] && [ "$(wc -c <"$LOG_FILE" 2>/dev/null || echo 0)" -gt 1048576 ]; then
            mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || true
        fi
        exec >>"$LOG_FILE" 2>&1
        printf '\n===== %s : starting Mnemify from %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$REPO"
    fi
fi

# ------------------------------------------------------------------ errors
# Set MNEMIFY_DIALOG_DRYRUN=1 to log the dialog command instead of showing it
# (used by the test suite, which has nobody around to click OK).
show_error() {
    _msg=$1
    printf '%s\n' "$_msg" >&2
    [ "$GUI" -eq 1 ] || return 0
    case "$(uname -s)" in
        Darwin)
            _script="display dialog \"$_msg\" buttons {\"OK\"} default button \"OK\" with icon stop with title \"Mnemify\""
            if [ -n "${MNEMIFY_DIALOG_DRYRUN:-}" ]; then
                printf '[dialog dry-run] osascript -e %s\n' "$_script"
            else
                osascript -e "$_script" >/dev/null 2>&1 || true
            fi
            ;;
        *)
            if [ -n "${MNEMIFY_DIALOG_DRYRUN:-}" ]; then
                printf '[dialog dry-run] zenity --error --title=Mnemify --text=%s\n' "$_msg"
            elif command -v zenity >/dev/null 2>&1; then
                zenity --error --title="Mnemify" --text="$_msg" >/dev/null 2>&1 || true
            elif command -v kdialog >/dev/null 2>&1; then
                kdialog --error "$_msg" >/dev/null 2>&1 || true
            elif command -v notify-send >/dev/null 2>&1; then
                notify-send -u critical "Mnemify" "$_msg" >/dev/null 2>&1 || true
            fi
            ;;
    esac
}

where_to_look() {
    if [ -n "$LOG_FILE" ]; then
        printf 'See %s' "$LOG_FILE"
    else
        printf 'Run it from a terminal to see why: sh %s/mnemify.sh' "$REPO"
    fi
}

# ------------------------------------------------------------ sanity checks
if [ ! -d "$REPO/backend/.venv" ]; then
    show_error "Mnemify is not installed yet. Run \`sh setup.sh\` in $REPO first."
    exit 1
fi
if [ -z "${MNEMIFY_WEB_DIST:-}" ] && [ ! -d "$REPO/frontend/web/dist" ]; then
    show_error "The Mnemify web app has not been built. Run \`sh setup.sh\` in $REPO first."
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    show_error "Could not find \`uv\`. Run \`sh setup.sh\` in $REPO first. $(where_to_look)"
    exit 1
fi

# ------------------------------------------------------------------- start
cd "$REPO/backend"

if [ "$GUI" -eq 1 ]; then
    # Not exec: we want to survive the server and report a failure in a dialog.
    set +e
    uv run --no-sync mnemify up "$@"
    status=$?
    set -e
    # 130 = SIGINT, 143 = SIGTERM: somebody (or the OS at logout) stopped the
    # server on purpose. That is not a failure worth a dialog.
    case "$status" in
        0 | 130 | 143) ;;
        *) show_error "Mnemify failed to start. $(where_to_look)" ;;
    esac
    exit "$status"
fi

exec uv run --no-sync mnemify up "$@"
