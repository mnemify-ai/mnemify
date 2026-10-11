"""Give the sample workspaces what a real user would have built up: a few
answers saved to region memory, then fresh AI briefs for the top regions
(the briefs read memory, todos and changes, so this runs after record_ask).

    MNEMIFY_HOME=... uv run --project backend python scripts/sample-data/curate.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_api import client, get_json, home, sse, walk_regions

# Recorded answers worth keeping in memory, by question id.
SAVE_TO_MEMORY = ["q02", "q04", "q05", "q07"]


def answer_of(record: dict) -> tuple[str, list[dict], list[str]]:
    text = "".join(
        e["data"].get("text", "")
        for e in record["events"]
        if e["event"] == "delta" and isinstance(e["data"], dict)
    )
    citations: list[dict] = []
    used: list[str] = []
    for e in record["events"]:
        if e["event"] == "citations" and isinstance(e["data"], dict):
            citations = e["data"].get("citations") or []
        if e["event"] == "citations_used" and isinstance(e["data"], dict):
            used = e["data"].get("used") or []
    if used:
        citations = [c for c in citations if c.get("citation_id") in set(used)] or citations
    return text, citations, used


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.environ.get("SAMPLE_ASK_PROVIDER", "claude"))
    ap.add_argument("--model", default=os.environ.get("SAMPLE_BRIEF_MODEL", "sonnet"))
    ap.add_argument("--skip-memory", action="store_true")
    ap.add_argument("--max-level", type=int, default=0, help="refresh briefs for regions up to this level (0 = top-level only)")
    args = ap.parse_args()

    chat_dir = home() / "sample" / "chat"
    with client(timeout=120) as c:
        if not args.skip_memory:
            for qid in SAVE_TO_MEMORY:
                path = chat_dir / f"{qid}.json"
                if not path.is_file():
                    print(f"[memory] {qid}: not recorded, skipping")
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                text, citations, _ = answer_of(record)
                region_id = record.get("regionId")
                if not region_id:
                    homes = Counter(cit.get("home_region_id") for cit in citations if cit.get("home_region_id"))
                    if not homes:
                        print(f"[memory] {qid}: no home region in citations, skipping")
                        continue
                    region_id = homes.most_common(1)[0][0]
                note_ids = sorted({n for cit in citations for n in (cit.get("source_note_ids") or [])})
                r = c.post(
                    f"/api/regions/{region_id}/memory",
                    json={
                        "title": record["question"][:200],
                        "body": text,
                        "kind": "answer",
                        "citations": citations[:40],
                        "source_note_ids": note_ids[:100],
                        "origin": {"thread_id": record.get("threadId"), "question": record["question"]},
                    },
                )
                r.raise_for_status()
                print(f"[memory] {qid} → {region_id}")

        index = get_json(c, "/api/regions")
        details: dict[str, dict] = {}

        def detail(rid: str) -> dict:
            if rid not in details:
                details[rid] = get_json(c, f"/api/regions/{rid}")
            return details[rid]

        for rid in walk_regions(index, detail):
            region = detail(rid)["region"]
            if region["level"] > args.max_level:
                continue
            print(f"[brief] {region['name']} (level {region['level']})", flush=True)
            for _t, event, data in sse(
                c, f"/api/regions/{rid}/overview/refresh",
                {"provider": args.provider, "model": args.model},
            ):
                if event == "error":
                    sys.exit(f"brief failed for {rid}: {data}")


if __name__ == "__main__":
    main()
