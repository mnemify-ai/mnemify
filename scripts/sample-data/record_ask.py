"""Ask every question in questions.yaml against the running sample server and
record the raw SSE stream (with timings) for the app to replay.

    MNEMIFY_HOME=... uv run --project backend python scripts/sample-data/record_ask.py

Writes ``$MNEMIFY_HOME/sample/chat/<id>.json``. Threads are saved server-side
as ``demo-<id>`` so the region workspaces' Activity shows them too.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_api import client, get_json, home, sse, walk_regions

HERE = Path(__file__).resolve().parent


def find_region(c, wanted: list[str]) -> tuple[str, str] | None:
    index = get_json(c, "/api/regions")
    details: dict[str, dict] = {}

    def detail(rid: str) -> dict:
        if rid not in details:
            details[rid] = get_json(c, f"/api/regions/{rid}")
        return details[rid]

    ids = walk_regions(index, detail)
    for needle in wanted:
        for rid in ids:
            name = detail(rid)["region"]["name"]
            if needle.lower() in name.lower():
                return rid, name
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.environ.get("SAMPLE_ASK_PROVIDER", "claude"))
    ap.add_argument("--model", default=os.environ.get("SAMPLE_ASK_MODEL", "opus"))
    ap.add_argument("--only", nargs="*", help="question ids to (re)record")
    args = ap.parse_args()

    spec = yaml.safe_load((HERE / "questions.yaml").read_text(encoding="utf-8"))
    out_dir = home() / "sample" / "chat"
    out_dir.mkdir(parents=True, exist_ok=True)

    with client(timeout=120) as c:
        for q in spec["questions"]:
            if args.only and q["id"] not in args.only:
                continue
            region = None
            if q.get("region"):
                region = find_region(c, list(q["region"]))
                if region is None:
                    print(f"[{q['id']}] no region matched {q['region']!r}; asking unscoped")
            body = {
                "query": q["question"],
                "provider": args.provider,
                "model": args.model,
                "history": [],
                "thread_id": f"demo-{q['id']}",
            }
            if region:
                body["region_id"] = region[0]
            print(f"[{q['id']}] {q['question']}" + (f"  (scoped to {region[1]})" if region else ""))
            events = []
            for t, event, data in sse(c, "/api/ask", body):
                events.append({"t": t, "event": event, "data": data})
                if event == "error":
                    sys.exit(f"[{q['id']}] ask failed: {data}")
            text = "".join(e["data"].get("text", "") for e in events if e["event"] == "delta" and isinstance(e["data"], dict))
            if not text.strip():
                sys.exit(f"[{q['id']}] empty answer")
            record = {
                "id": q["id"],
                "label": q["label"],
                "question": q["question"],
                "regionId": region[0] if region else None,
                "regionName": region[1] if region else None,
                "provider": args.provider,
                "model": args.model,
                "threadId": f"demo-{q['id']}",
                "events": events,
            }
            (out_dir / f"{q['id']}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
            print(f"      {len(events)} events, {len(text)} chars, {events[-1]['t'] / 1000:.1f}s")


if __name__ == "__main__":
    main()
