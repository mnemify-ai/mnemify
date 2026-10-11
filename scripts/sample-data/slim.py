"""Cut a full sample snapshot down to what the app needs to show it.

The compile produces far more than a preview should ship: every document
body, every signal, every region's full lists. These pure helpers keep the
parts a visitor can reach (the map, the recorded answers and what they cite,
a curated set of todos, capped workspace lists) and drop the rest. export.py
applies them; nothing here touches disk.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# ── recorded answers ────────────────────────────────────────────────────

CITATION_KEYS = (
    "citation_id", "node_id", "node_type", "layer", "label",
    "edge_provenance", "source_note_ids", "home_region_id",
)
REF_KEYS = ("doc_title", "doc_id", "heading", "source_url", "updated_at")
MAX_REFS = 2
MAX_EXCERPT = 280
MIN_DELTA = 120


def _clip(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _slim_citation(c: dict) -> dict:
    out = {k: c[k] for k in CITATION_KEYS if k in c}
    refs = []
    for r in (c.get("source_refs") or [])[:MAX_REFS]:
        ref = {k: r.get(k) for k in REF_KEYS}
        ref["excerpt"] = _clip(r.get("excerpt"), MAX_EXCERPT)
        refs.append(ref)
    out["source_refs"] = refs
    return out


def slim_chat(events: list[dict]) -> list[dict]:
    """One citations event (the final list, narrowed to what the answer
    used) where the first one arrived; text merged into ~120-char events;
    everything else unchanged. Replay re-chunks the text anyway."""
    used: list[str] = []
    final: list[dict] = []
    for e in events:
        if e["event"] == "citations":
            final = e["data"].get("citations") or []
        elif e["event"] == "citations_used":
            used = e["data"].get("used") or []
    keep = set(used)
    cited = [_slim_citation(c) for c in final if not keep or c.get("citation_id") in keep]

    out: list[dict] = []
    sent_citations = False
    for e in events:
        if e["event"] == "citations":
            if not sent_citations:
                out.append({"t": e["t"], "event": "citations", "data": {"citations": cited}})
                sent_citations = True
            continue
        if e["event"] == "delta" and out and out[-1]["event"] == "delta" and len(out[-1]["data"]["text"]) < MIN_DELTA:
            out[-1] = {**out[-1], "data": {"text": out[-1]["data"]["text"] + e["data"].get("text", "")}}
            continue
        out.append(e)
    return out


def chat_doc_refs(events: list[dict]) -> tuple[set[str], set[str]]:
    """(doc ids, note ids) an answer's citations point at."""
    docs: set[str] = set()
    notes: set[str] = set()
    for e in events:
        if e["event"] != "citations":
            continue
        for c in e["data"].get("citations") or []:
            notes.update(c.get("source_note_ids") or [])
            docs.update(r["doc_id"] for r in c.get("source_refs") or [] if r.get("doc_id"))
    return docs, notes


# ── todos ───────────────────────────────────────────────────────────────

MAX_OVERDUE, OVERDUE_WITHIN_DAYS = 5, 3
MAX_DUE_SOON, MAX_UPCOMING = 10, 3


def _todo_text(item: dict) -> str:
    return re.sub(r"^\s*todo:\s*", "", item.get("title") or "", flags=re.IGNORECASE).strip()


def _same_todo(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    if SequenceMatcher(None, a, b).ratio() >= 0.6:
        return True
    wa, wb = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.75


def _readable(item: dict) -> bool:
    text = _todo_text(item)
    return 4 <= len(text) <= 80 and not text.startswith(('"', "'", "“")) and text[0].isalnum()


def curate_todos(items: list[dict]) -> list[dict]:
    """A short, believable TODO list: deduplicated (one commitment is often
    restated across several docs), readable, and weighted to what's live —
    everything due soon, a few just-slipped items, a glimpse of upcoming."""
    picked: list[dict] = []
    caps = {"overdue": MAX_OVERDUE, "due_soon": MAX_DUE_SOON, "upcoming": MAX_UPCOMING}
    taken = {k: 0 for k in caps}
    for item in items:  # server order: most urgent first within each bucket
        bucket = item.get("bucket")
        if bucket not in caps or taken[bucket] >= caps[bucket] or not _readable(item):
            continue
        if bucket == "overdue" and (item.get("days_until_due") or 0) < -OVERDUE_WITHIN_DAYS:
            continue
        text = _todo_text(item)
        if any(_same_todo(text, _todo_text(p)) for p in picked):
            continue
        picked.append(item)
        taken[bucket] += 1
    return picked


def with_items(response: dict, items: list[dict]) -> dict:
    """An action-items-shaped response narrowed to `items`, counts redone."""
    counts = {k: 0 for k in (response.get("counts") or {})}
    for it in items:
        counts[it["bucket"]] = counts.get(it["bucket"], 0) + 1
    by_status: dict[str, int] = {k: 0 for k in (response.get("counts_by_status") or {})}
    for it in items:
        s = it.get("user_status") or "unverified"
        by_status[s] = by_status.get(s, 0) + 1
    return {**response, "items": items, "counts": counts, "counts_by_status": by_status}


# ── workspaces + attention ──────────────────────────────────────────────

MAX_SIGNALS = 3
MAX_CHANGES = 6


def _slim_signal(s: dict) -> dict:
    out = dict(s)
    out["summary"] = _clip(s.get("summary"), 200)
    out.pop("source_chunk_ids", None)
    if isinstance(out.get("source_note_ids"), list):
        out["source_note_ids"] = out["source_note_ids"][:3]
    return out


MAX_MEMORY_CITATIONS = 8


def _slim_memory(m: dict, body_chars: int | None = None) -> dict:
    """Citations trimmed; with `body_chars`, the body clipped too: previews
    and ancestor regions' copies show a snippet, the owning region the whole."""
    out = {**m, "citations": [_slim_citation(c) for c in (m.get("citations") or [])[:MAX_MEMORY_CITATIONS]]}
    if body_chars is not None:
        out["body"] = _clip(m.get("body"), body_chars)
    return out


def slim_region(region: dict, kept_todo_ids: set[str]) -> dict:
    detail = dict(region["detail"])
    detail["memory_preview"] = [_slim_memory(m, 400) for m in detail.get("memory_preview") or []]
    memory = region.get("memory") or {"groups": []}
    region = {
        **region,
        "memory": {**memory, "groups": [
            {**g, "items": [_slim_memory(m, None if g.get("is_self") else 600) for m in g.get("items", [])]}
            for g in memory.get("groups", [])
        ]},
    }
    for key in ("decisions", "open_questions"):
        block = detail.get(key) or {"total": 0, "items": []}
        detail[key] = {**block, "items": [_slim_signal(s) for s in block.get("items", [])[:MAX_SIGNALS]]}
    ai = detail.get("action_items") or {"items": []}
    detail["action_items"] = with_items(ai, [i for i in ai.get("items", []) if i["id"] in kept_todo_ids])
    changes = dict(region.get("changes") or {})
    if isinstance(changes.get("changes"), list):
        changes["truncated"] = changes.get("truncated") or len(changes["changes"]) > MAX_CHANGES
        changes["changes"] = changes["changes"][:MAX_CHANGES]
    scoped = region.get("action_items") or {"items": []}
    return {
        **region,
        "detail": detail,
        "changes": changes,
        "action_items": with_items(scoped, [i for i in scoped.get("items", []) if i["id"] in kept_todo_ids]),
    }


def region_note_refs(region: dict) -> set[str]:
    """Notes behind a workspace's saved memory (its todos are covered by the
    curated list; decisions and questions open as previews)."""
    detail = region["detail"]
    notes: set[str] = set()
    for m in detail.get("memory_preview") or []:
        notes.update(m.get("source_note_ids") or [])
    for g in (region.get("memory") or {}).get("groups", []):
        for m in g.get("items", []):
            notes.update(m.get("source_note_ids") or [])
    return notes


def slim_attention(att: dict) -> dict:
    def item(x: dict) -> dict:
        return {**x, "summary": _clip(x.get("summary"), 400), "signals": [_slim_signal(s) for s in (x.get("signals") or [])[:MAX_SIGNALS]]}

    return {
        **att,
        "regions": {k: item(v) for k, v in (att.get("regions") or {}).items()},
        "tags": {k: item(v) for k, v in (att.get("tags") or {}).items()},
        "burning": (att.get("burning") or [])[:8],
    }


def attention_note_refs(att: dict) -> set[str]:
    notes: set[str] = set()
    for group in ("regions", "tags"):
        for x in (att.get(group) or {}).values():
            for s in x.get("signals") or []:
                notes.update(s.get("source_note_ids") or [])
    return notes
