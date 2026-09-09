"""/api/action-items — flat, urgency-bucketed list of open todo signals.

Reads the compiled ``terrain.json`` (like /terrain/attention) but flattens
todo-kind signals across all regions/tags and computes deadline buckets
against *today at request time* — so an item extracted last week becomes
overdue as wall-clock time passes, with no recompile needed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.terrain.utils.deadlines import parse_anchor

router = APIRouter()
_DATA_DIR = Path(".mnemify")

_DUE_SOON_DAYS = 7


def _today() -> date:
    """Module-level so tests can monkeypatch a fixed day."""
    return datetime.now(timezone.utc).date()


def _bucket(due: date | None, today: date) -> tuple[str, int | None]:
    if due is None:
        return "no_date", None
    days = (due - today).days
    if days < 0:
        return "overdue", days
    if days <= _DUE_SOON_DAYS:
        return "due_soon", days
    return "upcoming", days


@router.get("/action-items")
async def action_items():
    path = _DATA_DIR / "terrain.json"
    if not path.is_file():
        raise HTTPException(404, "no compiled map yet — run a compile")
    try:
        bm = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"terrain.json is invalid: {e}") from e

    today = _today()
    items: dict[str, dict] = {}

    def add(signal: dict, *, region: dict, tag: dict | None) -> None:
        if signal.get("kind") != "todo" or signal.get("status") == "resolved":
            return
        sid = signal.get("id")
        if not sid or sid in items:
            return  # first attribution wins (tags walk before regions)
        due = parse_anchor(signal.get("due_date"))
        bucket, days = _bucket(due, today)
        items[sid] = {
            "id": sid,
            "title": signal.get("title") or "",
            "summary": signal.get("summary") or "",
            "severity": int(signal.get("severity") or 0),
            "status": signal.get("status") or "open",
            "owner": signal.get("owner"),
            "due_date": due.isoformat() if due else None,
            "due_text": signal.get("due_text"),
            "days_until_due": days,
            "bucket": bucket,
            "source_note_ids": signal.get("source_note_ids") or [],
            "source_chunk_ids": signal.get("source_chunk_ids") or [],
            "region_id": region.get("id"),
            "region_label": region.get("name"),
            "tag_id": tag.get("id") if tag else None,
            "tag_label": tag.get("label") if tag else None,
        }

    def walk(nodes: list) -> None:
        for node in nodes or []:
            # Tags first so items carry the most specific attribution; the
            # region-level pass then only adds signals no tag claimed.
            for tag in node.get("tags", []) or []:
                for signal in tag.get("signals", []) or []:
                    add(signal, region=node, tag=tag)
            for signal in node.get("signals", []) or []:
                add(signal, region=node, tag=None)
            walk(node.get("children", []))

    walk(bm.get("tree", []))

    bucket_rank = {"overdue": 0, "due_soon": 1, "upcoming": 2, "no_date": 3}
    ordered = sorted(
        items.values(),
        key=lambda it: (
            bucket_rank[it["bucket"]],
            it["due_date"] or "9999-12-31",
            -it["severity"],
            it["title"].lower(),
        ),
    )
    counts = {key: 0 for key in bucket_rank}
    for item in ordered:
        counts[item["bucket"]] += 1

    return {
        "generated_at": bm.get("generatedAt"),
        "today": today.isoformat(),
        "counts": counts,
        "items": ordered,
    }
