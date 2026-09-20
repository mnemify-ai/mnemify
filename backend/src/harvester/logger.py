"""Harvest logger — append-only JSONL activity log.

HarvestLogger writes one JSON object per line to a .jsonl file.  Every entry
has a UTC timestamp and an action string; event-specific fields are added as
extra keys on the same object.

The log is useful for:
  - Debugging: see exactly what happened during a run
  - Auditing: track which pages were harvested, skipped, or deleted
  - Future dashboard: surface recent activity and run summaries

The companion read_log() utility lets you tail or filter recent entries without
needing a log-aggregation stack.

Typical usage:

    log = HarvestLogger()                  # <mnemify home>/.mnemify/harvest-log.jsonl
    run_id = manifest.start_run(source_type="notion", mode="scheduled")
    log.log_run_started(run_id, source_type="notion", mode="scheduled")

    # ... per document ...
    log.log_harvested(run_id, source_type="notion", source_id="abc", title="My Page", version=1, action="new")
    log.log_skipped(run_id, source_type="notion", source_id="xyz", title="Old page", reason="unchanged")

    log.log_run_completed(run_id, stats={"found": 10, "harvested": 1, "skipped": 9, "failed": 0})
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HarvestLogger:
    """Append-only JSONL logger for harvest activity.

    Thread-safe for single-process use (file opened/closed per write).
    For higher throughput, the file handle can be kept open — but for the
    expected harvester volume (hundreds of docs/run) open-per-write is fine.
    """

    def __init__(self, log_path: str | Path | None = None):
        # Resolved here, not in the signature: a default argument would bind
        # one path at import time and ignore later MNEMIFY_HOME changes.
        if log_path is None:
            from src import paths

            log_path = paths.data_dir() / "harvest-log.jsonl"
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Internal write ─────────────────────────────────────────────

    def _write(self, entry: dict) -> None:
        """Append a single JSON entry to the log file."""
        entry.setdefault("ts", _now_iso())
        line = json.dumps(entry, ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ── Run lifecycle ──────────────────────────────────────────────

    def log_run_started(
        self,
        run_id: str,
        *,
        source_type: str | None = None,
        mode: str = "scheduled",
    ) -> None:
        self._write({
            "action": "harvest_started",
            "run": run_id,
            "source": source_type or "all",
            "mode": mode,
        })

    def log_run_completed(self, run_id: str, *, stats: dict) -> None:
        """Log end-of-run summary stats.

        Stats dict keys: found, harvested, skipped, failed, duration_sec (opt).
        """
        self._write({
            "action": "harvest_completed",
            "run": run_id,
            "docs_found": stats.get("found", 0),
            "docs_harvested": stats.get("harvested", 0),
            "docs_skipped": stats.get("skipped", 0),
            "docs_failed": stats.get("failed", 0),
            **({} if "duration_sec" not in stats else {"duration_sec": stats["duration_sec"]}),
        })

    # ── Per-document events ────────────────────────────────────────

    def log_harvested(
        self,
        run_id: str,
        *,
        source_type: str,
        source_id: str,
        title: str,
        version: int,
        action: str,  # "new" | "updated"
        bytes: int | None = None,
    ) -> None:
        entry = {
            "action": "harvested",
            "run": run_id,
            "source": source_type,
            "id": source_id,
            "title": title,
            "version": version,
            "change": action,
        }
        if bytes is not None:
            entry["bytes"] = bytes
        self._write(entry)

    def log_skipped(
        self,
        run_id: str,
        *,
        source_type: str,
        source_id: str,
        title: str,
        reason: str,
    ) -> None:
        self._write({
            "action": "skipped",
            "run": run_id,
            "source": source_type,
            "id": source_id,
            "title": title,
            "reason": reason,
        })

    def log_failed(
        self,
        run_id: str,
        *,
        source_type: str,
        source_id: str,
        title: str,
        error: str,
    ) -> None:
        self._write({
            "action": "harvest_failed",
            "run": run_id,
            "source": source_type,
            "id": source_id,
            "title": title,
            "error": error,
        })

    def log_deleted(
        self,
        run_id: str,
        *,
        source_type: str,
        source_id: str,
        title: str,
    ) -> None:
        self._write({
            "action": "deleted_at_source",
            "run": run_id,
            "source": source_type,
            "id": source_id,
            "title": title,
        })

    def log_attachment(
        self,
        run_id: str,
        *,
        source_type: str,
        parent_id: str,
        filename: str,
        size: int | None = None,
    ) -> None:
        self._write({
            "action": "attachment_downloaded",
            "run": run_id,
            "source": source_type,
            "parent": parent_id,
            "file": filename,
            **({} if size is None else {"size": size}),
        })

    # ── Query ──────────────────────────────────────────────────────

    def read_log(
        self,
        since: datetime | None = None,
        action_filter: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Read and optionally filter log entries.

        Args:
            since: Only return entries with ts >= this datetime.
            action_filter: Only return entries with this exact action string.
            limit: Maximum number of entries to return (most recent first).

        Returns:
            List of parsed log entry dicts, in file order (oldest first) unless
            limit is set in which case the tail is returned.
        """
        if not self.log_path.exists():
            return []

        entries: list[dict] = []
        with self.log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed log line: {line[:80]!r}")
                    continue

                if action_filter and entry.get("action") != action_filter:
                    continue

                if since:
                    ts_str = entry.get("ts", "")
                    try:
                        if ts_str.endswith("Z"):
                            ts_str = ts_str[:-1] + "+00:00"
                        entry_ts = datetime.fromisoformat(ts_str)
                        if entry_ts < since:
                            continue
                    except (ValueError, AttributeError):
                        pass

                entries.append(entry)

        if limit is not None:
            entries = entries[-limit:]

        return entries
