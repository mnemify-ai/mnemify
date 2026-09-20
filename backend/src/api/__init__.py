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
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from src import __version__, paths

from . import (
    idle,
    routes_action_items,
    routes_ask,
    routes_audit,
    routes_changes,
    routes_connections,
    routes_documents,
    routes_harvest,
    routes_schedules,
    routes_secrets,
    routes_settings,
    routes_embeddings,
    routes_system,
    routes_terrain,
    scheduler,
)


logger = logging.getLogger(__name__)


def _git_commit() -> str | None:
    """Short HEAD sha, or ``None`` when this isn't a git checkout.

    Resolved once at import so ``/api/health`` costs nothing per call. The
    explicit ``cwd`` matters: the server (and every test that ``chdir``s into
    a tmp dir) must not report some neighbouring repository's sha.
    """
    root = paths.repo_root()
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:  # noqa: BLE001 — no git on PATH, sandboxed exec, timeout
        return None
    sha = out.stdout.strip()
    return sha or None


COMMIT: str | None = _git_commit()


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
    # Load <home>/.env into os.environ before any route runs. The CLI paths do
    # this themselves; the server never did, so an API-only run saw whatever
    # the parent shell happened to export (a desktop launcher: nothing).
    try:
        from src.config import load_config

        load_config()
    except Exception:  # a malformed .env must not block boot
        logger.exception("config: failed to load %s", paths.env_file())

    # Start the in-process cron scheduler. Single-worker assumption: multiple
    # uvicorn workers would each run a scheduler and double-fire harvests.
    try:
        scheduler.start()
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: failed to start; schedules are inert")

    idle_task = None
    try:
        idle_task = idle.start()
    except Exception:
        logger.exception("idle: watchdog failed to start; the server will stay up")
    try:
        yield
    finally:
        await idle.stop(idle_task)
        try:
            scheduler.stop()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler: failed to stop cleanly")


#: Hostnames a request's ``Host`` header may carry. Mnemify binds loopback, so
#: a browser reaches it only as one of these. Extra names (a ``--host`` that is
#: not loopback, a test client's ``testserver``) come from this env var,
#: comma-separated.
ALLOWED_HOSTS_ENV = "MNEMIFY_ALLOWED_HOSTS"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})


def _allowed_hosts() -> frozenset[str]:
    extra = {
        h.strip().lower()
        for h in os.environ.get(ALLOWED_HOSTS_ENV, "").split(",")
        if h.strip()
    }
    return _LOOPBACK_HOSTS | extra


def _host_of(headers: list[tuple[bytes, bytes]]) -> str:
    """The ``Host`` header without its port, lower-cased. ``""`` if absent."""
    raw = ""
    for k, v in headers:
        if k == b"host":
            raw = v.decode("latin-1").strip()
            break
    if raw.startswith("["):  # [::1]:8783
        return raw[1 : raw.find("]")].lower() if "]" in raw else raw.lower()
    return raw.rsplit(":", 1)[0].lower() if ":" in raw else raw.lower()


class HostGuardMiddleware:
    """Refuse requests whose ``Host`` is not this machine.

    Everything mutating in this API — quit, secrets, settings reset, harvest
    reset — is reachable by any page the browser considers same-origin. A page
    on ``attacker.example`` whose DNS answer flips to ``127.0.0.1`` (DNS
    rebinding) *is* same-origin to ``http://attacker.example:8783`` and can
    send any header, so the ``X-Mnemify-Client`` guard alone is not enough.
    The one thing that page cannot forge is the ``Host`` header the browser
    sets, so a request that does not name localhost is not from our UI.

    Pure ASGI: SSE streams pass through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and (
            _host_of(scope.get("headers") or []) not in _allowed_hosts()
        ):
            response = JSONResponse({"error": "forbidden host"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


#: The header every state-changing ``/api`` request must carry. Any non-empty
#: value ("web" from the UI, "cli" from ``mnemify stop``, "test" in the suite).
CLIENT_HEADER = "X-Mnemify-Client"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ClientGuardMiddleware:
    """Refuse state-changing ``/api`` requests that lack ``X-Mnemify-Client``.

    Cross-site request forgery: a page on any other site can make the
    browser send ``POST http://localhost:8783/api/reset`` — the Host header
    is ``localhost``, so the Host guard passes, and a POST with no body and
    no custom header is a CORS "simple request" that needs no preflight. The
    browser hides the *response* from that page, but the request still runs.

    A custom header is what a foreign page cannot add: the browser would
    preflight, and this app grants no cross-origin allowance in a normal run.
    Our own UI and CLI add it trivially. GET/HEAD/OPTIONS stay open so SSE
    streams and plain reads keep working.

    Pure ASGI, like :class:`HostGuardMiddleware`.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("method", "GET") not in _SAFE_METHODS:
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                value = ""
                for k, v in scope.get("headers") or []:
                    if k == b"x-mnemify-client":
                        value = v.decode("latin-1").strip()
                        break
                if not value:
                    response = JSONResponse(
                        {"detail": f"{CLIENT_HEADER} header required"}, status_code=403
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(title="Mnemify Harvester API", version=__version__, lifespan=_lifespan)

    # Starlette wraps in *reverse* registration order: the middleware added
    # last is outermost. So these are listed innermost-first, and the resulting
    # onion is HostGuard > ClientGuard > Idle > (CORS, dev only) > routes.

    # Dev only: allow the Vite dev server (5173+) to hit /api directly when
    # developing without the built bundle. `mnemify up --reload` sets
    # MNEMIFY_DEV=1. In normal runs the static mount serves the frontend on
    # the same origin, so no cross-origin allowance exists at all. Preflights
    # (OPTIONS) pass both guards, so this can sit inside them.
    if os.environ.get("MNEMIFY_DEV") == "1":
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

    # Stamps the idle clock on real /api traffic and counts in-flight
    # /api/ask streams. Pure ASGI, so SSE isn't buffered. Inside the guards,
    # so a refused request does not count as activity.
    app.add_middleware(idle.IdleMiddleware)

    # Nothing mutates without the client header (CSRF guard).
    app.add_middleware(ClientGuardMiddleware)

    # Outermost: a request that is not addressed to this machine never
    # reaches a route, the idle clock or CORS.
    app.add_middleware(HostGuardMiddleware)

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
    app.include_router(routes_secrets.router, prefix="/api")
    app.include_router(routes_system.router, prefix="/api")
    app.include_router(routes_embeddings.router, prefix="/api")

    @app.get("/api/health")
    async def health():
        """Liveness + identity. The launcher, the single-instance check in
        ``mnemify up`` and Settings → General all read this."""
        return {
            "ok": True,
            "version": __version__,
            "commit": COMMIT,
            "platform": sys.platform,
            "paths": paths.describe(),
        }

    # A compile run left 'running' means a previous server died mid-build (the
    # compile worker thread dies with the process; there's no resume). Mark it
    # failed so /terrain/runs and /terrain/report stay honest. The chunk /
    # feature / embedding caches in terrain.db survive, so a re-run is fast.
    try:
        terrain_db = paths.data_dir() / "terrain.db"
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
        _migrate_fat_terrain_artifact(paths.data_dir())
    except Exception:  # noqa: BLE001
        logger.exception("terrain: fat-artifact migration failed; keeping as-is")

    dist = paths.web_dist_dir()
    if dist is not None:
        _mount_spa(app, dist)
    else:
        # Loud, not silent: a missing build used to boot "API-only" and show
        # a blank tab. Serve an explanation at / instead (the API still works).
        logger.warning(
            "frontend build not found (looked for frontend/web/dist; override "
            "with %s). Run `sh setup.sh` — or `npm run build` in frontend/web/.",
            paths.WEB_DIST_ENV,
        )
        _mount_no_frontend_page(app)

    return app


_NO_FRONTEND_HTML = """<!doctype html><meta charset="utf-8">
<title>Mnemify — frontend not built</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40em;margin:4em auto;padding:0 1em;color:#222}
code{background:#f3f3f3;padding:.1em .35em;border-radius:3px}</style>
<h1>Mnemify is running, but the web app isn't built yet</h1>
<p>The API is up at <code>/api/health</code>. To get the UI, run from the repo root:</p>
<pre><code>sh setup.sh</code></pre>
<p>or, by hand: <code>cd frontend/web &amp;&amp; npm ci &amp;&amp; npm run build</code>, then restart Mnemify.</p>
"""


def _mount_no_frontend_page(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    async def _no_frontend():
        return HTMLResponse(_NO_FRONTEND_HTML, status_code=503)


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
            # A bare tuple here would serialize as 200 + a 2-element array.
            return JSONResponse({"error": "not found"}, status_code=404)
        index = dist / "index.html"
        if not path:
            return FileResponse(index)
        # uvicorn does not normalise dot-segments, so ``dist / path`` can
        # point above ``dist`` (``/../../backend/.env``). Resolve and insist
        # the result is still inside the bundle before serving it.
        try:
            candidate = (dist / path).resolve()
            inside = candidate.is_relative_to(dist.resolve())
        except (OSError, ValueError):
            inside = False
        if inside and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
