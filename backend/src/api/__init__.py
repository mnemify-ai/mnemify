"""FastAPI app — the HTTP layer that fronts the existing harvester.

The frontend (`frontend/`) talks to this through a small, stable
set of routes under `/api/`. The harvester plugins underneath remain
unchanged: the API layer just calls their `test_connection`,
`list_documents`, `fetch_document`, etc. methods and streams events.

Credentials travel through `credential_store` (writes `.env`) and
`yaml_writer` (writes `mnemify.yaml`) — the same files the CLI
already reads.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from . import (
    routes_action_items,
    routes_ask,
    routes_audit,
    routes_changes,
    routes_connections,
    routes_documents,
    routes_harvest,
    routes_schedules,
    routes_settings,
    routes_terrain,
    scheduler,
)


logger = logging.getLogger(__name__)


def _migrate_fat_terrain_artifact(data_dir: Path) -> None:
    """Slim a pre-V0.9 terrain.json in place: backfill graph-node vectors
    into terrain.db, then atomically rewrite the artifact without inline
    ``embedding``/``context_embedding`` fields. Skips lean artifacts.

    Order matters: the table is written and committed before the artifact is
    replaced, so a crash in between leaves a fat-but-valid terrain.json.
    Tree/tag inline vectors are dropped without backfill — the graph
    duplicates them and nothing reads tree vectors at runtime."""
    import json

    terrain_path = data_dir / "terrain.json"
    if not terrain_path.is_file():
        return
    data = json.loads(terrain_path.read_text(encoding="utf-8"))
    nodes = (data.get("graph") or {}).get("nodes") or []
    fat = [n for n in nodes if n.get("embedding") or n.get("context_embedding")]
    if not fat:
        return

    from src.terrain.utils.emitter import _strip_vector_fields
    from src.terrain.utils.store import TerrainStore

    store = TerrainStore(data_dir / "terrain.db")
    try:
        store.replace_graph_node_vectors(
            {n["id"]: n["embedding"] for n in nodes if n.get("embedding")}
        )
    finally:
        store.close()

    _strip_vector_fields(data)
    tmp = terrain_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(terrain_path)
    logger.info(
        "terrain: migrated fat terrain.json — moved %d node vectors to terrain.db",
        len(fat),
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Start the in-process cron scheduler. Single-worker assumption: multiple
    # uvicorn workers would each run a scheduler and double-fire harvests.
    try:
        scheduler.start()
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: failed to start; schedules are inert")
    try:
        yield
    finally:
        try:
            scheduler.stop()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler: failed to stop cleanly")


def create_app() -> FastAPI:
    app = FastAPI(title="Mnemify Harvester API", version="0.1.0", lifespan=_lifespan)

    # Dev: allow the Vite dev server (5173+) to hit /api directly when
    # developing without the built bundle. In production the static
    # mount serves the frontend on the same origin, no CORS needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://localhost:5176",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_connections.router, prefix="/api")
    app.include_router(routes_harvest.router, prefix="/api")
    app.include_router(routes_documents.router, prefix="/api")
    app.include_router(routes_settings.router, prefix="/api")
    app.include_router(routes_terrain.router, prefix="/api")
    app.include_router(routes_audit.router, prefix="/api")
    app.include_router(routes_changes.router, prefix="/api")
    app.include_router(routes_schedules.router, prefix="/api")
    app.include_router(routes_ask.router, prefix="/api")
    app.include_router(routes_action_items.router, prefix="/api")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "version": "0.1.0"}

    # A compile run left 'running' means a previous server died mid-build (the
    # compile worker thread dies with the process; there's no resume). Mark it
    # failed so /terrain/runs and /terrain/report stay honest. The chunk /
    # feature / embedding caches in terrain.db survive, so a re-run is fast.
    try:
        terrain_db = Path(".mnemify") / "terrain.db"
        if terrain_db.is_file():
            from src.terrain.utils.store import TerrainStore

            _store = TerrainStore(terrain_db)
            try:
                n = _store.fail_orphaned_runs()
                if n:
                    logger.info("terrain: marked %d orphaned compile run(s) as failed", n)
            finally:
                _store.close()
    except Exception:  # noqa: BLE001
        logger.debug("terrain: orphaned-run cleanup skipped", exc_info=True)

    # One-time migration: pre-V0.9 compiles serialized every graph/tree
    # embedding into terrain.json (~98% of a 300MB+ file). Move the raw graph
    # vectors into terrain.db and rewrite the artifact lean. Best-effort and
    # atomic — a failure leaves the fat artifact fully usable.
    try:
        _migrate_fat_terrain_artifact(Path(".mnemify"))
    except Exception:  # noqa: BLE001
        logger.exception("terrain: fat-artifact migration failed; keeping as-is")

    # backend/src/api/__init__.py is the repo root; the app lives at
    # frontend/web/ so its build is frontend/web/dist (older layouts used
    # frontend/dist — accept either).
    repo_root = Path(__file__).resolve().parents[3]
    dist = next(
        (
            d
            for d in (repo_root / "frontend" / "web" / "dist", repo_root / "frontend" / "dist")
            if d.is_dir()
        ),
        None,
    )
    if dist is not None:
        _mount_spa(app, dist)
    else:
        logger.info(
            "frontend build not found; API-only mode. "
            "Run `npm run build` (or `npm run dev`) in frontend/web/."
        )

    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve /assets and the SPA index fallback for client-side routing."""
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="assets",
        )

    # Static files at the dist root (favicon, mockServiceWorker, etc.)
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str):
        if path.startswith("api/"):
            return {"error": "not found"}, 404
        candidate = dist / path if path else dist / "index.html"
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
