"""/api/schedules — CRUD for cron-driven harvest schedules.

Schedules live in ``mnemify.yaml`` under a top-level ``schedules:`` block:

    schedules:
      notion:
        cron: "0 6 * * *"   # every morning at 6am UTC
        enabled: true

After every write, ``scheduler.reload_from_yaml()`` re-registers jobs so
changes take effect without a server restart.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import scheduler as sched
from .yaml_writer import read_config, upsert_schedule


router = APIRouter()


class Schedule(BaseModel):
    cron: str = Field(min_length=1)
    enabled: bool = True


def _validate_cron(expr: str) -> None:
    """Best-effort cron validation by attempting to parse via apscheduler."""
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(expr, timezone="UTC")
    except ValueError as e:
        raise HTTPException(400, f"invalid cron expression: {e}") from e


@router.get("/schedules")
async def list_all() -> dict:
    """All schedules, with the next computed run time for each enabled one."""
    cfg = read_config()
    schedules = dict(cfg.get("schedules") or {})
    out: dict[str, dict] = {}
    for source, body in schedules.items():
        if not isinstance(body, dict):
            continue
        out[source] = {
            "cron": body.get("cron"),
            "enabled": bool(body.get("enabled")),
            "next_run": sched.next_run_iso(source),
        }
    return {"schedules": out}


@router.put("/schedules/{source}")
async def put_one(source: str, body: Schedule) -> dict:
    _validate_cron(body.cron)
    upsert_schedule(source, {"cron": body.cron, "enabled": body.enabled})
    sched.reload_from_yaml()
    return {
        "source": source,
        "cron": body.cron,
        "enabled": body.enabled,
        "next_run": sched.next_run_iso(source),
    }


@router.delete("/schedules/{source}")
async def delete_one(source: str) -> dict:
    upsert_schedule(source, None)
    sched.reload_from_yaml()
    return {"ok": True, "source": source}
