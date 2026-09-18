"""Glue between the UI compile lifecycle and the synchronous ``TerrainCompiler``.

Mirrors ``src/api/orchestrator.py`` (the harvest one). The compiler is
CPU/IO-bound and synchronous, so ``start_compile`` runs ``compiler.build`` in a
worker thread via ``asyncio.to_thread``. The compiler's ``progress`` callback
fires on that worker thread — it must NOT touch the asyncio queues directly, so
it hops back to the event loop via ``loop.call_soon_threadsafe``. Cancellation
is cooperative: a ``threading.Event`` the compiler checks between chunks/names.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from ._rate import _Rate
from .compile_bus import compile_bus

logger = logging.getLogger(__name__)
from src import paths  # data dir resolved at call time — see src/paths.py


# ─── Run state ──────────────────────────────────────────────────────

class CompileState:
    status: str = "idle"  # idle | running | complete | failed
    started_at: float | None = None
    finished_at: float | None = None
    stage: str | None = None
    counts: dict[str, Any] = {}
    summary: dict[str, Any] | None = None
    error: str | None = None
    ai_mode: str | None = None
    run_id: str | None = None
    _task: asyncio.Task | None = None
    _cancel: threading.Event = threading.Event()


state = CompileState()


def reset_state() -> None:
    """Return the compile state to idle (used by the reset endpoints)."""
    state.status = "idle"
    state.started_at = None
    state.finished_at = None
    state.stage = None
    state.counts = {}
    state.summary = None
    state.error = None
    state.ai_mode = None
    state.run_id = None
    state._task = None
    state._cancel = threading.Event()


def is_running() -> bool:
    """Whether a compile is in flight.

    The idle watchdog asks this before quitting the process — the compile
    worker thread dies with the server and there is no resume, so a false
    "idle" here silently throws away a long build.
    """
    return state.status == "running"


def snapshot() -> dict[str, Any]:
    return {
        "status": state.status,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "stage": state.stage,
        "counts": state.counts,
        "summary": state.summary,
        "error": state.error,
        "ai_mode": state.ai_mode,
        "run_id": state.run_id,
    }


# ─── Public entrypoints ─────────────────────────────────────────────

async def start_compile(
    source: str | None = None,
    ai_mode: str | None = None,
    fresh: bool = False,
    *,
    claude_extract_model: str | None = None,
    claude_name_model: str | None = None,
    openai_model: str | None = None,
    embedding_model: str | None = None,
    llm_concurrency: int | None = None,
    extract_batch_size: int | None = None,
    extract_effort: str | None = None,
    name_effort: str | None = None,
) -> dict:
    """Kick off a compile in the background. Returns immediately.

    ``fresh=True`` is a full recompile: feature/embedding/name caches are
    ignored and everything is recomputed from scratch (then re-saved).

    This is the resolution layer: any per-run override left as ``None`` falls
    back to the saved compile-settings defaults (GET/PATCH /api/settings/compile).
    The compiler receives concrete explicit args and never reads YAML itself.
    """
    if state.status == "running":
        return {"ok": False, "reason": "a compile is already running"}
    # Never compile mid-harvest: the manifest and harvested docs are still
    # changing under us, so a compile would build the map from a partial corpus.
    from . import orchestrator as harvest_orch
    if harvest_orch.state.status == "running":
        return {
            "ok": False,
            "reason": "a harvest is in progress — wait for it to finish before compiling",
        }
    if not (paths.data_dir() / "harvest-manifest.db").exists():
        return {"ok": False, "reason": "no harvest manifest — run a harvest first"}
    # Saved defaults back every knob the caller didn't override.
    from src.api.routes_settings import _compile_settings_block
    defaults = _compile_settings_block()
    # UI/API compiles must not silently fall back to the deterministic local
    # hash embedder; clustering quality depends on real semantic embeddings.
    if ai_mode is None:
        ai_mode = defaults["ai_mode"]
    if ai_mode not in ("openai", "anthropic", "local", "claude"):
        return {
            "ok": False,
            "reason": "ai_mode must be 'openai', 'anthropic', 'local', or 'claude'",
        }
    # Sync env from .env BEFORE the key checks so keys added to .env count.
    try:
        from src.config import load_config
        load_config()
    except Exception:  # noqa: BLE001
        pass
    # Every non-local mode needs OPENAI_API_KEY: openai for everything, claude/
    # anthropic for embeddings only (Anthropic has no embeddings API).
    if ai_mode in ("openai", "anthropic", "claude") and not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "reason": (
                "OPENAI_API_KEY not set — required for embeddings"
                + (
                    f" ({ai_mode} mode uses Claude for text, OpenAI for embeddings)"
                    if ai_mode in ("claude", "anthropic")
                    else ""
                )
                + ". Add the key to .env and restart, or explicitly request ai_mode='local' for offline tests"
            ),
        }
    if ai_mode == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return {
            "ok": False,
            "reason": (
                "ANTHROPIC_API_KEY not set — required for the Anthropic API "
                "engine. Add the key to .env, or pick the Claude (subscription) "
                "or OpenAI engine instead."
            ),
        }

    # Resolve every remaining knob: per-run override OR saved default.
    if source is None:
        source = defaults["default_source"]
    embedding_model = embedding_model or defaults["embedding_model"]
    llm_concurrency = llm_concurrency or defaults["llm_concurrency"]
    extract_batch_size = extract_batch_size or defaults["extract_batch_size"]
    # Effort: per-run override OR saved default; "" means provider default.
    extract_effort = (extract_effort or defaults.get("extract_effort") or "") or None
    name_effort = (name_effort or defaults.get("name_effort") or "") or None
    # openai mode uses a single model string (llm_model). claude + anthropic
    # modes use two independent per-step aliases (extract + name); local mode
    # ignores both.
    llm_model: str | None = None
    extract_model: str | None = None
    name_model: str | None = None
    if ai_mode == "openai":
        llm_model = openai_model or defaults["openai_model"]
    elif ai_mode in ("claude", "anthropic"):
        extract_model = claude_extract_model or defaults["claude_extract_model"]
        name_model = claude_name_model or defaults["claude_name_model"]

    compile_bus.reset_buffer()
    state.status = "running"
    state.started_at = time.time()
    state.finished_at = None
    state.stage = "load"
    state.counts = {}
    state.summary = None
    state.error = None
    state.ai_mode = ai_mode
    state.run_id = None
    state._cancel = threading.Event()
    state._task = asyncio.create_task(
        _run_compile(
            source,
            ai_mode,
            fresh,
            llm_model=llm_model,
            claude_extract_model=extract_model,
            claude_name_model=name_model,
            embedding_model=embedding_model,
            llm_concurrency=llm_concurrency,
            extract_batch_size=extract_batch_size,
            extract_effort=extract_effort,
            name_effort=name_effort,
            claude_call_logging=defaults["claude_call_logging"],
            workspace=defaults["workspace"],
            owner_name=defaults["owner_name"],
            owner_role=defaults["owner_role"],
        )
    )
    return {"ok": True, "ai_mode": ai_mode}


async def cancel_compile() -> dict:
    if state.status != "running":
        return {"ok": False}
    state._cancel.set()
    return {"ok": True}


# ─── Internals ──────────────────────────────────────────────────────

async def _run_compile(
    source: str | None,
    ai_mode: str,
    fresh: bool = False,
    *,
    llm_model: str | None = None,
    claude_extract_model: str | None = None,
    claude_name_model: str | None = None,
    embedding_model: str | None = None,
    llm_concurrency: int | None = None,
    extract_batch_size: int | None = None,
    extract_effort: str | None = None,
    name_effort: str | None = None,
    claude_call_logging: bool = False,
    workspace: str = "Mnemify",
    owner_name: str = "Mnemify User",
    owner_role: str = "Knowledge Worker",
) -> None:
    from src.terrain.agents.claude_cli import set_call_logging
    from src.terrain.pipelines.compiler import (
        TerrainCompiler,
        _CompileCancelled,
        compile_error_kind,
        describe_compile_error,
    )
    from src.terrain.utils.models import Owner

    loop = asyncio.get_running_loop()
    rate = _Rate()

    def progress(ev: dict) -> None:
        # Called from the WORKER thread — hop to the loop thread to publish.
        loop.call_soon_threadsafe(_on_progress, ev, rate)

    cancel = state._cancel
    compiler: "TerrainCompiler | None" = None
    try:
        # Set once on the loop thread, before the build's worker-thread fan-out
        # reads it (read-only during parallel calls => no race).
        set_call_logging(claude_call_logging)
        compiler = TerrainCompiler(
            data_dir=paths.data_dir(),
            ai_mode=ai_mode,
            llm_model=llm_model,
            claude_extract_model=claude_extract_model,
            claude_name_model=claude_name_model,
            embedding_model=embedding_model or "text-embedding-3-large",
            llm_concurrency=llm_concurrency,
            extract_batch_size=extract_batch_size,
            extract_effort=extract_effort,
            name_effort=name_effort,
            workspace=workspace,
            owner=Owner(name=owner_name, role=owner_role),
        )
        result = await asyncio.to_thread(
            compiler.build, source, progress=progress, cancel=cancel, fresh=fresh
        )
        seconds = max(1, int(time.time() - (state.started_at or time.time())))
        state.status = "complete"
        state.stage = "complete"
        state.finished_at = time.time()
        state.run_id = result.run_id
        state.summary = {
            "run_id": result.run_id,
            "ai_mode": ai_mode,
            "seconds": seconds,
            "stats": result.stats.model_dump(),
        }
        compile_bus.publish({"type": "complete", **state.summary, "ts": time.time() * 1000})
    except _CompileCancelled:
        state.status = "failed"
        state.finished_at = time.time()
        state.error = "cancelled"
        compile_bus.publish({"type": "failed", "error": "cancelled", "ts": time.time() * 1000})
    except Exception as e:  # noqa: BLE001
        logger.exception("terrain compile failed")
        state.status = "failed"
        state.finished_at = time.time()
        kind = compile_error_kind(e)
        state.error = describe_compile_error(e)[:400]
        compile_bus.publish({
            "type": "failed", "error": state.error,
            "error_kind": kind, "resumable": kind == "usage_limit",
            "ts": time.time() * 1000,
        })
    finally:
        if compiler is not None:
            try:
                compiler.store.close()
            except Exception:  # noqa: BLE001
                pass


def _on_progress(ev: dict, rate: _Rate) -> None:
    """Runs on the event-loop thread — safe to mutate state + publish."""
    stage = ev.get("stage")
    if stage:
        state.stage = stage
        # Normalize bare stage events to a "progress" type so the SSE consumer
        # has one discriminator. ({"type":"log"|"error"} events keep their type.)
        ev.setdefault("type", "progress")
    # Only the bare per-stage "progress" frames carry the counts — {type:"log"}
    # / {type:"error"} frames also have a `stage` but no done/total, so don't
    # let them clobber the counters.
    if ev.get("type") == "progress":
        if stage == "load":
            state.counts["docs"] = ev.get("count", 0)
        elif stage == "chunk":
            state.counts["chunks"] = ev.get("total", 0)
            state.counts["enrich_phase"] = "extract"
            state.counts["enrich_total"] = ev.get("total", 0)
            state.counts["enrich_done"] = 0
        elif stage == "enrich":
            # Enrich now reports two sub-phases ("extract" then "embed"), each
            # with its own done/total. Keep enrich_done/enrich_total as the
            # CURRENT phase (drives the bar) and also expose per-phase counts so
            # the UI can label and sub-weight them.
            phase = ev.get("phase", "extract")
            state.counts["enrich_phase"] = phase
            state.counts["enrich_done"] = ev.get("done", 0)
            state.counts["enrich_total"] = ev.get("total", 0)
            state.counts[f"enrich_{phase}_done"] = ev.get("done", 0)
            state.counts[f"enrich_{phase}_total"] = ev.get("total", 0)
            # The initial done=0 frame is just a phase marker — don't let it
            # reset the rolling rate/ETA.
            ev["rate_per_sec"] = None if ev.get("done", 0) == 0 else rate.tick()
            # Mirror the rate into the snapshot so pollers of
            # GET /api/terrain/current (the TopBar ops pill) can compute an ETA
            # without holding the SSE stream open. `None` means "still warming
            # up" — keep the last good value rather than flapping the ETA.
            if ev["rate_per_sec"] is not None:
                state.counts["rate_per_sec"] = ev["rate_per_sec"]
        elif stage == "derive":
            state.counts["derive_done"] = ev.get("done", 0)
            state.counts["derive_total"] = ev.get("total", 0)
    compile_bus.publish(ev)
