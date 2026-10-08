"""/api/action-items — flat, urgency-bucketed list of open todo signals.

Reads the compiled ``terrain.json`` (like /terrain/attention) but flattens
todo-kind signals across all regions/tags and computes deadline buckets
against *today at request time* — so an item extracted last week becomes
overdue as wall-clock time passes, with no recompile needed.

Buckets: ``overdue`` / ``due_soon`` / ``upcoming`` / ``no_date`` /
``probably_abandoned``. The last one holds open items whose deadline passed
more than ``STALE_DEADLINE_DAYS`` ago — kept open, never auto-resolved, but
filed at the bottom so a 2024 deadline doesn't read as an alarm in 2026.

Each item also carries ``user_status`` — the user's own review verdict
(``unverified`` / ``confirmed`` / ``dismissed``) kept in ``workspace.db`` and
keyed by the content-hashed signal id, so it survives recompiles.
``?region_id=`` narrows the list to one region's subtree.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.terrain.utils.attention import STALE_DEADLINE_DAYS
from src.terrain.utils.deadlines import parse_anchor

from . import region_scope
from .workspace_store import WorkspaceStore

router = APIRouter()

_DUE_SOON_DAYS = 7

BUCKET_RANK = {
    "overdue": 0,
    "due_soon": 1,
    "upcoming": 2,
    "no_date": 3,
    "probably_abandoned": 4,
}


def _today() -> date:
    """Module-level so tests can monkeypatch a fixed day."""
    return datetime.now(timezone.utc).date()


def _bucket(due: date | None, today: date) -> tuple[str, int | None]:
    if due is None:
        return "no_date", None
    days = (due - today).days
    if days < -STALE_DEADLINE_DAYS:
        # Still open — the user decides (dismiss or not) — but a deadline this
        # old is noise as an "overdue" alarm. See attention.STALE_DEADLINE_DAYS.
        return "probably_abandoned", days
    if days < 0:
        return "overdue", days
    if days <= _DUE_SOON_DAYS:
        return "due_soon", days
    return "upcoming", days


def build_items(
    index: region_scope.RegionIndex,
    *,
    region_id: str | None,
    today: date,
    statuses: dict[str, str],
) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    """Open todo signals (whole map, or one subtree), bucketed and sorted.
    Returns ``(items, counts_by_bucket, counts_by_status)``."""
    roots = [region_id] if region_id else list(index.roots)
    items: dict[str, dict] = {}
    for root in roots:
        for signal in region_scope.signals_in_subtree(index, root, kinds={"todo"}):
            if signal.get("status") == "resolved":
                continue
            sid = signal.get("id")
            if not sid or sid in items:
                continue
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
                # When the source note was last edited — shown next to a stale
                # deadline so the user can judge "done" vs "abandoned" themselves.
                "note_updated_at": signal.get("created_or_updated_at"),
                "source_note_ids": signal.get("source_note_ids") or [],
                "source_chunk_ids": signal.get("source_chunk_ids") or [],
                "region_id": signal.get("region_id"),
                "region_label": signal.get("region_label"),
                "tag_id": signal.get("tag_id"),
                "tag_label": signal.get("tag_label"),
                "user_status": statuses.get(sid, "unverified"),
            }

    ordered = sorted(
        items.values(),
        key=lambda it: (
            BUCKET_RANK[it["bucket"]],
            it["due_date"] or "9999-12-31",
            -it["severity"],
            it["title"].lower(),
        ),
    )
    counts = {key: 0 for key in BUCKET_RANK}
    by_status = {"unverified": 0, "confirmed": 0, "dismissed": 0}
    for item in ordered:
        counts[item["bucket"]] += 1
        by_status[item["user_status"]] = by_status.get(item["user_status"], 0) + 1
    return ordered, counts, by_status


def load_statuses() -> dict[str, str]:
    store = WorkspaceStore.open_if_exists()
    if store is None:
        return {}
    try:
        return store.statuses()
    finally:
        store.close()


@router.get("/action-items")
async def action_items(region_id: str | None = Query(default=None)):
    index = region_scope.region_index()
    if index is None:
        raise HTTPException(404, "no compiled map yet — run a compile")
    if region_id and region_id not in index.nodes:
        raise HTTPException(404, f"unknown region {region_id}")

    today = _today()
    ordered, counts, by_status = build_items(
        index, region_id=region_id, today=today, statuses=load_statuses()
    )
    return {
        "generated_at": index.generated_at or None,
        "today": today.isoformat(),
        "region_id": region_id,
        "counts": counts,
        "counts_by_status": by_status,
        "items": ordered,
    }


class StatusBody(BaseModel):
    status: Literal["unverified", "confirmed", "dismissed"]


@router.patch("/action-items/{signal_id}/status")
async def set_action_item_status(signal_id: str, body: StatusBody):
    store = WorkspaceStore()
    try:
        return store.set_status(signal_id, body.status)
    finally:
        store.close()
