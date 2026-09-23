#!/bin/sh
# Build the release ZIP: the git-tracked tree with the prebuilt web app,
# minus what a fresh machine never needs.
#
#   sh .github/scripts/make-release-zip.sh <version> <out-dir>
#
# Only files git tracks go in (working-tree contents, so an uncommitted edit
# to setup.sh is what gets tested locally), plus frontend/web/dist, which is
# ignored by git on purpose and is the whole point of the ZIP. Building the
# list from git rather than an exclude list means a stray local .venv, data
# folder or backup directory can never leak into a release.
#
# Expects frontend/web/dist to contain .mnemify-prebuilt (the release
# workflow writes it right after `npm run build`). Produces
# <out-dir>/mnemify-v<version>.zip whose single top-level folder is
# mnemify-v<version>/ so unzipping never spills files into Downloads.
#
# POSIX sh - no bashisms. Needs git, rsync and zip; all three are on every
# GitHub runner and on macOS / most Linux.

set -eu

if [ $# -ne 2 ]; then
    printf 'usage: %s <version> <out-dir>\n' "$0" >&2
    exit 2
fi
VERSION="$1"
OUT="$2"
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
NAME="mnemify-v$VERSION"
DIST="$ROOT/frontend/web/dist"

if [ ! -f "$DIST/index.html" ]; then
    printf 'frontend/web/dist/index.html is missing - build the web app first.\n' >&2
    exit 1
fi
if [ ! -f "$DIST/.mnemify-prebuilt" ]; then
    printf 'frontend/web/dist/.mnemify-prebuilt is missing - setup.sh would rebuild instead of skipping Node.\n' >&2
    exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$OUT"
case "$OUT" in /*) ;; *) OUT="$(pwd -P)/$OUT" ;; esac

# Tracked files, minus the contributor-only parts. Paths are repo-relative.
( cd "$ROOT" && git ls-files ) \
    | grep -v -E '^(\.github/|backend/tests/|mockdata/|\.gitignore$|UPDATES\.md$)' \
    > "$STAGE/files.txt"
if ! grep -q '^setup\.sh$' "$STAGE/files.txt"; then
    printf 'git ls-files did not list setup.sh - is this a git checkout?\n' >&2
    exit 1
fi
rsync -a --files-from="$STAGE/files.txt" "$ROOT/" "$STAGE/$NAME/"

mkdir -p "$STAGE/$NAME/frontend/web"
rsync -a "$DIST/" "$STAGE/$NAME/frontend/web/dist/"

rm -f "$OUT/$NAME.zip"
( cd "$STAGE" && zip -q -r -X "$OUT/$NAME.zip" "$NAME" )

count=$(wc -l < "$STAGE/files.txt" | tr -d ' ')
size=$(du -h "$OUT/$NAME.zip" | cut -f1)
printf 'Wrote %s/%s.zip (%s, %s tracked files + web app)\n' "$OUT" "$NAME" "$size" "$count"
