"""Glue between the UI harvest lifecycle and the existing harvester.

Wraps the real ``HarvestOrchestrator`` + a publishing ``HarvestLogger``
so per-document events (harvested / skipped / failed) stream to any
subscribers on ``event_bus``.

Design choices:

* Sources run **in parallel** (asyncio.gather), not sequentially. With
  two sources connected, harvest wall-time is ≈ max(notion, confluence)
  rather than the sum. Per-source concurrency is honored too.

* A run can absorb a new source mid-flight. ``start_harvest`` checks
  whether the requested source is already running; if not, it spawns a
  per-source task and merges progress into the existing run. The UI
  posting "/api/harvest" with one new source while the previous run is
  still going just adds it to the same logical run.

* Per-source rate is computed over a rolling 3-second window so the UI
  ETA is meaningful — the upstream ``HarvestOrchestrator`` doesn't
  expose this directly, so we sample as events flow through the
  publishing logger.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from src.config_file import load_config_file, get_source_config
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.normalized_store import NormalizedStore
from src.harvester.raw_store import RawStore
from src.harvester.orchestrator import (
    HarvestOrchestrator,
    WriteBackConfig,
    _doc_already_harvested,
    _is_unreliable_modified_at,
)
from src.harvester.retention import purge_deleted

from ._rate import _BytesRate, _Rate
from .event_bus import bus


logger = logging.getLogger(__name__)
from src import paths  # data dir resolved at call time — see src/paths.py
DEFAULT_CONCURRENCY = 10  # was 5; bigger pool drains lists faster

# Per-source default concurrency when the user's YAML sets none. Obsidian reads
# from local disk — no API rate limit, so it's bounded by I/O and wants a much
# bigger pool. Cloud sources stay at the global default: each client already
# backs off on 429/Retry-After, but a higher default would mostly burn retries.
_SOURCE_DEFAULT_CONCURRENCY: dict[str, int] = {
    "obsidian": 32,
}


# Which yaml key holds the "what to harvest" list, per source. Mirrored from
# routes_connections._SCOPE_KEY (we duplicate the tiny map rather than import
# across the api package to avoid a circular dependency).
_SCOPE_KEY = {
    "notion": "scope",
    "confluence": "space_keys",
    "obsidian": "watch_folders",
    "jira": "project_keys",
}


# ─── Retention sweep ───────────────────────────────────────────────


def _retention_sweep(manifest: HarvestManifest, source: str) -> None:
    """Apply ``data_retention`` policy after a non-scoped harvest run.

    Read the policy + grace period from ``mnemify.yaml``. When the policy
    is ``"purge"``, sweep ``deleted_at_source`` docs whose status flipped
    more than ``grace_days`` ago and remove their raw bytes + manifest rows.
    When the policy is ``"keep"`` (default), do nothing — the UI / CLI's
    "Purge now" remains the only path to delete.
    """
    cfg = load_config_file()
    block = cfg.get("data_retention") or {}
    policy = block.get("on_source_delete") or "keep"
    if policy != "purge":
        return
    grace = block.get("purge_grace_days")
    if not isinstance(grace, int) or grace < 0:
        grace = 7

    raw_store = RawStore(paths.data_dir() / "raw", converter_version=cfg.get("converter_version", "0.1.0"))
    normalized_store = NormalizedStore(paths.data_dir() / "normalized")
    result = purge_deleted(
        manifest,
        raw_store,
        normalized_store,
        source=source,
        grace_days=grace,
    )
    if result.purged or result.eligible:
        logger.info(
            "retention: source=%s purged=%d eligible=%d skipped=%d (grace=%dd)",
            source, result.purged, result.eligible, result.skipped, grace,
        )


# ─── Layer 3b: per-space scope override ────────────────────────────


def _apply_scope_to_source_cfg(source: str, source_cfg: dict, space_id: str) -> dict:
    """Return a per-source config narrowed to a single "space"."""
    return _apply_scope_ids_to_source_cfg(source, source_cfg, [space_id])


def _active_scope_ids_for(source: str, source_cfg: dict) -> list[str] | None:
    """Return the scope ids currently in YAML for ``source``.

    Used by the scope-aware deletion pass (Option B) to decide whether a doc
    missing from the latest listing should be marked deleted (its origin is
    still configured) or out_of_scope (its origin was removed from config).

    The set always includes the empty string ``""`` — that's the implicit
    "no scope restriction" origin (e.g. an Obsidian harvest with no
    ``watch_folders``, or a Notion harvest with no ``scope``). Docs tagged
    with the empty origin therefore stay reachable as long as the source is
    enabled.
    """
    if source == "notion":
        # Notion IDs round-trip through the API in inconsistent dash forms;
        # the plugin stores origin_scope_id in the normalized (dash-stripped,
        # lowercased) form, so normalize the YAML side to match.
        from src.harvester.notion.plugin import _normalize_notion_id
        ids = [_normalize_notion_id(s) for s in (source_cfg.get("scope") or []) if s]
    elif source == "confluence":
        # Scope is split across two YAML keys: whole-space keys and
        # page-subtree ids (each stamps origin_scope_id with its own value).
        ids = list(source_cfg.get("space_keys") or []) + list(
            source_cfg.get("page_ids") or []
        )
    elif source == "obsidian":
        ids = source_cfg.get("watch_folders") or []
    elif source == "jira":
        ids = source_cfg.get("project_keys") or []
    else:
        return None
    # Always include "" so the implicit "full source" origin is treated as
    # in-scope. Cheap and avoids edge cases where an Obsidian/Notion config
    # has zero scope ids (= harvest everything).
    out = [str(s) for s in ids if s]
    out.append("")
    return out


def _apply_scope_ids_to_source_cfg(
    source: str, source_cfg: dict, ids: list[str]
) -> dict:
    """Return a per-source config narrowed to a list of "space" / scope ids.

    Used by both the legacy single-id ``scope`` body and the newer
    ``scope_override`` payload (Manage Scope auto-harvest of just-added items).
    Shallow copy — does not mutate the caller's cfg dict.

    For each source we override the same key the *saved* scope lives under, so
    the plugin treats the override as a focused harvest of just those items
    (and their descendants, where the plugin supports subtree semantics):

      • confluence  → ``space_keys``
      • notion      → ``scope`` (a list of page/database IDs; the plugin's
                     ``_filter_docs_by_scope`` walks descendants from there).
                     A previous version of this function wrote to
                     ``filter.include_databases`` instead, which combined with
                     the YAML's wider ``scope`` to intersect to ~0–1 items.
      • obsidian    → ``watch_folders``
      • jira        → ``project_keys``
    """
    cfg = dict(source_cfg)
    if source == "confluence":
        # Mixed scope ids: alphanumeric entries are space keys (whole-space
        # harvest), all-digit entries are page ids (page + descendants).
        cfg["space_keys"] = [s for s in ids if not str(s).isdigit()]
        cfg["page_ids"] = [str(s) for s in ids if str(s).isdigit()]
    elif source == "notion":
        cfg["scope"] = list(ids)
    elif source == "obsidian":
        cfg["watch_folders"] = list(ids)
    elif source == "jira":
        cfg["project_keys"] = list(ids)
    return cfg


# ─── Layer 2: pre-flight already-harvested counter ─────────────────


def _count_already_harvested(manifest: HarvestManifest, doc_refs: list) -> int:
    """Return the count of listed docs that the Layer 1 short-circuit will skip.

    Mirrors the predicates in :mod:`src.harvester.orchestrator` exactly so
    the UI's "X already harvested" estimate equals the actual skipped
    count after fetches start.
    """
    count = 0
    for doc_ref in doc_refs:
        if _is_unreliable_modified_at(doc_ref):
            continue
        existing = manifest.lookup(doc_ref.source_type, doc_ref.source_id)
        if existing and _doc_already_harvested(doc_ref, existing):
            count += 1
    return count


# ─── Publishing logger ──────────────────────────────────────────────

class _Publishing(HarvestLogger):
    """A HarvestLogger that mirrors each event onto the SSE bus and updates rate."""

    def __init__(self, underlying: HarvestLogger, *, source_type: str, run_state: "RunState"):
        self._u = underlying
        self._source = source_type
        self._state = run_state
        self._rate = _Rate()
        # Bytes-rate runs in parallel for the bytes-weighted ETA overlay.
        # Notion is the only frontend consumer today, but tracking it
        # everywhere is free and lets us extend the overlay later.
        self._bytes_rate = _BytesRate()
        self._log_path = getattr(underlying, "_log_path", None)

    def _bump_rate(self, n_bytes: int) -> tuple[float | None, float | None]:
        """Tick both rates from a single doc-complete event.

        Returns ``(docs_per_sec, bytes_per_sec)`` — either may be ``None``
        while warming up. Caller forwards both onto the progress frame.
        """
        rate = self._rate.tick()
        bytes_rate = self._bytes_rate.tick(n_bytes)
        src = self._state.sources.get(self._source)
        if src is not None:
            src["rate"] = rate
            src["bytes_rate"] = bytes_rate
        return rate, bytes_rate

    def log_run_started(self, run_id: str, **kwargs) -> None:
        self._u.log_run_started(run_id, **kwargs)

    def log_run_completed(self, run_id: str, *, stats: dict) -> None:
        self._u.log_run_completed(run_id, stats=stats)

    def log_harvested(self, run_id: str, *, source_type: str, source_id: str,
                      title: str, version: int, action: str, bytes: int | None = None) -> None:
        self._u.log_harvested(
            run_id, source_type=source_type, source_id=source_id,
            title=title, version=version, action=action, bytes=bytes,
        )
        # Update done count + bytes accumulator so progress events accurately
        # reflect throughput. `bytes` is None for sources that don't report
        # raw size (rare); treat as zero.
        src = self._state.sources.get(source_type)
        doc_bytes = int(bytes or 0)
        if src is not None:
            src["done"] = src.get("done", 0) + 1
            src["bytes"] = src.get("bytes", 0) + doc_bytes
        rate, bytes_rate = self._bump_rate(doc_bytes)
        # avg_bytes_per_doc lets the frontend project remaining bytes from
        # the remaining doc count, then divide by bytes_per_sec — steadier
        # than docs/sec when page sizes vary by orders of magnitude.
        avg_bytes = (
            src.get("bytes", 0) / src["done"]
            if src is not None and src.get("done", 0) > 0
            else None
        )
        bus.publish({
            "type": "log",
            "level": "info",
            "source": source_type,
            "doc_id": source_id,
            "title": title,
            "msg": f"harvested ({action})",
            "ts": time.time() * 1000,
        })
        # Also emit a fresh progress event so the UI bar moves immediately.
        # Carry skipped/failed too so the frontend's bar (which is computed as
        # (done + skipped + failed) / total) stays in sync if cache-hit or
        # failure frames raced ahead.
        if src is not None:
            bus.publish({
                "type": "progress",
                "source": source_type,
                "done": src.get("done", 0),
                "skipped": src.get("skipped", 0),
                "failed": src.get("failed", 0),
                "total": src.get("total", 0),
                "rate_per_sec": rate,
                "bytes_per_sec": bytes_rate,
                "avg_bytes_per_doc": avg_bytes,
            })

    def log_skipped(self, run_id: str, *, source_type: str, source_id: str,
                    title: str, reason: str) -> None:
        self._u.log_skipped(
            run_id, source_type=source_type, source_id=source_id,
            title=title, reason=reason,
        )
        src = self._state.sources.get(source_type)
        if src is not None:
            src["skipped"] = src.get("skipped", 0) + 1
        bus.publish({
            "type": "log",
            "level": "info",
            "source": source_type,
            "doc_id": source_id,
            "title": title,
            "msg": f"skipped ({reason})",
            "ts": time.time() * 1000,
        })
        # Emit a progress event so the bar moves on cache hits too — the bar
        # is (done + skipped + failed) / total on the frontend. We deliberately
        # don't tick the rate here: skip detection is much cheaper than a full
        # fetch, so folding skips into docs/sec would bias the ETA. Carry the
        # last-known rate as-is.
        if src is not None:
            bus.publish({
                "type": "progress",
                "source": source_type,
                "done": src.get("done", 0),
                "skipped": src.get("skipped", 0),
                "failed": src.get("failed", 0),
                "total": src.get("total", 0),
                "rate_per_sec": src.get("rate"),
                "bytes_per_sec": src.get("bytes_rate"),
            })

    def log_failed(self, run_id: str, *, source_type: str, source_id: str,
                   title: str, error: str) -> None:
        self._u.log_failed(
            run_id, source_type=source_type, source_id=source_id,
            title=title, error=error,
        )
        src = self._state.sources.get(source_type)
        if src is not None:
            src["failed"] = src.get("failed", 0) + 1
        bus.publish({
            "type": "error",
            "level": "error",
            "source": source_type,
            "doc_id": source_id,
            "title": title,
            "msg": error[:140],
            "ts": time.time() * 1000,
        })
        # Move the bar forward — failed docs are "processed" too.
        if src is not None:
            bus.publish({
                "type": "progress",
                "source": source_type,
                "done": src.get("done", 0),
                "skipped": src.get("skipped", 0),
                "failed": src.get("failed", 0),
                "total": src.get("total", 0),
                "rate_per_sec": src.get("rate"),
                "bytes_per_sec": src.get("bytes_rate"),
            })

    def log_deleted(self, *args, **kwargs) -> None:
        self._u.log_deleted(*args, **kwargs)

    def log_attachment(self, *args, **kwargs) -> None:
        self._u.log_attachment(*args, **kwargs)


# ─── Plugin factory (avoid cycle with cli) ───────────────────────────

def _make_plugin(source_type: str, source_cfg: dict):
    from src.harvester.registry import create_plugin
    from src.harvester import notion as _notion  # noqa: F401
    from src.harvester import confluence as _conf  # noqa: F401
    from src.harvester import jira as _jira  # noqa: F401
    from src.harvester import obsidian as _obs  # noqa: F401

    if source_type == "notion" and "token" not in source_cfg:
        token_env = source_cfg.get("token_env", "NOTION_TOKEN")
        source_cfg = dict(source_cfg)
        source_cfg["token"] = os.getenv(token_env, "")
    return create_plugin(source_type, source_cfg)


# ─── Run state ──────────────────────────────────────────────────────

class RunState:
    status: str = "idle"
    started_at: float | None = None
    finished_at: float | None = None
    sources: dict[str, dict[str, Any]] = {}
    summary: dict[str, Any] | None = None
    _tasks: dict[str, asyncio.Task] = {}
    _cancel_event: asyncio.Event = asyncio.Event()


state = RunState()


# ─── Public entrypoints ─────────────────────────────────────────────

def is_running() -> bool:
    """Whether a harvest is in flight (any source still fetching).

    Queried by the idle watchdog before it shuts the process down: killing a
    harvest mid-run loses the in-progress fetches and leaves the run row open.
    """
    return state.status == "running"


async def start_harvest(
    sources: list[str] | None = None,
    *,
    force_full: bool = False,
    scope: dict | None = None,
    scope_override: dict[str, list[str]] | None = None,
) -> dict:
    """Kick off a harvest. If a run is in progress, *new* sources are
    added in parallel; sources already running are no-ops.

    ``force_full=True`` bypasses Layer 1's pre-fetch resume short-circuit
    so every doc is re-fetched. ``scope`` is an optional per-source
    filter override of the form ``{"source": "...", "space_id": "..."}``
    interpreted per-plugin (Confluence: space_keys; Notion:
    include_databases; Obsidian: watch_folders; Jira: project keys).
    """
    cfg = load_config_file()
    enabled = [s for s, v in (cfg.get("sources") or {}).items() if v.get("enabled")]
    requested = [s for s in (sources or enabled) if s in enabled]
    if not requested:
        return {"ok": False, "reason": "no enabled sources to harvest"}

    if state.status == "running":
        # Add only sources that aren't already running.
        added = [s for s in requested if s not in state.sources]
        if not added:
            return {"ok": True, "added": 0, "running": list(state.sources.keys())}
        for src in added:
            _spawn_source_task(
                src,
                cfg,
                force_full=force_full,
                scope=scope,
                scope_ids=(scope_override or {}).get(src),
            )
        bus.publish({
            "type": "log",
            "level": "info",
            "source": added[0],
            "doc_id": "",
            "title": ", ".join(added),
            "msg": "added to running map",
            "ts": time.time() * 1000,
        })
        return {"ok": True, "added": len(added), "running": list(state.sources.keys())}

    # Fresh run — drop any replay frames from the previous run so a UI tab
    # that connects now doesn't see stale log lines.
    bus.reset_buffer()
    state.status = "running"
    state.started_at = time.time()
    state.finished_at = None
    state.summary = None
    state.sources = {}
    state._tasks = {}
    state._cancel_event = asyncio.Event()

    for src in requested:
        _spawn_source_task(
            src,
            cfg,
            force_full=force_full,
            scope=scope,
            scope_ids=(scope_override or {}).get(src),
        )

    # Watcher coroutine completes the run when all source tasks resolve.
    asyncio.create_task(_watch_run())

    return {"ok": True, "added": len(requested), "running": requested}


async def cancel_harvest() -> dict:
    if state.status != "running":
        return {"ok": False}
    state._cancel_event.set()
    for t in list(state._tasks.values()):
        t.cancel()
    return {"ok": True}


def reset_state() -> None:
    """Return the run state to idle (used by the harvest-data reset endpoint).

    Caller must ensure no run is in progress; does not touch on-disk data.
    """
    state.status = "idle"
    state.started_at = None
    state.finished_at = None
    state.summary = None
    state.sources = {}
    state._tasks = {}
    state._cancel_event = asyncio.Event()


# ─── Internals ──────────────────────────────────────────────────────

def _spawn_source_task(
    source: str,
    cfg: dict,
    *,
    force_full: bool = False,
    scope: dict | None = None,
    scope_ids: list[str] | None = None,
) -> None:
    state.sources[source] = {
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0,
        "already_harvested": 0,
        "rate": 0.0,
        "bytes": 0,
        "bytes_rate": 0.0,
        # Content-level extraction drops (kind → count), filled in at
        # completion from the orchestrator's HarvestResult.
        "warnings": {},
    }
    bus.publish({
        "type": "progress",
        "source": source,
        "done": 0,
        "total": 0,
        "already_harvested": 0,
        "rate_per_sec": 0.0,
        "bytes_per_sec": 0.0,
        "avg_bytes_per_doc": None,
    })
    state._tasks[source] = asyncio.create_task(
        _run_one(source, cfg, force_full=force_full, scope=scope, scope_ids=scope_ids)
    )


async def _watch_run() -> None:
    # Wait until every per-source task finishes (or the run is cancelled).
    try:
        # We don't await a fixed snapshot of tasks because new ones can
        # be added mid-run. Loop until none remain.
        while state._tasks:
            done, _ = await asyncio.wait(
                list(state._tasks.values()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                # Find which source this task is.
                for src, task in list(state._tasks.items()):
                    if task is t:
                        state._tasks.pop(src, None)
                        break
        _finalize()
    except asyncio.CancelledError:
        _finalize()


def _emit_source_complete(source: str, status: str) -> None:
    """Mark a source's per-source progress terminal and publish the markers.

    Emits a final ``progress`` event (so the bar lands on done/total with
    rate 0) plus a ``source_complete`` event carrying the terminal status,
    and records ``status`` on ``state.sources[source]`` so a late-joining
    UI's ``snapshot`` frame reflects it. ``status`` is one of
    ``"complete" | "failed" | "cancelled"``.
    """
    src = state.sources.setdefault(source, {})
    src["status"] = status
    src["rate"] = 0.0
    src["bytes_rate"] = 0.0
    done = src.get("done", 0)
    avg_bytes = src.get("bytes", 0) / done if done > 0 else None
    bus.publish({
        "type": "progress",
        "source": source,
        "done": done,
        "total": src.get("total", 0),
        "already_harvested": src.get("already_harvested", 0),
        "rate_per_sec": 0.0,
        "bytes_per_sec": 0.0,
        "avg_bytes_per_doc": avg_bytes,
    })
    bus.publish({
        "type": "source_complete",
        "source": source,
        "status": status,
        "done": src.get("done", 0),
        "failed": src.get("failed", 0),
        "skipped": src.get("skipped", 0),
        "total": src.get("total", 0),
        "ts": time.time() * 1000,
    })


def _finalize() -> None:
    if state.status not in ("running",):
        return
    now = time.time()
    cancelled = state._cancel_event.is_set()
    harvested = sum(s.get("done", 0) for s in state.sources.values())
    failed = sum(s.get("failed", 0) for s in state.sources.values())
    skipped = sum(s.get("skipped", 0) for s in state.sources.values())
    state.status = "cancelled" if cancelled else "complete"
    state.finished_at = now
    state.summary = {
        "harvested": harvested,
        "failed": failed,
        "skipped": skipped,
        "seconds": max(1, int(now - (state.started_at or now))),
    }
    bus.publish({"type": "complete", "summary": state.summary, "ts": now * 1000})
    if not cancelled and harvested > 0:
        _maybe_auto_compile()


def _maybe_auto_compile() -> None:
    """Kick a compile after a successful harvest when the user opted in.

    Scheduled as a task, never awaited — ``_finalize`` runs on the event loop
    inside ``_watch_run`` and must not block on a compile. ``start_compile``
    self-guards against concurrent harvest/compile; a refusal is surfaced on
    the harvest bus so the UI can fall back to the manual "Compile now" nudge.
    """
    try:
        from src.api.routes_settings import _compile_settings_block
        if not _compile_settings_block().get("auto_compile_after_harvest"):
            return
    except Exception:  # noqa: BLE001
        logger.exception("auto-compile: could not read compile settings; skipping")
        return

    from src.api import compile_orchestrator as compile_orch

    async def _kick() -> None:
        try:
            result = await compile_orch.start_compile()
        except Exception as e:  # noqa: BLE001
            logger.exception("auto-compile: start_compile failed")
            result = {"ok": False, "reason": str(e)}
        msg = (
            "auto-compile started"
            if result.get("ok")
            else f"auto-compile skipped: {result.get('reason', 'unknown')}"
        )
        bus.publish({"type": "info", "msg": msg, "ts": time.time() * 1000})

    asyncio.create_task(_kick())


async def _run_one(
    source: str,
    cfg: dict,
    *,
    force_full: bool = False,
    scope: dict | None = None,
    scope_ids: list[str] | None = None,
) -> None:
    manifest = HarvestManifest(paths.data_dir() / "harvest-manifest.db")
    underlying = HarvestLogger(paths.data_dir() / "harvest-log.jsonl")

    try:
        source_cfg = get_source_config(cfg, source)
    except Exception as e:  # noqa: BLE001
        bus.publish({"type": "error", "source": source, "msg": f"config: {e}", "ts": time.time() * 1000})
        _emit_source_complete(source, "failed")
        return

    # Apply scope override (Layer 3b). The "space" concept is per-source;
    # we map onto the per-plugin config dimensions the harvester already
    # understands. Only applies when scope.source == this source.
    if scope and scope.get("source") == source and scope.get("space_id"):
        source_cfg = _apply_scope_to_source_cfg(source, source_cfg, scope["space_id"])
    # Per-source list of scope ids — used by Manage Scope to harvest only
    # the items the user just added, without touching the persisted scope.
    if scope_ids:
        source_cfg = _apply_scope_ids_to_source_cfg(source, source_cfg, scope_ids)

    try:
        plugin, closeable = _make_plugin(source, source_cfg)
    except Exception as e:  # noqa: BLE001
        bus.publish({"type": "error", "source": source, "msg": f"plugin init: {e}", "ts": time.time() * 1000})
        _emit_source_complete(source, "failed")
        return

    publishing_logger = _Publishing(underlying, source_type=source, run_state=state)

    try:
        # Quick listing so the UI knows the denominator before any docs land.
        # ``since=None`` matches the orchestrator: per-doc Layer 1 short-circuit
        # decides what's new vs. unchanged. Passing a real ``since`` here would
        # under-count when scope expanded (the just-added items have old
        # modified_at and would be filtered out), so the "X to fetch" estimate
        # would lie to the user before the run even started.
        try:
            listed = await plugin.list_documents(since=None)
            total = len(listed)
        except Exception as e:  # noqa: BLE001
            total = 0
            listed = []
            bus.publish({"type": "error", "source": source, "msg": f"list: {e}", "ts": time.time() * 1000})

        # Count how many of the listed docs the orchestrator's pre-fetch
        # short-circuit will skip — matches the Layer 1 predicate exactly so
        # the UI can show "X already harvested · Y to fetch" before fetches
        # start. Cheap: one manifest lookup per listed doc, no API calls.
        already_harvested = _count_already_harvested(manifest, listed)

        state.sources[source]["total"] = total
        state.sources[source]["already_harvested"] = already_harvested
        bus.publish({
            "type": "progress",
            "source": source,
            "done": 0,
            "total": total,
            "already_harvested": already_harvested,
            "rate_per_sec": 0.0,
        })

        raw_store = RawStore(
            paths.data_dir() / "raw",
            converter_version=cfg.get("converter_version", "0.1.0"),
        )
        normalized_store = NormalizedStore(paths.data_dir() / "normalized")

        # Read the FULL YAML scope (not the narrowed source_cfg one) so the
        # reconcile pass can tell "the user removed this scope item" apart
        # from "the source truly deleted this doc". For scoped runs we don't
        # need this — they skip reconcile entirely — but we still compute it
        # here for symmetry / future use.
        full_source_cfg = (cfg.get("sources") or {}).get(source) or {}
        active_scope_ids = _active_scope_ids_for(source, full_source_cfg)

        orchestrator = HarvestOrchestrator(
            plugin=plugin,
            manifest=manifest,
            harvest_logger=publishing_logger,
            max_concurrent=source_cfg.get(
                "concurrency",
                _SOURCE_DEFAULT_CONCURRENCY.get(source, DEFAULT_CONCURRENCY),
            ),
            raw_store=raw_store,
            normalized_store=normalized_store,
            write_back=WriteBackConfig(),
            dry_run=False,
            force_full=force_full,
            # When the API caller narrowed the run to specific scope ids
            # (e.g. Manage Scope auto-harvest of just-added items), don't
            # let the deletion-detection pass nuke previously-harvested
            # docs that simply weren't in this narrow listing.
            skip_mark_deleted=bool(scope_ids) or bool(scope),
            active_scope_ids=active_scope_ids,
        )

        result = await orchestrator.run(source_type=source, mode="manual")
        state.sources[source]["done"] = result.harvested
        state.sources[source]["failed"] = result.failed
        state.sources[source]["skipped"] = result.skipped
        state.sources[source]["warnings"] = result.warnings
        state.sources[source]["rate"] = 0.0

        # Snapshot the YAML scope when the run was both unscoped and not
        # cancelled — that's the only case where "this run covered every
        # configured scope id" holds, which the Connections card's
        # pending-scope diff depends on. Scoped runs (legacy single-space
        # ``scope`` body) intentionally cover only a subset, so they leave
        # the snapshot alone; the previously-recorded snapshot stays
        # authoritative until a full run replaces it.
        if not state._cancel_event.is_set() and not orchestrator.skip_mark_deleted:
            try:
                scope_key = _SCOPE_KEY.get(source, "scope")
                yaml_scope = list(full_source_cfg.get(scope_key, []) or [])
                if source == "confluence":
                    # Page-subtree scope lives in a second key; the
                    # pending-scope diff compares against the full set.
                    yaml_scope += [
                        str(p) for p in (full_source_cfg.get("page_ids") or [])
                    ]
                manifest.set_last_scope_snapshot(source, yaml_scope)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "couldn't snapshot scope for %s", source, exc_info=True
                )

        # Retention sweep: when the user has set on_source_delete=purge in
        # Settings, expire raw bytes + manifest rows for docs whose
        # ``status_changed_at`` is older than ``purge_grace_days``. Fires
        # after every harvest run — scoped Manage Scope runs can't *flag*
        # new deletions (they skip reconcile), but they should still clear
        # out previously-flagged rows whose grace has expired, since users
        # may rely on Manage Scope rather than scheduled harvests.
        try:
            _retention_sweep(manifest, source)
        except Exception:  # noqa: BLE001
            logger.warning("retention sweep failed for %s", source, exc_info=True)

        _emit_source_complete(
            source, "cancelled" if state._cancel_event.is_set() else "complete"
        )
    except asyncio.CancelledError:
        _emit_source_complete(source, "cancelled")
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception(f"harvest {source} failed")
        bus.publish({"type": "error", "source": source, "msg": str(e)[:200], "ts": time.time() * 1000})
        _emit_source_complete(source, "failed")
    finally:
        try:
            if closeable is not None and hasattr(closeable, "aclose"):
                await closeable.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await plugin.aclose()
        except Exception:  # noqa: BLE001
            pass
