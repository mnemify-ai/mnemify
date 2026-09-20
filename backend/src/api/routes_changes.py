"""/api/changes — documents changed since a boundary (default: last compile).

Reads the append-only ``<data_dir>/harvest-log.jsonl`` (see
``harvester/logger.py``), keeps the per-document ``harvested`` /
``deleted_at_source`` entries after the boundary, dedupes to one row per
document, and joins each row against the harvest manifest for author
attribution (``author_name`` / ``created_by`` / ``last_modified_by``) and a
source link. The boundary defaults to the last successful terrain compile,
so the list answers "what does my map not know yet?".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src import paths
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest

router = APIRouter()


# Resolved per call, never at import: MNEMIFY_HOME (and the tests) may point
# somewhere else by the time a request lands.
def _log_path() -> Path:
    return paths.data_dir() / "harvest-log.jsonl"


def _terrain_db() -> Path:
    return paths.data_dir() / "terrain.db"


def _manifest_db() -> Path:
    return paths.data_dir() / "harvest-manifest.db"


def _parse_iso(value: str) -> datetime | None:
    try:
        ts = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _last_compile_time() -> str | None:
    terrain_db = _terrain_db()
    if not terrain_db.exists():
        return None
    from src.terrain.utils.store import TerrainStore

    store = TerrainStore(terrain_db)
    try:
        return store.get_last_compile_time()
    finally:
        store.close()


def _parse_metadata(row: dict) -> dict:
    md = row.get("metadata") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:  # noqa: BLE001
            return {}
    return md if isinstance(md, dict) else {}


@router.get("/changes")
async def list_changes(
    since: str = Query("last_compile"),
    source: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Changed documents since a boundary, newest first, with authors.

    ``since`` is either the literal ``last_compile`` (default) or an ISO
    timestamp (the client's own "last seen" watermark).
    """
    if since == "last_compile":
        boundary_iso = _last_compile_time()
        boundary = {"kind": "last_compile", "ts": boundary_iso}
    else:
        if _parse_iso(since) is None:
            raise HTTPException(status_code=422, detail="since must be 'last_compile' or an ISO timestamp")
        boundary_iso = since
        boundary = {"kind": "timestamp", "ts": boundary_iso}
    boundary_dt = _parse_iso(boundary_iso) if boundary_iso else None

    log_path = _log_path()
    log = HarvestLogger(log_path) if log_path.exists() else None
    entries = log.read_log(since=boundary_dt) if log else []

    # Truncation detection: if the boundary predates the oldest surviving log
    # entry we may be missing earlier changes (log rotated or wiped).
    truncated = False
    if log and boundary_dt is not None:
        oldest_ts: datetime | None = None
        with log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    oldest_ts = _parse_iso(json.loads(line).get("ts", ""))
                except json.JSONDecodeError:
                    continue
                break
        if oldest_ts is not None and oldest_ts > boundary_dt:
            truncated = True

    # Dedupe by (source, id), latest entry wins. File order is oldest-first,
    # so a plain overwrite leaves the newest state per document.
    by_doc: dict[tuple[str, str], dict] = {}
    for e in entries:
        action = e.get("action")
        if action not in ("harvested", "deleted_at_source"):
            continue
        if source and e.get("source") != source:
            continue
        key = (e.get("source") or "", str(e.get("id") or ""))
        if not key[1]:
            continue
        if action == "deleted_at_source":
            change = "deleted"
        else:
            change = e.get("change") or "updated"
            # A doc first seen as "new" in this window stays "new" even if
            # later entries in the same window logged it as "updated".
            prev = by_doc.get(key)
            if prev and prev["change"] == "new" and change == "updated":
                change = "new"
        by_doc[key] = {
            "source_id": key[1],
            "source": key[0],
            "title": e.get("title") or "Untitled",
            "change": change,
            "changed_at": e.get("ts"),
        }

    changes = sorted(by_doc.values(), key=lambda c: c.get("changed_at") or "", reverse=True)
    changes = changes[:limit]

    # Join against the manifest for authors / links.
    manifest_db = _manifest_db()
    manifest = HarvestManifest(manifest_db) if manifest_db.exists() else None
    last_harvest_time: str | None = None
    try:
        if manifest:
            last_dt = manifest.get_last_harvest_time_any()
            last_harvest_time = last_dt.isoformat() if last_dt else None
        for c in changes:
            row = manifest.lookup(c["source"], c["source_id"]) if manifest else None
            md = _parse_metadata(row) if row else {}
            c["doc_id"] = row.get("id") if row else None
            c["source_modified"] = row.get("source_modified") if row else None
            c["author"] = md.get("author_name") or md.get("created_by")
            c["last_modified_by"] = md.get("last_modified_by")
            c["url"] = md.get("url") or (row.get("source_url") if row else None)
            c["space"] = md.get("space_key") or md.get("space") or md.get("parent_title")
    finally:
        if manifest:
            manifest.close()

    summary: dict = {"new": 0, "updated": 0, "deleted": 0, "by_source": {}}
    for c in by_doc.values():
        summary[c["change"]] += 1
        per = summary["by_source"].setdefault(c["source"], {"new": 0, "updated": 0, "deleted": 0})
        per[c["change"]] += 1

    from src.api import compile_orchestrator as compile_orch
    from src.api import orchestrator as harvest_orch
    from src.api import scheduler

    schedule_enabled = any(
        isinstance(block, dict) and block.get("enabled")
        for block in scheduler.list_schedules().values()
    )

    return {
        "boundary": boundary,
        "summary": summary,
        "changes": changes,
        "truncated": truncated,
        "compile_running": compile_orch.state.status == "running",
        "harvest_running": harvest_orch.state.status == "running",
        "last_harvest_time": last_harvest_time,
        "schedule_enabled": schedule_enabled,
    }
