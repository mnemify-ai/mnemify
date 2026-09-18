#!/bin/sh
# Assert the backend and the web app agree on the version number.
#
#   sh .github/scripts/check-version-sync.sh
#
# There is one Mnemify version, and a release tag names both halves of it.
# `backend/pyproject.toml` feeds `src.__version__` -> `/api/health` and the
# `.app` / `.lnk` bundle version; `frontend/web/package.json` feeds nothing at
# runtime but is what a reader checks first. They drift silently, so CI checks.
#
# POSIX sh - no bashisms.

set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
PYPROJECT="$ROOT/backend/pyproject.toml"
PACKAGE_JSON="$ROOT/frontend/web/package.json"

for f in "$PYPROJECT" "$PACKAGE_JSON"; do
    if [ ! -f "$f" ]; then
        printf 'check-version-sync: %s not found.\n' "$f" >&2
        exit 1
    fi
done

# Anchored on purpose: an unanchored match would also hit `target-version`
# in [tool.ruff] and `requires-python`.
py_version=$(sed -n 's/^version = "\([^"]*\)".*$/\1/p' "$PYPROJECT" | head -1)
js_version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*$/\1/p' "$PACKAGE_JSON" | head -1)

printf 'backend/pyproject.toml      version = %s\n' "${py_version:-<not found>}"
printf 'frontend/web/package.json   version = %s\n' "${js_version:-<not found>}"

if [ -z "$py_version" ]; then
    printf '\nCould not read `version` from %s.\n' "$PYPROJECT" >&2
    exit 1
fi
if [ -z "$js_version" ]; then
    printf '\nCould not read `version` from %s.\n' "$PACKAGE_JSON" >&2
    exit 1
fi
if [ "$py_version" != "$js_version" ]; then
    printf '\nVersion mismatch: backend %s != frontend %s\n' "$py_version" "$js_version" >&2
    printf 'Bump both to the same value together, then re-run.\n' >&2
    exit 1
fi

printf '\nOK - both are %s.\n' "$py_version"
