"""Catch-up for schedules missed while the app was closed (api/scheduler.py)."""

from datetime import datetime, timedelta, timezone

from src.api import scheduler

UTC = timezone.utc
DAILY_6 = "0 6 * * *"


def test_missed_when_last_run_before_fire_and_now_after():
    last = datetime(2026, 9, 13, 6, 5, tzinfo=UTC)  # yesterday's run
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)  # opened laptop at 10am
    assert scheduler.missed_fire_time(DAILY_6, last, now) == datetime(2026, 9, 14, 6, tzinfo=UTC)


def test_not_missed_when_last_run_is_after_fire():
    last = datetime(2026, 9, 14, 6, 3, tzinfo=UTC)  # today's run already happened
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    assert scheduler.missed_fire_time(DAILY_6, last, now) is None


def test_not_missed_when_fire_is_still_in_future():
    last = datetime(2026, 9, 13, 6, 5, tzinfo=UTC)
    now = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)  # before 6am
    assert scheduler.missed_fire_time(DAILY_6, last, now) is None


def test_multiple_missed_days_returns_earliest_single_fire():
    last = datetime(2026, 9, 10, 6, 5, tzinfo=UTC)
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    # One catch-up harvest is enough; we don't replay every missed day.
    assert scheduler.missed_fire_time(DAILY_6, last, now) == datetime(2026, 9, 11, 6, tzinfo=UTC)


def test_never_harvested_uses_lookback_window():
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    assert scheduler.missed_fire_time(DAILY_6, None, now, lookback=timedelta(days=1)) == datetime(
        2026, 9, 14, 6, tzinfo=UTC
    )
    # A schedule created moments ago has nothing to catch up on.
    assert scheduler.missed_fire_time(DAILY_6, None, now, lookback=timedelta(hours=1)) is None


def test_naive_datetimes_are_treated_as_utc():
    last = datetime(2026, 9, 13, 6, 5)
    now = datetime(2026, 9, 14, 10, 0)
    assert scheduler.missed_fire_time(DAILY_6, last, now) == datetime(2026, 9, 14, 6, tzinfo=UTC)


def test_invalid_cron_returns_none():
    assert scheduler.missed_fire_time("not a cron", None, datetime.now(UTC)) is None


async def test_catch_up_starts_one_harvest_for_all_missed_sources(monkeypatch):
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    monkeypatch.setattr(
        scheduler,
        "list_schedules",
        lambda: {
            "notion": {"cron": DAILY_6, "enabled": True},
            "confluence": {"cron": DAILY_6, "enabled": True},
            "jira": {"cron": DAILY_6, "enabled": False},  # disabled → ignored
            "slack": {"cron": "0 12 * * *", "enabled": True},  # not yet due
        },
    )
    last_runs = {
        "notion": datetime(2026, 9, 13, 6, 5, tzinfo=UTC),  # yesterday → missed 6am today
        "confluence": datetime(2026, 9, 13, 6, 5, tzinfo=UTC),
        "slack": datetime(2026, 9, 13, 12, 2, tzinfo=UTC),  # ran yesterday noon; next is today noon
    }
    monkeypatch.setattr(scheduler, "_last_completed", lambda s: last_runs.get(s))
    calls: list[list[str]] = []

    async def fake_start(sources):
        calls.append(sources)
        return {"ok": True}

    monkeypatch.setattr(scheduler.orch, "start_harvest", fake_start)
    monkeypatch.setattr(scheduler.orch.state, "status", "idle", raising=False)

    started = await scheduler.catch_up_missed_runs(now)

    assert sorted(started) == ["confluence", "notion"]
    assert calls == [["notion", "confluence"]]


async def test_catch_up_skips_when_harvest_already_running(monkeypatch):
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    monkeypatch.setattr(
        scheduler, "list_schedules", lambda: {"notion": {"cron": DAILY_6, "enabled": True}}
    )
    monkeypatch.setattr(scheduler, "_last_completed", lambda _s: None)
    monkeypatch.setattr(scheduler.orch.state, "status", "running", raising=False)

    async def boom(_sources):
        raise AssertionError("must not start a second harvest")

    monkeypatch.setattr(scheduler.orch, "start_harvest", boom)
    assert await scheduler.catch_up_missed_runs(now) == []
