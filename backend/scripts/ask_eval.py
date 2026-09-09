"""Offline retrieval eval for /api/ask — turn tuning from vibes into numbers.

Runs the real retrieval stack (node seeding + chunk-level search, no chat
LLM) over a golden set of questions and reports whether the expected
material reached the context bundle. Use it before and after touching any
retrieval constant (weights, floors, seed counts) so a "quality tweak"
can't silently regress.

Golden set format (``.mnemify/ask_eval.yaml``; see
``scripts/ask_eval.example.yaml``):

    questions:
      - q: "What did we decide about messaging inside workflow agents?"
        expect_labels:            # substring match on bundle item labels
          - "workflow"
        expect_node_ids:          # optional exact node ids
          - "tag.workflow-agents"
        expect_text:              # substring match on expanded excerpts
          - "agent communication protocol"

A question PASSES when every listed expectation category (of those present)
has at least one match in the retrieved bundle. Reports hit-rate and the
rank of the first matching item (lower = better).

Usage
-----
    cd backend
    python -m scripts.ask_eval                 # default paths
    python -m scripts.ask_eval path/to/eval.yaml

Requires a compiled corpus (``.mnemify/terrain.json`` + ``terrain.db``)
and the compile-time ``OPENAI_API_KEY`` for query embeddings (skip with
local-hash-compiled corpora).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from src.api import ask_chunks, ask_expansion, ask_retrieval
from src.api.routes_ask import _embedder_for_query
from src.terrain.utils.models import KnowledgeMap

DEFAULT_EVAL_PATH = Path(".mnemify/ask_eval.yaml")
TERRAIN_PATH = Path(".mnemify/terrain.json")


def run_eval(eval_path: Path) -> int:
    if not eval_path.is_file():
        print(f"no golden set at {eval_path} — copy scripts/ask_eval.example.yaml there")
        return 2
    if not TERRAIN_PATH.is_file():
        print("no compiled terrain — run a compile first")
        return 2

    spec = yaml.safe_load(eval_path.read_text(encoding="utf-8")) or {}
    questions = spec.get("questions") or []
    if not questions:
        print("golden set has no questions")
        return 2

    knowledge_map = KnowledgeMap.model_validate(json.loads(TERRAIN_PATH.read_text(encoding="utf-8")))
    if knowledge_map.graph is None or not knowledge_map.graph.nodes:
        print("terrain has no graph view — re-compile")
        return 2
    embedder = _embedder_for_query()

    passed = 0
    for i, case in enumerate(questions, 1):
        query = str(case.get("q") or "").strip()
        if not query:
            continue
        query_embedding = embedder.embed(query)

        chunk_matches = ask_chunks.search(query_embedding)
        chunk_hits: dict[str, float] = {}
        for hit in chunk_matches:
            chunk_hits[hit.note_node_id] = max(chunk_hits.get(hit.note_node_id, 0.0), hit.score)

        retrieval = ask_retrieval.retrieve(
            query, query_embedding, knowledge_map.graph, chunk_hits=chunk_hits,
        )
        ask_expansion.expand_bundle(retrieval.items)

        ok, detail = _judge(case, retrieval.items)
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {i}. {query}")
        print(f"       {detail}")
        if not ok:
            got = ", ".join(f"{it.citation_id}:{it.label[:40]}" for it in retrieval.items[:8])
            print(f"       bundle: {got}")

    total = len(questions)
    print(f"\n{passed}/{total} passed ({100 * passed // max(1, total)}%)")
    return 0 if passed == total else 1


def _judge(case: dict, items: list) -> tuple[bool, str]:
    labels = [(it.label or "").lower() for it in items]
    node_ids = [it.node_id for it in items]
    texts = [
        ((it.summary or "") + " " + " ".join(it.raw_excerpts)).lower()
        for it in items
    ]

    def first_rank(matches: list[bool]) -> int | None:
        for rank, m in enumerate(matches, 1):
            if m:
                return rank
        return None

    checks: list[tuple[str, int | None]] = []
    for key, haystacks in (
        ("expect_labels", labels),
        ("expect_text", texts),
    ):
        needles = [str(n).lower() for n in case.get(key) or []]
        if needles:
            rank = first_rank([any(n in h for n in needles) for h in haystacks])
            checks.append((key, rank))
    if case.get("expect_node_ids"):
        wanted = set(case["expect_node_ids"])
        rank = first_rank([nid in wanted for nid in node_ids])
        checks.append(("expect_node_ids", rank))

    if not checks:
        return False, "no expectations listed"
    ok = all(rank is not None for _, rank in checks)
    detail = ", ".join(
        f"{key}: {'rank ' + str(rank) if rank else 'MISS'}" for key, rank in checks
    )
    return ok, detail


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVAL_PATH
    raise SystemExit(run_eval(path))
