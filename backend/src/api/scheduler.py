"""In-process cron scheduler for harvest runs.

Reads the ``schedules:`` block in ``mnemify.yaml`` and registers one
``CronTrigger`` per enabled schedule. When a schedule fires, it calls
``orchestrator.start_harvest`` for the configured source.

Lifecycle is managed by the FastAPI lifespan in ``api/__init__.py``:
``scheduler.start()`` on app startup, ``scheduler.stop()`` on shutdown.

Single-worker only — multiple uvicorn workers would double-fire.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.harvester.manifest import HarvestManifest

from . import orchestrator as orch
from .yaml_writer import read_config


logger = logging.getLogger(__name__)

# Stable job-id prefix so we can refresh schedules without leaking orphans.
_JOB_PREFIX = "harvest-schedule:"

_scheduler: AsyncIOScheduler | None = None

_DATA_DIR = Path(".mnemify")

# Catch-up window. The app runs locally, so a 6am cron silently misses when
# the laptop is closed at 6am. On startup we look for a scheduled instant that
# fell between the source's last completed harvest and now, and run it. If a
# source has never completed a run, only look back this far so a brand-new
# schedule doesn't immediately fire on every restart.
CATCHUP_LOOKBACK = timedelta(days=7)
# Give uvicorn a moment to finish booting before kicking off a harvest.
_CATCHUP_START_DELAY_S = 5.0


def _job_id(source: str) -> str:
    return f"{_JOB_PREFIX}{source}"


async def _fire(source: str) -> None:
    """Trigger a harvest for one source. Swallows errors so a single failure
    doesn't kill the scheduler."""
    try:
        logger.info("scheduler: firing scheduled harvest for %s", source)
        if orch.state.status == "running":
            logger.warning("scheduler: harvest already running, skipping %s", source)
            return
        await orch.start_harvest([source])
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: scheduled harvest for %s failed", source)


def missed_fire_time(
    cron: str,
    last_completed: datetime | None,
    now: datetime | None = None,
    lookback: timedelta = CATCHUP_LOOKBACK,
) -> datetime | None:
    """Return the scheduled instant that was missed while the app was closed,
    or None if the schedule is up to date.

    A run counts as missed when the cron would have fired at least once after
    ``last_completed`` (or within ``lookback`` when there is no prior run) and
    that instant is already in the past. Returns the *earliest* such instant.
    Invalid crons return None (the caller already logs those on registration).
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    floor = now - lookback
    if last_completed is not None:
        if last_completed.tzinfo is None:
            last_completed = last_completed.replace(tzinfo=timezone.utc)
        floor = max(floor, last_completed)
    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
    except ValueError:
        return None
    fire = trigger.get_next_fire_time(None, floor)
    if fire is None or fire > now:
        return None
    return fire


def _last_completed(source: str) -> datetime | None:
    db = _DATA_DIR / "harvest-manifest.db"
    if not db.exists():
        return None
    try:
        return HarvestManifest(db).get_last_harvest_time(source)
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: couldn't read last harvest time for %s", source)
        return None


async def catch_up_missed_runs(now: datetime | None = None) -> list[str]:
    """Run any schedule that should have fired while the app was closed.

    Returns the sources that were kicked off (for logging/tests). All missed
    sources are passed to one ``start_harvest`` call so they run in parallel
    like a normal multi-source harvest.
    """
    now = now or datetime.now(timezone.utc)
    missed: list[str] = []
    for source, body in list_schedules().items():
        if not isinstance(body, dict) or not body.get("enabled"):
            continue
        cron = body.get("cron")
        if not cron or not isinstance(cron, str):
            continue
        fire = missed_fire_time(cron, _last_completed(source), now)
        if fire is None:
            continue
        logger.info(
            "scheduler: %s missed its %s run at %s (app was closed) — catching up",
            source,
            cron,
            fire.isoformat(),
        )
        missed.append(source)
    if not missed:
        return []
    if orch.state.status == "running":
        logger.info("scheduler: harvest already running, skipping catch-up for %s", missed)
        return []
    try:
        await orch.start_harvest(missed)
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: catch-up harvest failed for %s", missed)
        return []
    return missed


async def _delayed_catch_up() -> None:
    await asyncio.sleep(_CATCHUP_START_DELAY_S)
    try:
        await catch_up_missed_runs()
    except Exception:  # noqa: BLE001
        logger.exception("scheduler: catch-up check failed")


def _instance() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def list_schedules() -> dict[str, dict[str, Any]]:
    """Read schedules from mnemify.yaml. Returns ``{ source: {cron, enabled} }``."""
    cfg = read_config()
    return dict(cfg.get("schedules") or {})


def reload_from_yaml() -> None:
    """Clear all existing schedule jobs and re-register from yaml. Called on
    startup and after every schedule update."""
    sched = _instance()
    for job in list(sched.get_jobs()):
        if job.id.startswith(_JOB_PREFIX):
            sched.remove_job(job.id)

    schedules = list_schedules()
    for source, body in schedules.items():
        if not isinstance(body, dict):
            continue
        if not body.get("enabled"):
            continue
        cron = body.get("cron")
        if not cron or not isinstance(cron, str):
            logger.warning("scheduler: %s has no cron expression, skipping", source)
            continue
        try:
            trigger = CronTrigger.from_crontab(cron, timezone="UTC")
        except ValueError:
            logger.warning("scheduler: %s has invalid cron %r, skipping", source, cron)
            continue
        sched.add_job(
            _fire,
            trigger=trigger,
            id=_job_id(source),
            args=[source],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("scheduler: registered %s @ %r (UTC)", source, cron)


def start() -> None:
    sched = _instance()
    reload_from_yaml()
    if not sched.running:
        sched.start()
        logger.info("scheduler: started")
        # Fire anything that should have run while the app was closed. Runs
        # as a background task so startup isn't blocked on a harvest.
        try:
            asyncio.get_running_loop().create_task(_delayed_catch_up())
        except RuntimeError:
            logger.warning("scheduler: no running loop; skipping catch-up check")


def stop() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler: stopped")
    _scheduler = None


def next_run_iso(source: str) -> str | None:
    """ISO timestamp of the next scheduled run for ``source``, if any."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_job_id(source))
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()
