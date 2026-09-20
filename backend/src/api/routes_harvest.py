"""/api/harvest/* — start, stream, cancel, history."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.harvester.manifest import HarvestManifest

from . import compile_orchestrator as compile_orch
from . import orchestrator as orch
from ._sse import _json
from .compile_bus import compile_bus
from .event_bus import bus


router = APIRouter()
logger = logging.getLogger(__name__)
from src import paths  # data dir resolved at call time — see src/paths.py


class HarvestScope(BaseModel):
    source: str
    space_id: str


class HarvestStart(BaseModel):
    sources: list[str] | None = None
    dry_run: bool = False
    force_full: bool = False
    scope: HarvestScope | None = None
    # Per-source list of scope ids to harvest for this run only — the
    # persisted scope in mnemify.yaml is left untouched. Used by Manage
    # Scope auto-harvest to pull just the newly added items.
    scope_override: dict[str, list[str]] | None = None


@router.post("/harvest")
async def start(body: HarvestStart):
    scope_dict = body.scope.model_dump() if body.scope else None
    return await orch.start_harvest(
        body.sources,
        force_full=body.force_full,
        scope=scope_dict,
        scope_override=body.scope_override,
    )


@router.post("/harvest/cancel")
async def cancel():
    return await orch.cancel_harvest()


# Harvested-data artifacts under .mnemify/ that a "reset" wipes. Sources
# stay enabled and credentials in .env are untouched — only what a harvest
# produced is removed. Anything else under .mnemify/ (e.g. OAuth token
# dirs) is left in place.
_RESET_DIRS = ["raw", "normalized"]
_RESET_FILES = [
    "harvest-manifest.db",
    "harvest-manifest.db-shm",
    "harvest-manifest.db-wal",
    "harvest-log.jsonl",
    "terrain.json",
    "terrain.db",
    "terrain.db-shm",
    "terrain.db-wal",
    "render-data.json",
    "mocknotes.json",
    "debug_sample.md",
]


@router.post("/harvest/reset")
async def reset():
    """Wipe harvested data (raw bytes, normalized sidecars, manifest, log) and
    the compiled map (terrain, render-data, notes), and return the run state
    to idle. Does **not** disable any source or clear credentials. Refused
    while a harvest or compile is running."""
    if orch.state.status == "running":
        raise HTTPException(409, "a harvest is in progress; cancel it first")
    if compile_orch.state.status == "running":
        raise HTTPException(409, "a compile is in progress; cancel it first")

    removed: list[str] = []
    for name in _RESET_DIRS:
        p = paths.data_dir() / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(f"{name}/")
    for name in _RESET_FILES:
        p = paths.data_dir() / name
        if p.exists():
            try:
                p.unlink()
                removed.append(name)
            except OSError:  # noqa: PERF203
                pass

    orch.reset_state()
    bus.reset_buffer()
    compile_orch.reset_state()
    compile_bus.reset_buffer()
    return {"ok": True, "removed": removed}


@router.get("/harvest/current")
async def current():
    s = orch.state
    return {
        "status": s.status,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "sources": s.sources,
        "summary": s.summary,
    }


@router.get("/harvest/stream")
async def stream():
    """SSE stream of progress/log/error/complete events."""

    async def event_gen():
        queue = await bus.subscribe()
        # Emit initial snapshot so late-joining UIs start at the right state.
        yield {"data": _json({"type": "snapshot", "state": {
            "status": orch.state.status,
            "sources": orch.state.sources,
            "summary": orch.state.summary,
        }})}
        # Replay recent events so a UI that connects *after* a fast source
        # (e.g. Obsidian) finished still sees its log lines + source_complete
        # markers. Subscribed first, so a dup in the tiny race window between
        # subscribe and replay is at worst a harmless repeated frame.
        for ev in bus.replay():
            yield {"data": _json(ev)}
        try:
            while True:
                # Heartbeat every 15s so proxies don't close the connection.
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"data": _json(event)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            await bus.unsubscribe(queue)

    return EventSourceResponse(event_gen())


def _derive_run_status(run: dict) -> str:
    """The harvest_runs schema has no explicit status column — derive it
    from completed_at (running vs finished) and docs_failed / errors
    (failed vs complete).
    """
    if not run.get("completed_at"):
        return "running"
    try:
        errors = json.loads(run.get("errors") or "[]")
    except (json.JSONDecodeError, TypeError):
        errors = []
    if (run.get("docs_failed") or 0) > 0 or errors:
        return "failed"
    return "complete"


@router.get("/harvest/history")
async def history():
    db = paths.data_dir() / "harvest-manifest.db"
    if not db.exists():
        return {"runs": []}
    try:
        manifest = HarvestManifest(db)
        runs = manifest.get_runs(limit=20)
    except Exception:  # noqa: BLE001
        logger.warning("harvest history fetch failed", exc_info=True)
        return {"runs": []}
    return {
        "runs": [
            {
                "id": r.get("id"),
                "started_at": r.get("started_at"),
                # Frontend's HarvestRun TS interface calls this `finished_at`;
                # the DB column is `completed_at`.
                "finished_at": r.get("completed_at"),
                "status": _derive_run_status(r),
                "sources": [r["source_type"]] if r.get("source_type") else [],
                "docs_harvested": r.get("docs_harvested") or 0,
                "docs_failed": r.get("docs_failed") or 0,
            }
            for r in runs
        ]
    }
