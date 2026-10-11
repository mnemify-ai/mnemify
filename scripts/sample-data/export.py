"""Turn a sample snapshot into the app's static fixtures (frontend/web/public/demo).

    MNEMIFY_HOME=... uv run --project backend python scripts/sample-data/export.py

Reads ``$MNEMIFY_HOME/sample/{snap,chat}`` and rewrites ``public/demo`` from
scratch, slimmed (slim.py) to what a visitor can reach: the whole map and
document list, but bodies only for documents the answers, todos and
workspaces point at, a curated handful of todos and capped workspace lists. Responses keep their API shapes so the app's own hooks can read them;
the only changes are privacy/sanity fixes made by ``sanitize``:

* no local paths: ``raw_path``/``normalized_path``/``root_path`` dropped, the
  scratch home and any ``/Users/...`` path scrubbed from every string;
* ``file://`` source URLs (local notes) blanked, since they point nowhere;
* documents get the author the compiler resolved for their note when the
  documents API had none (Obsidian/local frontmatter authors);
* render-data highlight lists only keep tag ids that exist in the bake;
* recorded answers lose the agent's narration between tool calls ("I'll
  start by orienting myself…"), which the stream glues onto the answer, and
  so does every saved copy of those answers (memory, threads).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "frontend" / "web" / "public" / "demo"
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(HERE))

import slim
from sample_api import home

from src.utils.hashing import short_hash

SIGN_OFF = re.compile(r"\A\s*(?:I've gathered enough[^.\n]*\.|I have enough to answer[^.\n]*\.)\s*")
DROP_KEYS = {"raw_path", "normalized_path", "root_path", "retrieval_debug"}
# A local path at the start of a token (not inside a URL like
# https://x.com/home/…). Paths with spaces are caught by the explicit roots.
USERS_PATH = re.compile(r"(?<![\w:/.])(?:/private)?/(?:Users|home|tmp|var/folders)/[^\s\"')\]]*")
# Fake source hosts → a reserved TLD, so "Open in Notion" can never reach a
# real tenant. (fixture_plugin.py mints .example URLs for new builds.)
HOST_REWRITES = {
    "https://stencil.notion.site/": "https://stencil.notion.example/",
    "https://stencil.atlassian.net/": "https://stencil.atlassian.example/",
}
# Saved copies of a recorded answer: only these fields get its narration cut.
ANSWER_FIELDS = {"body", "text"}


def note_id_for(doc_id: str) -> str:
    # Must match TerrainCompiler._note_id_for.
    return f"n-{short_hash(doc_id, 8)}"


def strip_narration(events: list[dict]) -> tuple[list[dict], str]:
    """Drop answer text streamed before the agent's last tool step: that's
    its running commentary, not the answer. Returns the kept events and the
    dropped text (to strip from saved copies of the answer)."""
    last_step = max((i for i, e in enumerate(events) if e["event"] == "agent_step"), default=-1)
    if last_step < 0:
        return events, ""  # not an agentic answer: nothing to strip
    dropped = "".join(
        e["data"].get("text", "")
        for e in events[:last_step]
        if e["event"] == "delta" and isinstance(e["data"], dict)
    )
    kept = [e for i, e in enumerate(events) if not (e["event"] == "delta" and i < last_step)]
    # …and the sign-off it sometimes opens the answer with.
    text = "".join(e["data"].get("text", "") for e in kept if e["event"] == "delta" and isinstance(e["data"], dict))
    lead = SIGN_OFF.match(text)
    trim = len(lead.group(0)) if lead else 0
    if trim:
        dropped += text[:trim]
        for e in kept:
            if trim <= 0:
                break
            if e["event"] == "delta" and isinstance(e["data"], dict):
                piece = e["data"].get("text", "")
                cut = min(trim, len(piece))
                e["data"] = {**e["data"], "text": piece[cut:]}
                trim -= cut
    return kept, dropped


class Sanitizer:
    def __init__(self, scratch: Path):
        roots = {str(scratch), str(scratch.resolve()), str(REPO), str(REPO.resolve())}
        # Longest first, so a nested root is removed whole.
        self.scratch = sorted(roots, key=len, reverse=True)
        self.hits = 0
        self.preambles: list[str] = []

    def text(self, s: str, key: str | None = None) -> str:
        orig = s
        if s.startswith("file://"):
            return ""
        if key in ANSWER_FIELDS:
            for p in self.preambles:
                if s.startswith(p):
                    s = s[len(p):].lstrip()
        for old, new in HOST_REWRITES.items():
            s = s.replace(old, new)
        for root in self.scratch:
            s = s.replace(root, "")
        s = USERS_PATH.sub("", s)
        if s != orig:
            self.hits += 1
        return s

    def __call__(self, value, key: str | None = None):
        if isinstance(value, dict):
            return {k: self(v, k) for k, v in value.items() if k not in DROP_KEYS}
        if isinstance(value, list):
            return [self(v, key) for v in value]
        if isinstance(value, str):
            return self.text(value, key)
        return value


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(rel: str, payload) -> None:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    scratch = home()
    snap = scratch / "sample" / "snap"
    chat_dir = scratch / "sample" / "chat"
    if not (snap / "terrain-render-data.json").is_file():
        sys.exit(f"No snapshot at {snap}; run snapshot.py first.")
    clean = Sanitizer(scratch)
    # Recorded answers first: their narration is stripped everywhere below.
    raw_chat = []
    condensed_dir = scratch / "sample" / "chat-condensed"
    for path in sorted(chat_dir.glob("*.json")):
        rec = load(path)
        rec["events"], dropped = strip_narration([e for e in rec["events"] if e["event"] not in DROP_KEYS])
        if dropped.strip():
            clean.preambles.append(dropped.strip())
        # A shortened version (condense_answers.py) replaces what's replayed;
        # saved copies elsewhere (memory, threads) keep the full answer.
        short = condensed_dir / path.name
        if short.is_file():
            rec = {**rec, "events": [e for e in load(short)["events"] if e["event"] not in DROP_KEYS]}
        raw_chat.append(rec)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # ── map ── (whole: it's small, and every region is clickable)
    render = load(snap / "terrain-render-data.json")
    known_tags = set(render.get("tagIndex") or [])
    hl = render.get("highlights") or {}
    for key in ("godTagIds", "bridgeTagIds", "trendingTagIds"):
        hl[key] = [t for t in hl.get(key) or [] if t in known_tags]
    render["highlights"] = hl
    write("render-data.json", clean(render))

    notes_file = clean(load(snap / "terrain-notes.json"))
    notes = notes_file["notes"]
    note_by_id = {n["id"]: n for n in notes}
    write("notes.json", notes_file)
    write("attention.json", clean(slim.slim_attention(load(snap / "terrain-attention.json"))))
    write("report.json", clean(load(snap / "terrain-report.json")))

    # ── chat ── (labels from questions.yaml, so rewording a button doesn't
    # need a re-recording)
    import yaml

    labels = {q["id"]: q["label"] for q in yaml.safe_load((HERE / "questions.yaml").read_text())["questions"]}
    chat = [
        clean({**rec, "label": labels.get(rec["id"], rec["label"]), "events": slim.slim_chat(rec["events"])})
        for rec in raw_chat
    ]
    write("chat.json", chat)

    # ── todos + workspaces ──
    full_items = clean(load(snap / "action-items.json"))
    kept_items = slim.curate_todos(full_items["items"])
    kept_ids = {i["id"] for i in kept_items}
    action_items = slim.with_items(full_items, kept_items)
    write("action-items.json", action_items)
    write("regions.json", clean(load(snap / "regions.json")))
    shown_notes: set[str] = set()
    for path in sorted((snap / "regions").glob("*.json")):
        region = slim.slim_region(clean(load(path)), kept_ids)
        shown_notes |= slim.region_note_refs(region)
        write(f"regions/{path.name}", region)
    for path in sorted((snap / "threads").glob("*.json")):
        write(f"threads/{path.name}", clean(load(path)))

    # ── documents ── every row (the tree and the Documents page list them
    # all); bodies only where something in the sample points.
    rows = clean(load(snap / "documents.json"))
    doc_to_note: dict[str, str] = {}
    for row in rows:
        nid = note_id_for(row["id"])
        note = note_by_id.get(nid)
        if note:
            doc_to_note[row["id"]] = nid
            if not row.get("author") and note.get("author") not in (None, "", "Unknown"):
                row["author"] = note["author"]
        row["excerpt"] = slim._clip(row.get("excerpt"), 160)
    write("documents.json", rows)
    note_to_doc = {n: d for d, n in doc_to_note.items()}
    wanted_docs: set[str] = set()
    for rec in chat:
        docs, cited_notes = slim.chat_doc_refs(rec["events"])
        wanted_docs |= docs
        shown_notes |= cited_notes
    for item in kept_items:
        shown_notes.update(item.get("source_note_ids") or [])
    wanted_docs |= {note_to_doc[n] for n in shown_notes if n in note_to_doc}
    # Late documents: "what changed" points at them.
    wanted_docs |= {c.get("doc_id") for c in load(snap / "changes.json").get("changes", []) if c.get("doc_id")}
    rows_by_id = {r["id"]: r for r in rows}
    bodies = 0
    for path in sorted((snap / "docs").glob("*.json")):
        did = path.stem
        if did not in wanted_docs:
            continue
        doc = clean(load(path))
        doc["row"] = {**doc["row"], "author": rows_by_id.get(did, {}).get("author") or doc["row"].get("author")}
        write(f"docs/{did}.json", doc)
        bodies += 1

    stats = clean(load(snap / "documents-stats.json"))
    write("stats.json", stats)
    write("changes.json", clean(load(snap / "changes.json")))

    manifest = {
        "version": 1,
        "exportedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        # The day the server bucketed todos against; the app shifts every
        # date by (real today - this) so "due in 3 days" stays true.
        "today": action_items["today"],
        # The compile's real finish time (render-data's generatedAt is a
        # fixed bake stamp). Doubles as the sample's "last visit".
        "generatedAt": load(snap / "terrain-report.json").get("generated_at") or render.get("generatedAt"),
        "counts": {
            "documents": len(rows),
            "notes": len(notes),
            "regions": len(render.get("regions") or []),
            "tags": len(known_tags),
            "actionItems": len(action_items.get("items") or []),
            "documentBodies": bodies,
            "questions": len(chat),
        },
        "questions": [
            {"id": c["id"], "label": c["label"], "question": c["question"], "regionId": c.get("regionId")}
            for c in chat
        ],
        "docIdToNoteId": doc_to_note,
    }
    write("manifest.json", manifest)

    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"Exported {len(rows)} documents ({bodies} with bodies), {len(notes)} notes, "
          f"{len(kept_items)} todos, {len(chat)} answers → {OUT} "
          f"({size / 1e6:.1f} MB; {clean.hits} strings scrubbed)")


if __name__ == "__main__":
    main()
