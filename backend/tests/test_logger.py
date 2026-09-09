"""Unit tests for HarvestLogger (src/harvester/logger.py)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

from src.harvester.logger import HarvestLogger

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def log(tmp_path) -> HarvestLogger:
    return HarvestLogger(tmp_path / "harvest-log.jsonl")


def read_all(log: HarvestLogger) -> list[dict]:
    return log.read_log()


# ── Write & read roundtrip ─────────────────────────────────────────

def test_log_run_started_written_and_readable(log):
    log.log_run_started("run_001", source_type="notion", mode="scheduled")
    entries = read_all(log)
    assert len(entries) == 1
    e = entries[0]
    assert e["action"] == "harvest_started"
    assert e["run"] == "run_001"
    assert e["source"] == "notion"
    assert e["mode"] == "scheduled"
    assert "ts" in e


def test_log_run_started_defaults_source_to_all(log):
    log.log_run_started("run_x")
    e = read_all(log)[0]
    assert e["source"] == "all"


def test_log_harvested(log):
    log.log_harvested("run_1", source_type="notion", source_id="p1", title="My Page", version=1, action="new")
    e = read_all(log)[0]
    assert e["action"] == "harvested"
    assert e["source"] == "notion"
    assert e["id"] == "p1"
    assert e["title"] == "My Page"
    assert e["version"] == 1
    assert e["change"] == "new"


def test_log_updated_action(log):
    log.log_harvested("run_1", source_type="notion", source_id="p1", title="T", version=2, action="updated")
    e = read_all(log)[0]
    assert e["change"] == "updated"


def test_log_skipped(log):
    log.log_skipped("run_1", source_type="notion", source_id="p2", title="Old", reason="unchanged")
    e = read_all(log)[0]
    assert e["action"] == "skipped"
    assert e["reason"] == "unchanged"


def test_log_failed(log):
    log.log_failed("run_1", source_type="notion", source_id="p3", title="Fail", error="HTTP 429")
    e = read_all(log)[0]
    assert e["action"] == "harvest_failed"
    assert e["id"] == "p3"
    assert e["error"] == "HTTP 429"
    assert "ts" in e


def test_log_harvested_with_bytes(log):
    log.log_harvested(
        "run_1",
        source_type="notion",
        source_id="p1",
        title="Page",
        version=1,
        action="new",
        bytes=4096,
    )
    e = read_all(log)[0]
    assert e["bytes"] == 4096


def test_log_harvested_without_bytes_omits_field(log):
    log.log_harvested("run_1", source_type="notion", source_id="p1", title="P", version=1, action="new")
    e = read_all(log)[0]
    assert "bytes" not in e


def test_log_deleted(log):
    log.log_deleted("run_1", source_type="notion", source_id="p4", title="Gone")
    e = read_all(log)[0]
    assert e["action"] == "deleted_at_source"
    assert e["id"] == "p4"


def test_log_attachment_with_size(log):
    log.log_attachment("run_1", source_type="notion", parent_id="p1", filename="photo.png", size=12345)
    e = read_all(log)[0]
    assert e["action"] == "attachment_downloaded"
    assert e["file"] == "photo.png"
    assert e["size"] == 12345


def test_log_attachment_without_size(log):
    log.log_attachment("run_1", source_type="notion", parent_id="p1", filename="doc.pdf")
    e = read_all(log)[0]
    assert "size" not in e


def test_log_run_completed(log):
    log.log_run_completed("run_1", stats={"found": 50, "harvested": 10, "skipped": 39, "failed": 1})
    e = read_all(log)[0]
    assert e["action"] == "harvest_completed"
    assert e["docs_found"] == 50
    assert e["docs_harvested"] == 10
    assert e["docs_skipped"] == 39
    assert e["docs_failed"] == 1


def test_log_run_completed_with_duration(log):
    log.log_run_completed("run_1", stats={"found": 5, "duration_sec": 3.2})
    e = read_all(log)[0]
    assert e["duration_sec"] == 3.2


def test_log_run_completed_defaults_zeros(log):
    log.log_run_completed("run_1", stats={})
    e = read_all(log)[0]
    assert e["docs_found"] == 0


# ── Multiple entries ───────────────────────────────────────────────

def test_multiple_entries_appended_in_order(log):
    log.log_run_started("run_1")
    log.log_harvested("run_1", source_type="notion", source_id="p1", title="A", version=1, action="new")
    log.log_skipped("run_1", source_type="notion", source_id="p2", title="B", reason="unchanged")
    log.log_run_completed("run_1", stats={"found": 2, "harvested": 1, "skipped": 1})
    entries = read_all(log)
    assert len(entries) == 4
    assert entries[0]["action"] == "harvest_started"
    assert entries[-1]["action"] == "harvest_completed"


def test_each_entry_has_ts_field(log):
    log.log_run_started("r")
    log.log_skipped("r", source_type="notion", source_id="p", title="T", reason="filtered")
    for e in read_all(log):
        assert "ts" in e


# ── read_log filtering ─────────────────────────────────────────────

def test_read_log_action_filter(log):
    log.log_harvested("r", source_type="notion", source_id="p1", title="A", version=1, action="new")
    log.log_skipped("r", source_type="notion", source_id="p2", title="B", reason="unchanged")
    log.log_harvested("r", source_type="notion", source_id="p3", title="C", version=1, action="new")
    harvested = log.read_log(action_filter="harvested")
    assert len(harvested) == 2
    assert all(e["action"] == "harvested" for e in harvested)


def test_read_log_since_filter(log, tmp_path):
    """Entries before `since` are excluded."""
    # Manually write entries with specific timestamps
    log_path = tmp_path / "harvest-log.jsonl"
    entries = [
        {"ts": "2026-03-01T00:00:00+00:00", "action": "skipped", "run": "r"},
        {"ts": "2026-05-01T00:00:00+00:00", "action": "harvested", "run": "r"},
        {"ts": "2026-07-01T00:00:00+00:00", "action": "harvested", "run": "r"},
    ]
    with log_path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    logger = HarvestLogger(log_path)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = logger.read_log(since=since)
    assert len(result) == 2
    assert all(e["action"] == "harvested" for e in result)


def test_read_log_limit(log):
    for i in range(10):
        log.log_skipped("r", source_type="notion", source_id=f"p{i}", title=f"P{i}", reason="unchanged")
    tail = log.read_log(limit=3)
    assert len(tail) == 3
    # Should be the last 3 entries
    assert tail[-1]["id"] == "p9"


def test_read_log_empty_file_returns_empty_list(log):
    result = log.read_log()
    assert result == []


def test_read_log_nonexistent_file_returns_empty_list(tmp_path):
    logger = HarvestLogger(tmp_path / "nonexistent.jsonl")
    assert logger.read_log() == []


def test_read_log_skips_malformed_lines(tmp_path):
    log_path = tmp_path / "log.jsonl"
    with log_path.open("w") as f:
        f.write('{"action": "harvested", "run": "r", "ts": "2026-01-01T00:00:00+00:00"}\n')
        f.write("NOT VALID JSON\n")
        f.write('{"action": "skipped", "run": "r", "ts": "2026-01-01T00:00:00+00:00"}\n')
    logger = HarvestLogger(log_path)
    entries = logger.read_log()
    assert len(entries) == 2


def test_log_file_is_valid_jsonl(log):
    """Every line in the log file must be valid JSON."""
    log.log_run_started("r1", source_type="notion")
    log.log_harvested("r1", source_type="notion", source_id="p", title="T", version=1, action="new")
    log.log_run_completed("r1", stats={"found": 1})

    with log.log_path.open() as f:
        for line in f:
            if line.strip():
                json.loads(line)  # must not raise
