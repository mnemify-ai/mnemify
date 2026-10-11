#!/usr/bin/env bash
# Build the sample workspace end to end and export it to frontend/web/public/demo.
#
#   scripts/sample-data/build.sh [scratch-home]      (default: a fresh temp dir)
#
# Uses your Claude subscription (the `claude` CLI) for every LLM step and the
# on-device bge-small model for embeddings, so no API keys are needed. Set
# SAMPLE_AI_MODE=anthropic to use ANTHROPIC_API_KEY instead (put it in
# <scratch-home>/.env). Never touches the repo's backend/.mnemify.
#
# Any recompile changes every region/tag id, so the steps after the compile
# (curate → record → late harvest → snapshot → export) always run together.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRATCH="${1:-$(mktemp -d "${TMPDIR:-/tmp}/mnemify-sample.XXXXXX")}"
AI_MODE="${SAMPLE_AI_MODE:-claude}"
PORT="${SAMPLE_PORT:-8790}"

unset MNEMIFY_ENV_FILE MNEMIFY_YAML_FILE
export MNEMIFY_HOME="$SCRATCH"
case "$MNEMIFY_HOME" in
  "$REPO"|"$REPO"/*) echo "Refusing to build inside the repo: $MNEMIFY_HOME" >&2; exit 1 ;;
esac

py() { uv run --project "$REPO/backend" python "$@"; }
mnemify() { (cd "$REPO/backend" && uv run mnemify "$@"); }

echo "== sample workspace in $MNEMIFY_HOME (ai-mode: $AI_MODE)"

echo "== 1/9 lint corpus"
py "$HERE/lint_corpus.py"

echo "== 2/9 harvest corpus"
py "$HERE/seed.py"

echo "== 3/9 on-device embedding model"
REPO="$REPO" py - <<'PY'
import os, sys, time
sys.path.insert(0, os.path.join(os.environ["REPO"], "backend"))
from src.terrain.utils.local_embedder import is_model_downloaded, local_model_status, prepare_local_model
prepare_local_model()
while not is_model_downloaded():
    status = local_model_status()
    if status.get("status") == "error":
        sys.exit(f"model download failed: {status.get('error')}")
    time.sleep(2)
print("bge-small-en-v1.5 ready")
PY

echo "== 4/9 compile (this is the long one)"
mnemify terrain build --ai-mode "$AI_MODE" --embedding-model bge-small-en-v1.5

echo "== 5/9 start the API on :$PORT"
rm -f "$MNEMIFY_HOME/server.port"
(cd "$REPO/backend" && exec uv run mnemify up --no-browser --port "$PORT") > "$MNEMIFY_HOME/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  [ -s "$MNEMIFY_HOME/server.port" ] && break
  sleep 1
done
[ -s "$MNEMIFY_HOME/server.port" ] || { echo "server did not start; see $MNEMIFY_HOME/server.log" >&2; exit 1; }
PROVIDER="$AI_MODE"; [ "$PROVIDER" = "claude" ] || PROVIDER=anthropic

echo "== 6/9 record suggested questions"
SAMPLE_ASK_PROVIDER="$PROVIDER" py "$HERE/record_ask.py"

echo "== 7/9 curate memory + briefs, shorten the answers"
SAMPLE_ASK_PROVIDER="$PROVIDER" py "$HERE/curate.py"
py "$HERE/condense_answers.py"

echo "== 8/9 late harvest + snapshot"
py "$HERE/seed.py" --late
py "$HERE/snapshot.py"

echo "== 9/9 export + validate"
py "$HERE/export.py"
py "$HERE/validate.py"

echo "Done. Scratch home kept at $MNEMIFY_HOME (delete it when you're happy)."
