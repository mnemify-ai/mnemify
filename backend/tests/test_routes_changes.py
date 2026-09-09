"""Tests for GET /api/changes and the post-harvest auto-compile hook."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_log(dir_: Path, entries: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    with (dir_ / "harvest-log.jsonl").open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _client(tmp_path, monkeypatch) -> TestClient:
    from src.api import create_app

    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


NOW = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def test_changes_empty_when_no_log(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/changes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == {"new": 0, "updated": 0, "deleted": 0, "by_source": {}}
    assert data["changes"] == []
    assert data["truncated"] is False
    assert data["boundary"]["kind"] == "last_compile"
    assert data["boundary"]["ts"] is None


def test_changes_rejects_bad_since(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/changes?since=not-a-date").status_code == 422


def test_changes_dedupes_and_joins_authors(tmp_path, monkeypatch):
    data_dir = tmp_path / ".mnemify"
    _write_log(data_dir, [
        # Same doc harvested twice: first new, then updated → one row, "new" wins.
        {"action": "harvested", "run": "r1", "source": "confluence", "id": "p1",
         "title": "Roadmap", "version": 1, "change": "new", "ts": _iso(NOW - timedelta(hours=3))},
        {"action": "harvested", "run": "r2", "source": "confluence", "id": "p1",
         "title": "Roadmap", "version": 2, "change": "updated", "ts": _iso(NOW - timedelta(hours=1))},
        # An updated doc from another source.
        {"action": "harvested", "run": "r2", "source": "notion", "id": "n1",
         "title": "Meeting notes", "version": 5, "change": "updated", "ts": _iso(NOW - timedelta(hours=2))},
        # A deletion.
        {"action": "deleted_at_source", "run": "r2", "source": "notion", "id": "n2",
         "title": "Old page", "ts": _iso(NOW - timedelta(minutes=30))},
        # Noise that must be ignored.
        {"action": "skipped", "run": "r2", "source": "notion", "id": "n3",
         "title": "Unchanged", "reason": "unchanged", "ts": _iso(NOW)},
        {"action": "harvest_completed", "run": "r2", "docs_found": 4, "ts": _iso(NOW)},
    ])

    from src.harvester.manifest import HarvestManifest
    manifest = HarvestManifest(data_dir / "harvest-manifest.db")
    manifest.upsert_document(
        "confluence", "p1", "Roadmap",
        source_url="https://x.atlassian.net/wiki/spaces/ENG/pages/1",
        source_modified=_iso(NOW - timedelta(hours=1)),
        metadata={
            "author_name": "Sarah Chen",
            "last_modified_by": "Tom Ito",
            "url": "https://x.atlassian.net/wiki/spaces/ENG/pages/1",
            "space_key": "ENG",
        },
    )
    manifest.upsert_document(
        "notion", "n1", "Meeting notes",
        source_modified=_iso(NOW - timedelta(hours=2)),
        metadata={"created_by": "Ana Ruiz", "last_modified_by": "Ana Ruiz"},
    )
    manifest.close()

    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/changes").json()

    assert data["summary"] == {
        "new": 1, "updated": 1, "deleted": 1,
        "by_source": {
            "confluence": {"new": 1, "updated": 0, "deleted": 0},
            "notion": {"new": 0, "updated": 1, "deleted": 1},
        },
    }
    by_id = {c["source_id"]: c for c in data["changes"]}
    assert set(by_id) == {"p1", "n1", "n2"}
    # Dedupe: p1 appears once, stays "new", carries the latest timestamp.
    assert by_id["p1"]["change"] == "new"
    assert by_id["p1"]["author"] == "Sarah Chen"
    assert by_id["p1"]["last_modified_by"] == "Tom Ito"
    assert by_id["p1"]["space"] == "ENG"
    assert by_id["p1"]["url"].startswith("https://x.atlassian.net")
    assert by_id["n1"]["author"] == "Ana Ruiz"
    # Deleted doc has no manifest row — nulls, but survives in the list.
    assert by_id["n2"]["change"] == "deleted"
    assert by_id["n2"]["author"] is None
    # Newest first.
    assert data["changes"][0]["source_id"] == "n2"


def test_changes_since_filters_and_flags_truncation(tmp_path, monkeypatch):
    data_dir = tmp_path / ".mnemify"
    _write_log(data_dir, [
        {"action": "harvested", "run": "r1", "source": "notion", "id": "a",
         "title": "Old", "version": 1, "change": "new", "ts": _iso(NOW - timedelta(days=2))},
        {"action": "harvested", "run": "r2", "source": "notion", "id": "b",
         "title": "Fresh", "version": 1, "change": "new", "ts": _iso(NOW - timedelta(hours=1))},
    ])
    client = _client(tmp_path, monkeypatch)

    recent = client.get(
        "/api/changes", params={"since": _iso(NOW - timedelta(hours=6))}
    ).json()
    assert [c["source_id"] for c in recent["changes"]] == ["b"]
    assert recent["boundary"]["kind"] == "timestamp"
    # Log's oldest entry (2 days ago) postdates nothing here → not truncated.
    assert recent["truncated"] is False

    # Boundary older than the oldest log line → truncated flag set.
    ancient = client.get(
        "/api/changes", params={"since": _iso(NOW - timedelta(days=30))}
    ).json()
    assert ancient["truncated"] is True
    assert len(ancient["changes"]) == 2


def test_changes_last_compile_boundary_reads_terrain_db(tmp_path, monkeypatch):
    data_dir = tmp_path / ".mnemify"
    _write_log(data_dir, [
        {"action": "harvested", "run": "r1", "source": "notion", "id": "a",
         "title": "Before compile", "version": 1, "change": "new",
         "ts": _iso(NOW - timedelta(days=2))},
        {"action": "harvested", "run": "r2", "source": "notion", "id": "b",
         "title": "After compile", "version": 1, "change": "new",
         "ts": _iso(NOW - timedelta(hours=1))},
    ])
    from src.terrain.utils.store import TerrainStore
    store = TerrainStore(data_dir / "terrain.db")
    run_id = store.start_run({})
    store.complete_run(run_id, {"notes": 1})
    # Pin the completed_at between the two log entries.
    store._conn.execute(
        "UPDATE terrain_runs SET completed_at=? WHERE id=?",
        (_iso(NOW - timedelta(days=1)), run_id),
    )
    store._conn.commit()
    assert store.get_last_compile_time() == _iso(NOW - timedelta(days=1))
    store.close()

    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/changes").json()
    assert data["boundary"]["kind"] == "last_compile"
    assert data["boundary"]["ts"] == _iso(NOW - timedelta(days=1))
    assert [c["source_id"] for c in data["changes"]] == ["b"]


def test_changes_freshness_fields_default_null(tmp_path, monkeypatch):
    # Point yaml at a non-existent file so the repo's real config can't leak in.
    monkeypatch.setenv("MNEMIFY_YAML_FILE", str(tmp_path / "mnemify.yaml"))
    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/changes").json()
    assert data["last_harvest_time"] is None
    assert data["schedule_enabled"] is False


def test_changes_last_harvest_time_from_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_YAML_FILE", str(tmp_path / "mnemify.yaml"))
    data_dir = tmp_path / ".mnemify"
    data_dir.mkdir(parents=True, exist_ok=True)

    from src.harvester.manifest import HarvestManifest
    manifest = HarvestManifest(data_dir / "harvest-manifest.db")
    completed = _iso(NOW - timedelta(hours=4))
    for offset_days, ts in ((2, _iso(NOW - timedelta(days=2))), (0, completed)):
        run_id = manifest.start_run("confluence", mode="manual")
        manifest.complete_run(run_id, {"found": 1, "harvested": 1})
        manifest._conn.execute(
            "UPDATE harvest_runs SET completed_at=? WHERE id=?", (ts, run_id)
        )
        manifest._conn.commit()
    manifest.close()

    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/changes").json()
    # Most recent completed run wins, regardless of source.
    assert data["last_harvest_time"] == completed


def test_changes_schedule_enabled_reflects_yaml(tmp_path, monkeypatch):
    yaml_path = tmp_path / "mnemify.yaml"
    monkeypatch.setenv("MNEMIFY_YAML_FILE", str(yaml_path))

    yaml_path.write_text(
        "sources: {}\nschedules:\n  confluence:\n    cron: '0 6 * * *'\n    enabled: true\n",
        encoding="utf-8",
    )
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/changes").json()["schedule_enabled"] is True

    yaml_path.write_text(
        "sources: {}\nschedules:\n  confluence:\n    cron: '0 6 * * *'\n    enabled: false\n",
        encoding="utf-8",
    )
    assert client.get("/api/changes").json()["schedule_enabled"] is False


def test_compile_settings_include_auto_compile_default_off(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/settings/compile").json()
    assert data["auto_compile_after_harvest"] is False


@pytest.mark.asyncio
async def test_finalize_kicks_auto_compile_when_enabled(monkeypatch):
    from src.api import orchestrator as orch
    from src.api import compile_orchestrator as compile_orch
    from src.api import routes_settings

    calls: list[dict] = []

    async def fake_start_compile(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(compile_orch, "start_compile", fake_start_compile)
    monkeypatch.setattr(
        routes_settings, "_compile_settings_block",
        lambda: {"auto_compile_after_harvest": True},
    )

    orch._maybe_auto_compile()
    await asyncio.sleep(0)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_finalize_skips_auto_compile_when_disabled(monkeypatch):
    from src.api import orchestrator as orch
    from src.api import compile_orchestrator as compile_orch
    from src.api import routes_settings

    calls: list[dict] = []

    async def fake_start_compile(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(compile_orch, "start_compile", fake_start_compile)
    monkeypatch.setattr(
        routes_settings, "_compile_settings_block",
        lambda: {"auto_compile_after_harvest": False},
    )

    orch._maybe_auto_compile()
    await asyncio.sleep(0)
    assert calls == []


def test_compile_settings_accept_full_claude_model_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    base = client.get("/api/settings/compile").json()

    # Full ids (what the unified model dropdown now stores) round-trip.
    body = {**base, "claude_extract_model": "claude-haiku-4-5", "claude_name_model": "claude-fable-5-1"}
    resp = client.patch("/api/settings/compile", json=body)
    assert resp.status_code == 200, resp.text
    saved = client.get("/api/settings/compile").json()
    assert saved["claude_extract_model"] == "claude-haiku-4-5"
    assert saved["claude_name_model"] == "claude-fable-5-1"

    # Legacy aliases still validate.
    resp = client.patch("/api/settings/compile", json={**base, "claude_name_model": "opus"})
    assert resp.status_code == 200, resp.text

    # Anything that isn't an alias or a claude-… id is rejected.
    resp = client.patch("/api/settings/compile", json={**base, "claude_name_model": "gpt-5.6-terra"})
    assert resp.status_code == 422
