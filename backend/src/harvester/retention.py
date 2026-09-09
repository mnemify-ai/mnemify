"""Retention sweep — purge ``deleted_at_source`` docs after a grace period.

Shared by the CLI ``purge`` command, the Settings → Data "Purge now" action,
and the post-harvest auto-sweep that runs when ``data_retention.on_source_delete``
is ``"purge"`` in ``mnemify.yaml``.

A doc is eligible for purge when:

* ``harvest_status = 'deleted_at_source'``
* the row's ``status_changed_at`` is older than ``grace_days`` ago
  (falls back to ``harvested_at`` when ``status_changed_at`` is NULL —
  legacy rows from before the column existed)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .manifest import HarvestManifest
from .normalized_store import NormalizedStore
from .raw_store import RawStore


logger = logging.getLogger(__name__)


@dataclass
class PurgeResult:
    """Outcome of a purge sweep — useful for both UI and CLI surfaces."""

    eligible: int  # rows that matched the predicate
    purged: int    # rows actually deleted (== eligible when not dry_run)
    skipped: int   # rows still within the grace period
    source_ids: list[str]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def count_deleted(manifest: HarvestManifest, source: str | None = None) -> int:
    """Return how many docs are currently marked ``deleted_at_source``."""
    if source:
        rows = manifest.get_documents(source_type=source, status="deleted_at_source")
    else:
        rows = manifest.get_documents(status="deleted_at_source")
    return len(rows)


def purge_deleted(
    manifest: HarvestManifest,
    raw_store: RawStore,
    normalized_store: NormalizedStore | None,
    *,
    source: str | None = None,
    grace_days: int = 0,
    dry_run: bool = False,
) -> PurgeResult:
    """Delete raw + normalized files and manifest rows for eligible docs.

    Args:
        source: Restrict to one source; ``None`` sweeps every source.
        grace_days: Skip rows whose ``status_changed_at`` is newer than this.
            ``0`` purges everything that's currently ``deleted_at_source``.
        dry_run: Inspect-only — count rows but don't touch disk or DB.

    Cutoff comparison uses ``status_changed_at`` when present, else falls
    back to ``harvested_at`` (so legacy rows aren't stuck in limbo). Rows
    with neither timestamp are treated as old enough to purge.
    """
    if source:
        rows = manifest.get_documents(source_type=source, status="deleted_at_source")
    else:
        rows = manifest.get_documents(status="deleted_at_source")

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=grace_days)
        if grace_days > 0
        else None
    )

    eligible_rows: list[dict] = []
    skipped = 0
    for row in rows:
        if cutoff is not None:
            ts = _parse_iso(row.get("status_changed_at")) or _parse_iso(
                row.get("harvested_at")
            )
            if ts is not None and ts > cutoff:
                skipped += 1
                continue
        eligible_rows.append(row)

    purged_ids: list[str] = []
    if not dry_run:
        for row in eligible_rows:
            src_type = row["source_type"]
            src_id = row["source_id"]
            try:
                raw_store.delete(src_type, src_id)
            except Exception:  # noqa: BLE001
                logger.warning("retention: raw_store.delete failed for %s/%s",
                               src_type, src_id, exc_info=True)
            if normalized_store is not None:
                try:
                    normalized_store.delete(src_type, src_id)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "retention: normalized_store.delete failed for %s/%s",
                        src_type, src_id, exc_info=True,
                    )
            with manifest._transaction():
                manifest._conn.execute(
                    "DELETE FROM documents WHERE source_type = ? AND source_id = ?",
                    (src_type, src_id),
                )
            purged_ids.append(src_id)

    return PurgeResult(
        eligible=len(eligible_rows),
        purged=len(purged_ids),
        skipped=skipped,
        source_ids=purged_ids if not dry_run else [r["source_id"] for r in eligible_rows],
    )
