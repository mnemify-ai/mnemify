#!/bin/sh
# Mnemify — one-line installer for macOS / Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/mnemify-ai/mnemify/main/scripts/install.sh | sh
#
# It clones (or updates) the repo into $HOME/Mnemify and runs setup.sh there.
# Set MNEMIFY_INSTALL_DIR to put it somewhere else.
#
# Re-running this one-liner is the manual update path: if the folder already
# exists it does a fast-forward `git pull` and re-runs setup.sh, which rebuilds
# the backend and the web app. Your harvested and compiled data lives outside
# the folder, so nothing here can touch it.
#
# POSIX sh — must work when piped to `sh`, so it never looks at its own path.

set -eu

REPO_URL=${MNEMIFY_REPO_URL:-https://github.com/mnemify-ai/mnemify}
DEST=${MNEMIFY_INSTALL_DIR:-$HOME/Mnemify}

printf 'Mnemify installer\n'
printf 'Source: %s\n' "$REPO_URL"
printf 'Folder: %s\n\n' "$DEST"

if ! command -v git >/dev/null 2>&1; then
    printf 'git is required and was not found.\n' >&2
    case "$(uname -s)" in
        Darwin)
            printf 'Install it with:  xcode-select --install     (or: brew install git)\n' >&2
            ;;
        *)
            printf 'Install it with:  sudo apt install git   (Debian/Ubuntu)\n' >&2
            printf '                  sudo dnf install git   (Fedora)\n' >&2
            ;;
    esac
    printf '\nNo git? Download the ZIP instead:\n' >&2
    printf '  %s/archive/refs/heads/main.zip\n' "$REPO_URL" >&2
    printf '  unzip it, then run:  sh setup.sh\n' >&2
    exit 1
fi

if [ -d "$DEST/.git" ]; then
    printf 'Already installed — updating to the latest code.\n'
    git -C "$DEST" pull --ff-only
elif [ -e "$DEST" ]; then
    printf '%s already exists and is not a git checkout.\n' "$DEST" >&2
    printf 'Move it aside, or set MNEMIFY_INSTALL_DIR to another folder, then try again.\n' >&2
    exit 1
else
    git clone "$REPO_URL" "$DEST"
fi

cd "$DEST"
printf '\nRunning setup.\n\n'

# When this file arrives through `curl | sh`, stdin is the pipe, not the user.
# Hand setup.sh the terminal back so its one prompt (install uv?) still works.
# `[ -r /dev/tty ]` is true even where there is no controlling terminal (CI,
# a daemon), and the redirect then fails and takes setup.sh down with it.
# Actually opening it is the only honest test.
if [ ! -t 0 ] && (: </dev/tty) 2>/dev/null; then
    exec sh ./setup.sh "$@" </dev/tty
fi
exec sh ./setup.sh "$@"
