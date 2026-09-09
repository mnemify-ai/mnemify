"""Harvest orchestrator — drives a full harvest run end-to-end.

Coordinates plugin, manifest, and logger into a single run lifecycle:
  1. Test source connection (fail fast if unhealthy)
  2. Start a manifest run and log it
  3. List documents
  4. Fetch documents concurrently (semaphore-bounded)
  5. Detect deletions (pages no longer returned by source)
  6. Complete the run with stats

Usage:
    orchestrator = HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=harvest_logger,
        max_concurrent=5,
        raw_store=RawStore(DATA_DIR / "raw", converter_version="0.1.0"),
    )
    result = await orchestrator.run()
    print(result.summary())
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.harvester import (
    DocRef,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
    begin_extraction_capture,
    reset_extraction_capture,
    take_extraction_warnings,
)
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.normalized_store import NormalizedStore
from src.harvester.raw_store import RawStore
from src.utils.hashing import sha256_hash

logger = logging.getLogger(__name__)

# Max attachments fetched concurrently per document. Bounds the in-flight
# downloads of a single attachment-heavy doc (e.g. an image gallery) so it
# can't swamp the source/blob API while still overlapping their network waits.
ATTACHMENT_CONCURRENCY = 5


def _jsonable(value):
    """Recursively convert a value to something ``json.dumps`` accepts.

    User-defined YAML frontmatter in Obsidian notes can contain ``date``
    or ``datetime`` objects (see the Q2 planning fixture note). Rather
    than asking every plugin to pre-convert, we defensively coerce here.
    Unknown objects fall back to ``str(value)``.
    """
    from datetime import date, datetime as _dt

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (_dt, date)):
        return value.isoformat()
    return str(value)


def _is_unreliable_modified_at(doc_ref: DocRef) -> bool:
    """True for source/document combinations whose ``modified_at`` doesn't
    move when content actually changes. Such docs must always be re-fetched
    so the post-fetch content-hash gate can do its job.

    Currently: Notion databases. The Notion API's ``last_edited_time`` on a
    database doesn't advance when its rows are added, edited, or removed,
    only when schema-level changes occur. Skipping the fetch based on
    ``modified_at`` would freeze databases at their first-harvested state.
    """
    if doc_ref.source_type == "notion":
        return doc_ref.metadata.get("document_type") == "database"
    return False


def _doc_already_harvested(doc_ref: DocRef, existing: dict) -> bool:
    """True when the manifest's stored row covers ``doc_ref``'s version.

    Mirrors the ``manifest.upsert_document`` skip predicate (manifest.py
    line 235-240): we treat the doc as already-harvested when the
    listing's ``modified_at`` is less than or equal to the stored
    ``source_modified``. The ``<=`` (not ``==``) tolerates listing
    endpoints that occasionally serve a slightly stale ``modified_at``.

    Also requires the manifest to actually carry the harvested artifact
    (``raw_path`` non-null) — if a previous run upserted the row but the
    raw write failed, we re-fetch.
    """
    if not existing.get("raw_path"):
        return False
    stored_iso = existing.get("source_modified")
    if not stored_iso or doc_ref.modified_at is None:
        return False
    try:
        stored_dt = datetime.fromisoformat(stored_iso)
    except (TypeError, ValueError):
        return False
    incoming = doc_ref.modified_at
    if stored_dt.tzinfo is None and incoming.tzinfo is not None:
        stored_dt = stored_dt.replace(tzinfo=timezone.utc)
    elif stored_dt.tzinfo is not None and incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    return incoming <= stored_dt


@dataclass
class WriteBackConfig:
    """Configuration for optional write-back to the source."""

    enabled: bool = False
    property_name: str = "Harvested At"


class _Progress:
    """Rate-limited progress reporter for the fetch loop.

    Prints every doc when total ≤ 50, otherwise every ~1% of total
    (capped so there are at most ~100 log lines regardless of corpus
    size). Always prints the final doc so the last line matches total.
    """

    def __init__(self, total: int, source_type: str) -> None:
        self.total = total
        self.source_type = source_type
        self.done = 0
        self.step = 1 if total <= 50 else max(1, total // 100)
        self.lock = asyncio.Lock()

    async def tick(self, title: str, status: str) -> None:
        async with self.lock:
            self.done += 1
            if self.done % self.step == 0 or self.done == self.total:
                pct = (self.done / self.total) * 100 if self.total else 100.0
                truncated = (title or "")[:60]
                logger.info(
                    f"[{self.done:>4}/{self.total}] {self.source_type}: "
                    f"{status} {truncated!r} ({pct:.1f}%)"
                )


@dataclass
class HarvestResult:
    """Summary of a completed harvest run."""

    run_id: str
    source_type: str
    found: int = 0
    harvested: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    duration_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    # Content-level drops during extraction, aggregated by kind →
    # occurrence count (e.g. ``{"notion_unsupported_block": 14}``). Unlike
    # ``errors`` (whole-doc failures) these are partial: the document was
    # harvested, but some blocks/comments/nodes couldn't be rendered.
    warnings: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        parts = [
            f"Run {self.run_id} [{self.source_type}]:",
            f"  found={self.found}",
            f"  harvested={self.harvested}",
            f"  skipped={self.skipped}",
            f"  failed={self.failed}",
            f"  deleted={self.deleted}",
            f"  duration={self.duration_sec:.1f}s",
        ]
        if self.errors:
            parts.append(f"  errors={len(self.errors)}")
        if self.warnings:
            dropped = sum(self.warnings.values())
            parts.append(f"  dropped={dropped} {self.warnings}")
        return "\n".join(parts)


class HarvestOrchestrator:
    """Drives a complete harvest run for a single source plugin."""

    def __init__(
        self,
        plugin: SourcePlugin,
        manifest: HarvestManifest,
        harvest_logger: HarvestLogger,
        max_concurrent: int = 5,
        raw_store: RawStore | None = None,
        normalized_store: NormalizedStore | None = None,
        write_back: WriteBackConfig | None = None,
        dry_run: bool = False,
        force_full: bool = False,
        skip_attachments: bool = False,
        max_documents: int | None = None,
        skip_mark_deleted: bool = False,
        active_scope_ids: list[str] | None = None,
    ):
        self.plugin = plugin
        self.manifest = manifest
        self.harvest_logger = harvest_logger
        self.max_concurrent = max_concurrent
        self.raw_store = raw_store
        self.normalized_store = normalized_store
        self.write_back = write_back or WriteBackConfig()
        self.dry_run = dry_run
        self.force_full = force_full
        self.skip_attachments = skip_attachments
        self.max_documents = max_documents
        # The scope ids currently configured in YAML for this source — used
        # by the scope-aware deletion pass to distinguish docs whose origin
        # scope is still configured (true deletions) from docs whose scope
        # was removed (out_of_scope). ``None`` falls back to the legacy
        # behavior so CLI / test runs don't change semantics.
        self.active_scope_ids = (
            set(active_scope_ids) if active_scope_ids is not None else None
        )
        # When True, skip the post-fetch "mark anything not listed as deleted"
        # pass. Used by scoped runs (e.g. Manage Scope auto-harvest of just
        # newly added items) where ``list_documents()`` only returns the
        # subset we asked for — running mark_deleted there would wrongly nuke
        # every previously-harvested doc.
        self.skip_mark_deleted = skip_mark_deleted

    async def run(self, source_type: str = "notion", mode: str = "scheduled") -> HarvestResult:
        """Execute a complete harvest run and return the result."""
        start_time = time.monotonic()
        result = HarvestResult(run_id="", source_type=source_type)

        # 1. Health check — fail fast
        health = await self.plugin.test_connection()
        if not health.healthy:
            raise RuntimeError(f"Source health check failed: {health.message}")

        # 2. Listing is unfiltered; per-doc Layer 1 is the authority.
        # A source-wide ``since`` watermark dropped newly-scoped pages with old
        # ``modified_at`` from the listing *before* Layer 1 could check them
        # per-doc, breaking Manage Scope expansion (and silently marking
        # unchanged docs as deleted_at_source on plain scheduled runs).
        # ``since=None`` lets the plugin return its full in-scope listing;
        # ``_doc_already_harvested`` short-circuits at the doc level.
        # Plugins that historically used ``since`` for *server-side* cost
        # savings (jira/github/gmail/slack) still accept the kwarg — they
        # just receive None here. Restore the optimization with a scope-aware
        # approach when those sources are wired into the UI.
        since = None
        logger.info(
            f"Harvesting {source_type} — per-doc resume "
            f"(force_full={self.force_full})"
        )

        # 3. Start run
        run_id = self.manifest.start_run(source_type=source_type, mode=mode)
        result.run_id = run_id
        self.harvest_logger.log_run_started(run_id, source_type=source_type, mode=mode)

        # 4. List documents
        all_docs = await self.plugin.list_documents(since=since)
        result.found = len(all_docs)
        to_fetch = all_docs

        # Hard cap on documents to fetch (useful for integration tests / dry probes).
        # Sort by source_id before slicing so the selected subset is deterministic
        # regardless of the order list_documents() returns documents.
        if self.max_documents is not None and len(to_fetch) > self.max_documents:
            to_fetch = sorted(to_fetch, key=lambda d: d.source_id)[: self.max_documents]
            extra = len(all_docs) - self.max_documents
            logger.info(f"max_documents={self.max_documents}: capped fetch list, skipping {extra} extra")

        # 5. Fetch concurrently (bounded by semaphore) — skipped in dry_run
        if self.dry_run:
            logger.info(f"Dry run: would fetch {len(to_fetch)} document(s), skipping")
            result.skipped += len(to_fetch)
        else:
            semaphore = asyncio.Semaphore(self.max_concurrent)
            progress = _Progress(total=len(to_fetch), source_type=source_type)
            if to_fetch:
                logger.info(
                    f"Fetching {len(to_fetch)} document(s) from {source_type} "
                    f"(concurrency={self.max_concurrent})"
                )
            fetch_tasks = [
                asyncio.create_task(
                    self._fetch_one(doc_ref, run_id, semaphore, result, progress)
                )
                for doc_ref in to_fetch
            ]
            if fetch_tasks:
                await asyncio.gather(*fetch_tasks)

        # 6. Reconcile against the listing — scope-aware (Option B).
        # Scoped runs (Manage Scope auto-harvest of just-added items) still
        # skip the pass entirely since the listing is intentionally narrow.
        # Otherwise we hand `active_scope_ids` to the manifest so a doc whose
        # origin scope was removed from config is marked `out_of_scope`
        # instead of `deleted_at_source` — and is recoverable by re-adding
        # the scope item, without the user ever losing the raw file.
        if self.skip_mark_deleted:
            logger.info(
                f"Skipping deletion-reconcile for {source_type} "
                f"(scoped run — listing only the requested subset)"
            )
        else:
            active_ids = {d.source_id for d in all_docs}
            reconciled = self.manifest.reconcile_against_listing(
                source_type,
                active_ids,
                active_scope_ids=self.active_scope_ids,
            )
            deleted_ids = reconciled["deleted"]
            out_of_scope_ids = reconciled["out_of_scope"]
            preserved_ids = reconciled["preserved"]
            result.deleted = len(deleted_ids)

            for source_id in deleted_ids:
                self.harvest_logger.log_deleted(
                    run_id,
                    source_type=source_type,
                    source_id=source_id,
                    title=source_id,
                )

            if out_of_scope_ids:
                logger.info(
                    f"[{source_type}] Marked {len(out_of_scope_ids)} doc(s) "
                    "out_of_scope (their origin scope is no longer in config)"
                )
            if preserved_ids:
                logger.info(
                    f"[{source_type}] Preserved {len(preserved_ids)} doc(s) "
                    "with unknown origin (legacy rows) — they'll be tagged "
                    "on the next successful harvest"
                )

        # 7. Complete run
        result.duration_sec = time.monotonic() - start_time
        stats = {
            "found": result.found,
            "harvested": result.harvested,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": result.errors,
            "warnings": result.warnings,
            "duration_sec": result.duration_sec,
        }
        self.manifest.complete_run(run_id, stats)
        self.harvest_logger.log_run_completed(run_id, stats=stats)

        logger.info(f"Run complete: {result.summary()}")
        return result

    async def _fetch_one(
        self,
        doc_ref: DocRef,
        run_id: str,
        semaphore: asyncio.Semaphore,
        result: HarvestResult,
        progress: _Progress | None = None,
    ) -> None:
        """Fetch, hash, optionally persist, and upsert a single document.

        All attachment downloads and write-back calls happen inside the same
        semaphore acquisition so they respect the rate-limiter.
        """
        status = "failed"  # default; overwritten on each successful exit path
        async with semaphore:
            # Install a per-document collector so any content-level drops
            # during fetch/normalize (which run inside this task's context,
            # including the to_thread normalize) are attributed to this doc.
            warn_token = begin_extraction_capture()
            try:
                # Resume short-circuit: if the manifest already has this
                # exact (or newer) version of the doc, skip the fetch
                # entirely. Saves the per-page API budget on re-runs after
                # cancel and on routine incremental harvests.
                if not self.force_full and not _is_unreliable_modified_at(doc_ref):
                    existing = self.manifest.lookup(
                        doc_ref.source_type, doc_ref.source_id
                    )
                    if existing and _doc_already_harvested(doc_ref, existing):
                        result.skipped += 1
                        status = "unchanged"
                        self.harvest_logger.log_skipped(
                            run_id,
                            source_type=doc_ref.source_type,
                            source_id=doc_ref.source_id,
                            title=doc_ref.title,
                            reason="already harvested (no source change)",
                        )
                        return

                raw: RawDocument = await self.plugin.fetch_document(doc_ref)

                # Normalize once, up-front — failures here don't abort the
                # harvest (raw is the source of truth); the row's
                # normalized_path stays NULL and a future
                # ``mnemify normalize --force`` can retry.
                normalized: NormalizedDocument | None
                try:
                    # Offload to a worker thread — normalize() is CPU-bound
                    # (XHTML/blocks → markdown) and would otherwise block the
                    # event loop, stalling every other concurrent fetch.
                    normalized = await asyncio.to_thread(self.plugin.normalize, raw)
                except NotImplementedError:
                    normalized = None
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Normalization failed for %s/%s: %s — raw is preserved, "
                        "retry via 'mnemify normalize --force'",
                        doc_ref.source_type, doc_ref.source_id, e,
                    )
                    normalized = None

                # Hash content (off the event loop — large docs would otherwise
                # block concurrent fetches while hashing).
                content_hash = await asyncio.to_thread(sha256_hash, raw.content)

                # Merge list-time DocRef metadata with fetch-time RawDocument
                # metadata so the manifest carries the full picture — fields
                # that used to live in the .md frontmatter (labels, ancestors,
                # version_number, etc.) are only populated after fetch, so they
                # must come from raw.metadata. raw.metadata wins on key
                # conflicts because it's strictly richer than the list view.
                merged_meta: dict = {}
                if doc_ref.metadata:
                    merged_meta.update(doc_ref.metadata)
                if raw.metadata:
                    merged_meta.update(raw.metadata)
                doc_ref_meta = _jsonable(merged_meta) if merged_meta else None
                origin_scope_id = (merged_meta or {}).get("origin_scope_id")

                # Upsert into manifest first (without raw_path) — determines action
                doc_id, action = self.manifest.upsert_document(
                    source_type=doc_ref.source_type,
                    source_id=doc_ref.source_id,
                    title=doc_ref.title,
                    source_url=doc_ref.source_url,
                    content_hash=content_hash,
                    source_modified=doc_ref.modified_at,
                    raw_format=raw.format,
                    converter_version=(
                        self.raw_store.converter_version if self.raw_store else None
                    ),
                    metadata=doc_ref_meta,
                    origin_scope_id=origin_scope_id,
                )

                if action == "unchanged":
                    result.skipped += 1
                    status = "unchanged"
                    self.harvest_logger.log_skipped(
                        run_id,
                        source_type=doc_ref.source_type,
                        source_id=doc_ref.source_id,
                        title=doc_ref.title,
                        reason="unchanged",
                    )
                    return

                # WS1 — raw store write (only for new/updated docs; failure → count as failed)
                raw_path: str | None = None
                if self.raw_store is not None:
                    try:
                        written = self.raw_store.write(
                            doc_ref.source_type, doc_ref.source_id, raw
                        )
                        raw_path = written.as_posix()  # POSIX seps — portable across OSes
                        # Record the path directly — avoids re-running change detection
                        self.manifest.set_raw_path(
                            doc_ref.source_type,
                            doc_ref.source_id,
                            raw_path,
                            raw_bytes=len(raw.content),
                        )
                    except OSError as e:
                        result.failed += 1
                        status = "failed"
                        error_msg = f"{doc_ref.source_id}: raw write failed: {e}"
                        result.errors.append(error_msg)
                        logger.error(f"Raw write failed for {doc_ref.source_id!r}: {e}")
                        self.harvest_logger.log_failed(
                            run_id,
                            source_type=doc_ref.source_type,
                            source_id=doc_ref.source_id,
                            title=doc_ref.title,
                            error=str(e),
                        )
                        return

                # WS2 — normalization (markdown sidecar). Computed up-front
                # at fetch time; here we just persist. ``normalized is None``
                # means normalize() raised earlier (logged above); we leave
                # normalized_path NULL so a future ``mnemify normalize
                # --force`` can retry.
                if self.normalized_store is not None and normalized is not None:
                    try:
                        norm_written = self.normalized_store.write(
                            doc_ref.source_type, normalized
                        )
                        self.manifest.set_normalized_path(
                            doc_ref.source_type,
                            doc_ref.source_id,
                            norm_written.as_posix(),
                            normalizer_version=normalized.normalizer_version,
                            normalized_bytes=len(normalized.markdown.encode("utf-8")),
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "Normalized store write failed for %s/%s: %s — raw is "
                            "preserved, retry via 'mnemify normalize --force'",
                            doc_ref.source_type, doc_ref.source_id, e,
                        )

                # WS3 — attachment downloads (only on new/updated docs; skipped when skip_attachments=True)
                att_manifest: list[dict] = []
                if not self.skip_attachments and self.raw_store is not None and raw.attachments:
                    # Fetch attachments concurrently rather than one-at-a-time —
                    # the old serial loop held this doc's outer-semaphore slot for
                    # the full sum of every attachment's latency. Bound per-doc
                    # concurrency so one gallery-heavy doc can't swamp the API.
                    # Each task fetches + writes to disk and returns only the small
                    # manifest entry, so attachment bytes are released as we go.
                    att_sem = asyncio.Semaphore(
                        min(ATTACHMENT_CONCURRENCY, len(raw.attachments))
                    )

                    async def _grab(att_ref) -> dict | None:
                        async with att_sem:
                            try:
                                att_bytes = await self.plugin.fetch_attachment(att_ref)
                                att_path = self.raw_store.write_attachment(
                                    doc_ref.source_type,
                                    doc_ref.source_id,
                                    att_bytes,
                                    att_ref.filename,
                                )
                                return {
                                    "filename": att_ref.filename,
                                    "local_path": str(att_path),
                                    "sha256": sha256_hash(att_bytes),
                                    "size": len(att_bytes),
                                    "mime_type": att_ref.mime_type,
                                }
                            except Exception as e:  # noqa: BLE001
                                logger.warning(
                                    f"Attachment download failed for "
                                    f"{att_ref.filename!r} (parent {doc_ref.source_id!r}): {e}"
                                )
                                return None

                    # gather preserves input order → manifest + log order is stable.
                    for att_entry in await asyncio.gather(
                        *(_grab(att_ref) for att_ref in raw.attachments)
                    ):
                        if att_entry is None:
                            continue
                        att_manifest.append(att_entry)
                        self.harvest_logger.log_attachment(
                            run_id,
                            source_type=doc_ref.source_type,
                            parent_id=doc_ref.source_id,
                            filename=att_entry["filename"],
                            size=att_entry["size"],
                        )

                    # Persist attachment manifest into document metadata via direct update
                    if att_manifest:
                        row = self.manifest.lookup(doc_ref.source_type, doc_ref.source_id)
                        existing_meta: dict = {}
                        if row and row.get("metadata"):
                            try:
                                existing_meta = json.loads(row["metadata"])
                            except (json.JSONDecodeError, TypeError):
                                pass
                        existing_meta["attachments"] = att_manifest
                        self.manifest.update_metadata(
                            doc_ref.source_type,
                            doc_ref.source_id,
                            _jsonable(existing_meta),
                        )

                result.harvested += 1
                status = "harvested"
                row = self.manifest.lookup(doc_ref.source_type, doc_ref.source_id)
                version = row["version"] if row else 1
                self.harvest_logger.log_harvested(
                    run_id,
                    source_type=doc_ref.source_type,
                    source_id=doc_ref.source_id,
                    title=doc_ref.title,
                    version=version,
                    action=action,
                    bytes=len(raw.content),
                )

                # WS5 — write-back (only on new/updated docs, opt-in)
                if self.write_back.enabled:
                    try:
                        ts = datetime.now(timezone.utc).isoformat()
                        await self.plugin.mark_harvested(
                            doc_ref.source_id,
                            ts,
                            self.write_back.property_name,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Write-back failed for {doc_ref.source_id!r}: {e}"
                        )

            except Exception as e:
                result.failed += 1
                status = "failed"
                error_msg = f"{doc_ref.source_id}: {e}"
                result.errors.append(error_msg)
                logger.error(f"Failed to fetch {doc_ref.source_id!r}: {e}")
                self.harvest_logger.log_failed(
                    run_id,
                    source_type=doc_ref.source_type,
                    source_id=doc_ref.source_id,
                    title=doc_ref.title,
                    error=str(e),
                )
            finally:
                # Fold this doc's content-drops into the run aggregate. The
                # fold + reset are synchronous (no await between them and the
                # task's other result mutations), so concurrent fetch tasks
                # don't interleave on ``result.warnings``.
                for kind, _detail in take_extraction_warnings():
                    result.warnings[kind] = result.warnings.get(kind, 0) + 1
                reset_extraction_capture(warn_token)
                if progress is not None:
                    await progress.tick(doc_ref.title, status)

    # ── Out-of-band single-doc reharvest ───────────────────────────

    async def harvest_one(
        self,
        doc_ref: DocRef,
        *,
        force_full: bool = True,
    ) -> dict:
        """Fetch + persist a single document outside any run.

        Used by the per-doc reharvest API endpoint. Does **not** create a
        ``harvest_runs`` row, does **not** emit SSE log events, does
        **not** acquire the orchestrator's run-scoped semaphore. Errors
        propagate to the caller.

        Returns a dict with the post-upsert manifest row + the action
        (``new`` / ``updated`` / ``unchanged``) so the caller can report
        what happened.

        ``force_full`` defaults to ``True`` because that's the user's
        intent when they hit "Reharvest" — bypass Layer 1's resume
        short-circuit and re-fetch.
        """
        if not force_full and not _is_unreliable_modified_at(doc_ref):
            existing = self.manifest.lookup(doc_ref.source_type, doc_ref.source_id)
            if existing and _doc_already_harvested(doc_ref, existing):
                return {"action": "unchanged", "row": existing}

        raw: RawDocument = await self.plugin.fetch_document(doc_ref)

        normalized: NormalizedDocument | None
        try:
            normalized = self.plugin.normalize(raw)
        except NotImplementedError:
            normalized = None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Normalization failed for %s/%s: %s — raw is preserved",
                doc_ref.source_type, doc_ref.source_id, e,
            )
            normalized = None

        content_hash = sha256_hash(raw.content)

        merged_meta: dict = {}
        if doc_ref.metadata:
            merged_meta.update(doc_ref.metadata)
        if raw.metadata:
            merged_meta.update(raw.metadata)
        doc_ref_meta = _jsonable(merged_meta) if merged_meta else None
        origin_scope_id = (merged_meta or {}).get("origin_scope_id")

        doc_id, action = self.manifest.upsert_document(
            source_type=doc_ref.source_type,
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            source_url=doc_ref.source_url,
            content_hash=content_hash,
            source_modified=doc_ref.modified_at,
            raw_format=raw.format,
            converter_version=(
                self.raw_store.converter_version if self.raw_store else None
            ),
            metadata=doc_ref_meta,
            origin_scope_id=origin_scope_id,
        )

        if action != "unchanged":
            if self.raw_store is not None:
                written = self.raw_store.write(
                    doc_ref.source_type, doc_ref.source_id, raw
                )
                self.manifest.set_raw_path(
                    doc_ref.source_type,
                    doc_ref.source_id,
                    written.as_posix(),
                    raw_bytes=len(raw.content),
                )
            if self.normalized_store is not None and normalized is not None:
                norm_written = self.normalized_store.write(
                    doc_ref.source_type, normalized
                )
                self.manifest.set_normalized_path(
                    doc_ref.source_type,
                    doc_ref.source_id,
                    norm_written.as_posix(),
                    normalizer_version=normalized.normalizer_version,
                    normalized_bytes=len(normalized.markdown.encode("utf-8")),
                )

        row = self.manifest.lookup(doc_ref.source_type, doc_ref.source_id)
        return {"action": action, "row": row}
