"""In-process cron scheduler for harvest runs.

Reads the ``schedules:`` block in ``mnemify.yaml`` and registers one
``CronTrigger`` per enabled schedule. When a schedule fires, it calls
``orchestrator.start_harvest`` for the configured source.

Lifecycle is managed by the FastAPI lifespan in ``api/__init__.py``:
``scheduler.start()`` on app startup, ``scheduler.stop()`` on shutdown.

Single-worker only — multiple uvicorn workers would double-fire.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import orchestrator as orch
from .yaml_writer import read_config


logger = logging.getLogger(__name__)

# Stable job-id prefix so we can refresh schedules without leaking orphans.
_JOB_PREFIX = "harvest-schedule:"

_scheduler: AsyncIOScheduler | None = None


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
