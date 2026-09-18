"""/api/terrain/* — compile (async + SSE-streamed), the v2 knowledge-map JSON, the
v3 hex render-data the 3D map reads, the companion notes registry, the run
history, and a lightweight compile report."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.terrain.utils.store import TerrainStore
from src.terrain.agents.anthropic_clients import CLAUDE_MODEL_PATTERN

from . import compile_orchestrator as compile_orch
from ._sse import _json
from .compile_bus import compile_bus


router = APIRouter()
from src import paths  # data dir resolved at call time — see src/paths.py


_EMPTY_MAP = {
    "version": 2,
    "schemaName": "cortex.brain-map",
    "workspace": "Mnemify",
    "owner": {"name": "Mnemify User", "role": "Knowledge Worker"},
    "generatedAt": None,
    "compiler": {"version": "0.2.0", "extractor": "", "clusterer": ""},
    "bounds": {"minX": -100, "maxX": 100, "minZ": -100, "maxZ": 100, "maxElevation": 100},
    "stats": {
        "regions": 0, "subRegionsTotal": 0, "tagsTotal": 0, "notes": 0,
        "sources": 0, "edges": 0, "deltas": {"tags": 0.0, "notes": 0.0, "edges": 0.0},
    },
    "highlights": {"godTags": [], "bridgeTags": [], "trendingTags": [], "isolatedTags": []},
    "tree": [],
    "edges": {"regionEdges": [], "tagEdges": []},
}


# ─── compile lifecycle ──────────────────────────────────────────────

class CompileStart(BaseModel):
    source: str | None = None
    ai_mode: str | None = None  # "openai" | "anthropic" | "local" | "claude"; None -> saved default
    fresh: bool = False  # True -> ignore caches, recompute everything
    # Per-run overrides. All None -> fall back to saved compile-settings defaults
    # (GET/PATCH /api/settings/compile). Resolution happens in start_compile.
    claude_extract_model: str | None = Field(default=None, pattern=CLAUDE_MODEL_PATTERN, max_length=100)
    claude_name_model: str | None = Field(default=None, pattern=CLAUDE_MODEL_PATTERN, max_length=100)
    openai_model: str | None = Field(default=None, max_length=100)
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] | None = None
    llm_concurrency: int | None = Field(default=None, ge=1, le=32)
    extract_batch_size: int | None = Field(default=None, ge=1, le=64)


@router.post("/terrain/build")
async def build_terrain(body: CompileStart | None = None):
    """Kick off a compile in the background; returns immediately. Body:
    ``{source?, ai_mode?, fresh?}``. Returns ``{ok, ai_mode}`` or
    ``{ok:false, reason}``."""
    body = body or CompileStart()
    return await compile_orch.start_compile(
        body.source,
        body.ai_mode,
        body.fresh,
        claude_extract_model=body.claude_extract_model,
        claude_name_model=body.claude_name_model,
        openai_model=body.openai_model,
        embedding_model=body.embedding_model,
        llm_concurrency=body.llm_concurrency,
        extract_batch_size=body.extract_batch_size,
    )


@router.post("/terrain/cancel")
async def cancel_terrain():
    return await compile_orch.cancel_compile()


@router.get("/terrain/current")
async def terrain_current():
    return compile_orch.snapshot()


@router.get("/terrain/stream")
async def terrain_stream():
    """SSE stream of compile-progress events (snapshot / per-stage progress /
    log / error / complete / failed)."""

    async def event_gen():
        queue = await compile_bus.subscribe()
        yield {"data": _json({"type": "snapshot", "state": compile_orch.snapshot()})}
        for ev in compile_bus.replay():
            yield {"data": _json(ev)}
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"data": _json(ev)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            await compile_bus.unsubscribe(queue)

    return EventSourceResponse(event_gen())


# ─── compiled artifacts ─────────────────────────────────────────────

@router.get("/terrain")
async def get_terrain():
    """The raw v2 knowledge-map JSON (or an empty stub if nothing's compiled yet).

    Streamed straight from disk — parsing and re-serializing a multi-MB
    artifact per request bought nothing. no-store for the same reason as
    render-data: compiles rewrite the file."""
    path = paths.data_dir() / "terrain.json"
    if not path.exists():
        return _EMPTY_MAP
    return FileResponse(
        path, media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/terrain/render-data")
async def terrain_render_data():
    """The v3 hex render-data the 3D map reads. 404 → nothing compiled yet.

    Served no-store: this file is rewritten on every compile, so any browser
    caching makes a fresh recompile silently invisible (stale layout shown).
    """
    path = paths.data_dir() / "render-data.json"
    if not path.is_file():
        raise HTTPException(404, "no compiled map yet — run a compile")
    return FileResponse(
        path, media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/terrain/notes")
async def terrain_notes():
    """The companion notes registry (titles/authors/excerpts the map's drawer
    reads). 404 → nothing compiled yet."""
    path = paths.data_dir() / "mocknotes.json"
    if not path.is_file():
        raise HTTPException(404, "no compiled notes yet — run a compile")
    return FileResponse(
        path, media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/terrain/attention")
async def terrain_attention():
    """Lean attention/signal index for region panels and burn overlays.

    The full terrain graph can be large because it contains embeddings. This
    endpoint returns only source-grounded operational facts needed by the UI.
    """
    path = paths.data_dir() / "terrain.json"
    if not path.is_file():
        raise HTTPException(404, "no compiled map yet — run a compile")
    try:
        bm = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"terrain.json is invalid: {e}") from e

    regions: dict[str, dict] = {}
    tags: dict[str, dict] = {}

    def walk(nodes: list) -> None:
        for node in nodes or []:
            regions[node.get("id")] = {
                "id": node.get("id"),
                "type": "region",
                "label": node.get("name"),
                "summary": node.get("summary") or "",
                "attentionScore": float(node.get("attentionScore") or 0),
                "attentionLevel": node.get("attentionLevel") or "none",
                "signals": node.get("signals") or [],
            }
            for tag in node.get("tags", []) or []:
                tags[tag.get("id")] = {
                    "id": tag.get("id"),
                    "type": "tag",
                    "label": tag.get("label"),
                    "summary": tag.get("blurb") or "",
                    "attentionScore": float(tag.get("attentionScore") or 0),
                    "attentionLevel": tag.get("attentionLevel") or "none",
                    "signals": tag.get("signals") or [],
                }
            walk(node.get("children", []))

    walk(bm.get("tree", []))
    return {
        "generated_at": bm.get("generatedAt"),
        "regions": regions,
        "tags": tags,
        "burning": _top_burning_items(bm),
    }


@router.get("/terrain/runs")
async def terrain_runs(limit: int = 20):
    db_path = paths.data_dir() / "terrain.db"
    # Guard: TerrainStore.__init__ calls sqlite3.connect which creates
    # the file as a side-effect. We must not create it from a GET path —
    # otherwise a wiped .mnemify/ silently grows back on the next
    # page navigation (LastCompiledPill polls this).
    if not db_path.is_file():
        return {"runs": []}
    store = TerrainStore(db_path)
    try:
        return {"runs": store.recent_runs(limit=limit)}
    finally:
        store.close()


@router.get("/terrain/report")
async def terrain_report():
    """Lightweight compile report: headline stats/highlights + the last run's
    metadata + per-source doc counts. (The /compile page renders this; it
    doesn't need the whole v2 terrain.json.)"""
    tpath = paths.data_dir() / "terrain.json"
    db_path = paths.data_dir() / "terrain.db"
    # Guard: TerrainStore.__init__ creates the DB as a side-effect of
    # sqlite3.connect. This endpoint is polled on every page (via
    # LastCompiledPill), so unconditional construction silently
    # re-creates terrain.db after a wipe — defeating `mnemify reset`.
    if not db_path.is_file():
        runs: list[dict] = []
    else:
        store = TerrainStore(db_path)
        try:
            runs = store.recent_runs(limit=1)
        except Exception:  # noqa: BLE001
            runs = []
        finally:
            store.close()
    last_run = runs[0] if runs else None

    ai_mode = None
    seconds = None
    if last_run:
        try:
            ai_mode = (json.loads(last_run.get("params") or "{}")).get("ai_mode")
        except Exception:  # noqa: BLE001
            ai_mode = None
        s, c = last_run.get("started_at"), last_run.get("completed_at")
        if s and c:
            try:
                seconds = max(
                    0,
                    int((datetime.fromisoformat(c) - datetime.fromisoformat(s)).total_seconds()),
                )
            except Exception:  # noqa: BLE001
                seconds = None

    by_source: dict[str, int] = {}
    try:
        from src.harvester.manifest import HarvestManifest
        mdb = paths.data_dir() / "harvest-manifest.db"
        if mdb.exists():
            for r in HarvestManifest(mdb).get_documents():
                k = r.get("source_type") or "?"
                by_source[k] = by_source.get(k, 0) + 1
    except Exception:  # noqa: BLE001
        by_source = {}

    if not tpath.exists():
        return {
            "exists": False, "generated_at": None, "ai_mode": ai_mode, "seconds": seconds,
            "stats": None, "highlights": None, "compiler": None,
            "by_source": by_source, "last_run": last_run,
        }
    try:
        bm = json.loads(tpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"terrain.json is invalid: {e}") from e
    highlights = bm.get("highlights") or {}
    return {
        "exists": True,
        "generated_at": bm.get("generatedAt"),
        "ai_mode": ai_mode,
        "seconds": seconds,
        "stats": bm.get("stats"),
        "highlights": highlights,
        "burning": _top_burning_items(bm),
        # Real LLM-generated labels for the highlighted tag ids. The highlights
        # carry only ids (e.g. ``tag.node_3566…``); without this the UI can only
        # prettify the id into "Node 3566…". Scoped to highlight ids to keep the
        # payload small.
        "tag_labels": _highlight_tag_labels(bm, highlights),
        "compiler": bm.get("compiler"),
        "by_source": by_source,
        "last_run": last_run,
    }


def _highlight_tag_labels(bm: dict, highlights: dict) -> dict[str, str]:
    """id → label for every tag referenced in highlights, read from the v2 tree."""
    wanted: set[str] = set()
    for ids in highlights.values():
        if isinstance(ids, list):
            wanted.update(ids)
    if not wanted:
        return {}
    labels: dict[str, str] = {}

    def walk(nodes: list) -> None:
        for node in nodes or []:
            for tag in node.get("tags", []) or []:
                tid = tag.get("id")
                if tid in wanted and tag.get("label"):
                    labels[tid] = tag["label"]
            walk(node.get("children", []))

    walk(bm.get("tree", []))
    return labels


def _top_burning_items(bm: dict, limit: int = 8) -> list[dict]:
    items: list[dict] = []

    def add_node(node: dict) -> None:
        score = float(node.get("attentionScore") or 0)
        if score > 0:
            items.append({
                "id": node.get("id"),
                "type": "region",
                "label": node.get("name") or node.get("id"),
                "attentionScore": round(score, 2),
                "attentionLevel": node.get("attentionLevel") or "none",
                "signalCount": len(node.get("signals") or []),
            })
        for tag in node.get("tags", []) or []:
            tag_score = float(tag.get("attentionScore") or 0)
            if tag_score > 0:
                items.append({
                    "id": tag.get("id"),
                    "type": "tag",
                    "label": tag.get("label") or tag.get("id"),
                    "attentionScore": round(tag_score, 2),
                    "attentionLevel": tag.get("attentionLevel") or "none",
                    "signalCount": len(tag.get("signals") or []),
                })
        for child in node.get("children", []) or []:
            add_node(child)

    for root in bm.get("tree", []) or []:
        add_node(root)
    items.sort(key=lambda item: (-item["attentionScore"], item["type"], item["label"]))
    return items[:limit]
