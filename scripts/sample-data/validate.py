"""Check the exported sample fixtures hang together. Exits non-zero on any problem.

    uv run --project backend python scripts/sample-data/validate.py

Every id the app will look up (note, tag, region, document, thread) must
resolve; no local paths may remain; sources must agree across files.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "frontend" / "web" / "public" / "demo"
REPO = Path(__file__).resolve().parents[2]
LEAK = re.compile(
    "|".join(
        [r"file://", r"/Users/", r"/private/tmp", r"/var/folders", r"mnemify-sample",
         r"stencil\.notion\.site", r"stencil\.atlassian\.net",
         re.escape(str(REPO)), re.escape(str(REPO.resolve()))]
    )
)

problems: list[str] = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        problems.append(msg)


def load(rel: str):
    return json.loads((DEMO / rel).read_text(encoding="utf-8"))


def main() -> None:
    if not (DEMO / "manifest.json").is_file():
        sys.exit(f"No fixtures at {DEMO}; run export.py first.")
    manifest = load("manifest.json")
    render = load("render-data.json")
    notes = load("notes.json")["notes"]
    docs = load("documents.json")
    action_items = load("action-items.json")
    regions_index = load("regions.json")
    chat = load("chat.json")

    check(render.get("version") == 3, "render-data is not v3")
    region_ids = {r["id"] for r in render["regions"]}
    tag_ids = set(render["tagIndex"])
    note_ids = {n["id"] for n in notes}
    doc_ids = {d["id"] for d in docs}

    for key, ids in (render.get("highlights") or {}).items():
        for t in ids:
            check(t in tag_ids, f"highlights.{key}: unknown tag {t}")
    for n in notes:
        check(n["regionId"] in region_ids, f"note {n['id']}: unknown region {n['regionId']}")
        check(n["primaryTagId"] in tag_ids, f"note {n['id']}: unknown primary tag {n['primaryTagId']}")
    for did, nid in manifest["docIdToNoteId"].items():
        check(did in doc_ids, f"docIdToNoteId: unknown doc {did}")
        check(nid in note_ids, f"docIdToNoteId: unknown note {nid}")
    # Bodies ship only for what the sample points at (export.py / slim.py);
    # the rest open as a preview. Whatever is pointed at must be there.
    note_to_doc = {n: d for d, n in manifest["docIdToNoteId"].items()}

    def has_body(doc_id: str) -> bool:
        return (DEMO / "docs" / f"{doc_id}.json").is_file()

    check(len(manifest["docIdToNoteId"]) >= 0.9 * len(note_ids), "fewer than 90% of notes map to a document")

    # Sources agree: every note's source exists among documents, and counts match.
    doc_sources = Counter(d["source"] for d in docs)
    note_sources = Counter(n["source"] for n in notes)
    for src, n in note_sources.items():
        check(doc_sources.get(src, 0) >= n, f"source {src}: {n} notes but {doc_sources.get(src, 0)} documents")
    stats = load("stats.json")
    check(stats["total_documents"] == len(docs), "stats.total_documents != documents.json length")

    for item in action_items["items"]:
        for nid in item.get("source_note_ids") or []:
            check(nid in note_ids, f"todo {item['id']}: unknown note {nid}")
            if nid in note_to_doc:
                check(has_body(note_to_doc[nid]), f"todo {item['id']}: source {nid} has no body")
        if item.get("region_id"):
            check(item["region_id"] in region_ids, f"todo {item['id']}: unknown region {item['region_id']}")
    buckets = Counter(i["bucket"] for i in action_items["items"])
    check(8 <= sum(v for k, v in buckets.items() if k != "probably_abandoned") <= 30,
          f"todo list should be short and live (buckets: {dict(buckets)})")

    for r in regions_index["regions"]:
        check((DEMO / "regions" / f"{r['id']}.json").is_file(), f"region {r['id']} has no regions/<id>.json")
    for path in (DEMO / "regions").glob("*.json"):
        region = json.loads(path.read_text(encoding="utf-8"))
        for t in region["threads"].get("threads", []):
            check((DEMO / "threads" / f"{t['id']}.json").is_file(), f"thread {t['id']} not exported")

    check(len(chat) == len(manifest["questions"]), "chat.json and manifest.questions disagree")
    for rec in chat:
        events = {e["event"] for e in rec["events"]}
        check({"citations", "delta", "done"} <= events, f"chat {rec['id']}: missing citations/delta/done")
        cits: dict[str, dict] = {}
        used: list[str] = []
        for e in rec["events"]:
            if e["event"] == "citations":
                cits = {c["citation_id"]: c for c in e["data"]["citations"]}
            if e["event"] == "citations_used":
                used = e["data"].get("used") or []
        check(bool(cits), f"chat {rec['id']}: no citations")
        for cid in used:
            check(cid in cits, f"chat {rec['id']}: used citation {cid} not in citations")
        for c in cits.values():
            for nid in c.get("source_note_ids") or []:
                check(nid in note_ids, f"chat {rec['id']}: citation {c['citation_id']} unknown note {nid}")
            for ref in c.get("source_refs") or []:
                if ref.get("doc_id"):
                    check(ref["doc_id"] in doc_ids, f"chat {rec['id']}: source_ref unknown doc {ref['doc_id']}")
                    check(has_body(ref["doc_id"]), f"chat {rec['id']}: cited doc {ref['doc_id']} has no body")
            if c.get("home_region_id"):
                check(c["home_region_id"] in region_ids, f"chat {rec['id']}: unknown home region")
        if rec.get("regionId"):
            check(rec["regionId"] in region_ids, f"chat {rec['id']}: unknown scope region")

    for path in DEMO.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        m = LEAK.search(text)
        check(m is None, f"{path.relative_to(DEMO)}: local path leaked ({m.group(0) if m else ''})")

    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems[:80]:
            print(f"  - {p}")
        sys.exit(1)
    print(f"OK: {len(notes)} notes, {len(docs)} documents, {len(region_ids)} regions, "
          f"{len(action_items['items'])} todos {dict(buckets)}, {len(chat)} answers")


if __name__ == "__main__":
    main()
