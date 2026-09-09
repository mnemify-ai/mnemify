"""/api/audit-log — paginated read of .mnemify/harvest-log.jsonl."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from src.harvester.logger import HarvestLogger


router = APIRouter()
_LOG_PATH = Path(".mnemify") / "harvest-log.jsonl"

# Known action types written by HarvestLogger.
KNOWN_ACTIONS = (
    "harvest_started",
    "harvest_completed",
    "harvested",
    "skipped",
    "harvest_failed",
    "deleted_at_source",
    "attachment_downloaded",
)


@router.get("/audit-log")
async def audit_log(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    action: str | None = Query(None),
    source: str | None = Query(None),
) -> dict:
    """Paginated audit log. Returns newest entries first.

    Reads the existing ``.mnemify/harvest-log.jsonl`` (a JSONL file the
    HarvestLogger appends to during every run). Filters by action and source
    are exact-match.
    """
    if not _LOG_PATH.exists():
        return {
            "entries": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "actions": list(KNOWN_ACTIONS),
        }

    logger = HarvestLogger(_LOG_PATH)
    # HarvestLogger.read_log returns oldest-first; we want newest-first.
    all_entries = logger.read_log(action_filter=action)

    if source:
        all_entries = [e for e in all_entries if e.get("source") == source]

    total = len(all_entries)
    # Newest first.
    all_entries.reverse()
    page = all_entries[offset : offset + limit]

    return {
        "entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "actions": list(KNOWN_ACTIONS),
    }
