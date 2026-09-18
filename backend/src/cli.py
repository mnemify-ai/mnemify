"""Mnemify CLI — harvest, compile, inspect, and manage content.

Commands:
  harvest   Run a full harvest for a source (default: notion)
  compile   Compile harvested raw content into the knowledge graph (Tier 1)
  status    Show manifest stats and recent run history
  inspect   Print metadata and content for a specific document by source_id
  debug     Connection test + document listing + sample fetch for any source
  purge     Delete raw files for docs marked deleted_at_source
  up        Start the web app (API + built UI) on localhost
  stop      Stop the running server
  migrate-home
            Move a legacy backend/ state layout into the platform app-data home

Usage:
  python -m src harvest --source notion
  python -m src harvest --source obsidian
  python -m src compile
  python -m src compile --source obsidian --dry-run
  python -m src status
  python -m src inspect <source_id> --source obsidian
  python -m src debug --source notion
  python -m src debug --source obsidian
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from src import paths

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party + per-block loggers in the default run.
    # Users who want the raw HTTP trace can pass `-v`.
    if not verbose:
        for name in (
            "httpx",
            "httpcore",
            "urllib3",
            "src.harvester.notion.pages",
            "src.harvester.notion.comments",
            "src.harvester.notion.client",
            "src.harvester.confluence.client",
            "src.harvester.jira.client",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)


def _make_plugin(source_type: str, source_cfg: dict):
    """Instantiate a plugin via the registry.

    Returns ``(plugin, closeable_or_None)``.  The caller must close the
    second element in a ``finally`` block when it is not ``None``.
    """
    from src.harvester.registry import create_plugin

    return create_plugin(source_type, source_cfg)


# ── Commands ───────────────────────────────────────────────────────


async def _cmd_harvest(args: argparse.Namespace) -> None:
    from src.config import load_config
    from src.config_file import load_config_file
    from src.harvester.logger import HarvestLogger
    from src.harvester.manifest import HarvestManifest
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    # Load .env and YAML config
    load_config()
    file_cfg = load_config_file(getattr(args, "config", None))

    # Shared resources across all sources in this invocation.
    paths.ensure_home()
    data_dir = paths.data_dir()
    manifest = HarvestManifest(data_dir / "harvest-manifest.db")
    harvest_logger = HarvestLogger(data_dir / "harvest-log.jsonl")

    # YAML path settings are anchored to the Mnemify home, never the cwd, so
    # `raw_root: .mnemify/raw` means the same tree wherever you run from.
    raw_root_cfg = file_cfg.get("raw_root")
    converter_version = file_cfg.get("converter_version", "0.1.0")
    raw_root_path = (
        paths.resolve_under_data_dir(raw_root_cfg) if raw_root_cfg else data_dir / "raw"
    )
    raw_store = RawStore(raw_root_path, converter_version=converter_version)

    normalized_root_cfg = file_cfg.get("normalized_root")
    normalized_root_path = (
        paths.resolve_under_data_dir(normalized_root_cfg)
        if normalized_root_cfg
        else data_dir / "normalized"
    )
    normalized_store = NormalizedStore(normalized_root_path)

    # Pick which source(s) to run.
    #   --source X  → single source (back-compat)
    #   omitted     → every source with `enabled: true` in the yaml
    explicit_source: str | None = getattr(args, "source", None)
    if explicit_source:
        sources_to_run = [explicit_source]
    else:
        sources_block = file_cfg.get("sources", {}) or {}
        sources_to_run = [
            name for name, cfg in sources_block.items()
            if isinstance(cfg, dict) and cfg.get("enabled", False)
        ]
        if not sources_to_run:
            print(
                "No sources to harvest. Either pass --source, or enable at least "
                "one source in mnemify.yaml under `sources:`."
            )
            return
        logger.info(
            f"Multi-source run: {', '.join(sources_to_run)} "
            f"(from mnemify.yaml `sources.*.enabled: true`)"
        )

    results = []
    for src in sources_to_run:
        if len(sources_to_run) > 1:
            print(f"\n=== {src} ===")
        result = await _harvest_one_source(
            src,
            file_cfg=file_cfg,
            manifest=manifest,
            harvest_logger=harvest_logger,
            raw_store=raw_store,
            normalized_store=normalized_store,
            args=args,
        )
        if result is not None:
            results.append((src, result))
            print(result.summary())

    if len(results) > 1:
        total_h = sum(r.harvested for _, r in results)
        total_s = sum(r.skipped for _, r in results)
        total_f = sum(r.failed for _, r in results)
        total_dur = sum(r.duration_sec for _, r in results)
        print(
            f"\n=== all sources ===\n"
            f"  sources={len(results)} "
            f"harvested={total_h} skipped={total_s} failed={total_f} "
            f"duration={total_dur:.1f}s"
        )


async def _harvest_one_source(
    source_type: str,
    *,
    file_cfg: dict,
    manifest,
    harvest_logger,
    raw_store,
    normalized_store,
    args: argparse.Namespace,
):
    """Run a single-source harvest. Returns HarvestResult or None on setup error."""
    from src.config_file import get_source_config
    from src.harvester.orchestrator import HarvestOrchestrator, WriteBackConfig

    source_cfg = get_source_config(file_cfg, source_type)

    # Notion: ensure the token is resolved from env into source_cfg before plugin build.
    if source_type == "notion" and "token" not in source_cfg:
        import os
        token_env = source_cfg.get("token_env", "NOTION_TOKEN")
        source_cfg = dict(source_cfg)  # copy before mutating
        source_cfg["token"] = os.getenv(token_env, "")

    try:
        plugin, client = _make_plugin(source_type, source_cfg)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not build plugin for {source_type!r}: {e}")
        return None

    # Write-back (Notion-only today; harmless no-op otherwise)
    wb_cfg = source_cfg.get("write_back", {})
    write_back = WriteBackConfig(
        enabled=wb_cfg.get("enabled", False),
        property_name=wb_cfg.get("property", "Harvested At"),
    )

    if getattr(args, "below_converter_version", None):
        rows = manifest.get_documents_by_converter_version(
            source_type, args.below_converter_version
        )
        logger.info(
            f"--below-converter-version: {len(rows)} docs have converter_version < "
            f"{args.below_converter_version}. Use --force-full to re-harvest all."
        )

    # Concurrency resolution: CLI flag > yaml `concurrency` > default 5.
    # The CLI parser leaves --concurrency as None when unspecified so the
    # yaml value can win; without that, the argparse default masks yaml.
    cli_concurrency = getattr(args, "concurrency", None)
    concurrency = cli_concurrency or source_cfg.get("concurrency", 5)

    orchestrator = HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=harvest_logger,
        max_concurrent=concurrency,
        raw_store=raw_store,
        normalized_store=normalized_store,
        write_back=write_back,
        dry_run=getattr(args, "dry_run", False),
        force_full=getattr(args, "force_full", False),
    )

    try:
        return await orchestrator.run(source_type=source_type, mode=args.mode)
    finally:
        await plugin.aclose()
        if client is not None:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                await client.close()


async def _cmd_status(args: argparse.Namespace) -> None:
    from src.harvester.manifest import HarvestManifest

    info = paths.describe()
    json_output = getattr(args, "json_output", False)
    if not json_output:
        print(f"Layout   : {info['layout']}")
        print(f"Home     : {info['home']}")
        print(f"Data dir : {info['data_dir']}")
        print()

    db_path = paths.data_dir() / "harvest-manifest.db"
    if not db_path.exists():
        if json_output:
            print(json.dumps({"error": "No manifest found", "paths": info}))
        else:
            print("No manifest found. Run 'harvest' first.")
        return

    manifest = HarvestManifest(db_path)
    stats = manifest.stats()

    if json_output:
        print(json.dumps({**stats, "paths": info}, indent=2, default=str))
        return

    print(f"Total documents : {stats['total_documents']}")
    print(f"Total runs      : {stats['total_runs']}")
    print()
    if stats["by_source"]:
        print("By source:")
        for row in stats["by_source"]:
            print(f"  [{row['source_type']}] {row['harvest_status']}: {row['n']}")
    else:
        print("No documents harvested yet.")

    log_path = paths.data_dir() / "harvest-log.jsonl"
    if log_path.exists():
        from src.harvester.logger import HarvestLogger

        harvest_logger = HarvestLogger(log_path)
        recent = harvest_logger.read_log(limit=10)
        if recent:
            print()
            print("Recent activity (last 10 entries):")
            for entry in recent:
                ts = entry.get("ts", "")[:19]
                action = entry.get("action", "")
                title = entry.get("title", entry.get("run", ""))
                print(f"  {ts}  {action:<25}  {title}")


async def _cmd_terrain(args: argparse.Namespace) -> None:
    from src.config import load_config
    from src.terrain import TerrainCompiler

    load_config()
    action = getattr(args, "terrain_command", None)
    if action == "schema":
        _cmd_terrain_schema(args)
        return
    if action != "build":
        print("Usage: python -m src terrain build | python -m src terrain schema --out PATH")
        return

    db_path = paths.data_dir() / "harvest-manifest.db"
    if not db_path.exists():
        print("No harvest manifest found. Run 'harvest' first.")
        sys.exit(1)

    compiler = TerrainCompiler(
        data_dir=paths.data_dir(),
        ai_mode=getattr(args, "ai_mode", "openai"),
        llm_model=getattr(args, "llm_model", "gpt-5.6-luna"),
        embedding_model=getattr(args, "embedding_model", "text-embedding-3-large"),
    )
    try:
        result = compiler.build(source=getattr(args, "source", None))
        print("Terrain build complete")
        print(f"  run:           {result.run_id}")
        print(f"  terrain.json:  {result.terrain_path}")
        print(f"  mocknotes:     {result.notes_path}")
        print(f"  render-data:   {result.render_data_path}")
        print(
            f"  regions: {result.stats.regions}  tags: {result.stats.tagsTotal}  "
            f"notes: {result.stats.notes}  edges: {result.stats.edges}"
        )
    finally:
        compiler.store.close()


def _cmd_terrain_schema(args: argparse.Namespace) -> None:
    """Export the v2 KnowledgeMap Pydantic schema as JSON Schema."""
    import json as _json

    from src.terrain.models import KnowledgeMap, KnowledgeMapNotes

    out_path = Path(getattr(args, "out", None) or "brain-map.schema.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Mnemify Knowledge Map v2",
        "description": "Schema for terrain.json (and the companion mocknotes.json).",
        "oneOf": [
            KnowledgeMap.model_json_schema(by_alias=True),
            KnowledgeMapNotes.model_json_schema(by_alias=True),
        ],
    }
    out_path.write_text(_json.dumps(schema, indent=2), encoding="utf-8")
    print(f"Wrote v2 brain-map JSON Schema → {out_path}")


async def _cmd_inspect(args: argparse.Namespace) -> None:
    from src.harvester.manifest import HarvestManifest

    db_path = paths.data_dir() / "harvest-manifest.db"
    if not db_path.exists():
        print("No manifest found. Run 'harvest' first.")
        return

    manifest = HarvestManifest(db_path)
    row = manifest.lookup(getattr(args, "source", "notion"), args.source_id)
    if not row:
        print(f"Document {args.source_id!r} not found in manifest.")
        return

    print(json.dumps(row, indent=2, default=str))

    if getattr(args, "content", False) and row.get("raw_path"):
        raw_file = Path(row["raw_path"])
        if raw_file.exists():
            print()
            print(f"--- Content: {raw_file} ---")
            print(raw_file.read_text(encoding="utf-8", errors="replace"))
        else:
            print(f"\n[raw_path recorded but file not found: {raw_file}]")


async def _cmd_normalize(args: argparse.Namespace) -> None:
    """Convert existing harvested raw content into normalized markdown sidecars.

    Reconstructs a ``RawDocument`` from each manifest row's on-disk raw file
    and calls ``plugin.normalize()`` for the corresponding source. Writes to
    ``{normalized_root}/{source_type}/{shard}/{source_id}.md`` atomically and
    updates the manifest's ``normalized_path`` / ``normalizer_version`` columns.

    Sources whose plugin raises ``NotImplementedError`` (Notion) are skipped
    — the compiler reader's legacy path handles them.
    """
    import os

    from src.config import load_config
    from src.config_file import get_source_config, load_config_file
    from src.harvester import RawDocument
    from src.harvester.manifest import HarvestManifest
    from src.harvester.normalized_store import NormalizedStore

    load_config()
    file_cfg = load_config_file(getattr(args, "config", None))

    db_path = paths.data_dir() / "harvest-manifest.db"
    if not db_path.exists():
        print("No harvest manifest found. Run 'harvest' first.")
        sys.exit(1)

    manifest = HarvestManifest(db_path)

    normalized_root_cfg = file_cfg.get("normalized_root")
    normalized_root_path = (
        paths.resolve_under_data_dir(normalized_root_cfg)
        if normalized_root_cfg
        else paths.data_dir() / "normalized"
    )
    normalized_store = NormalizedStore(normalized_root_path)

    source_filter = getattr(args, "source", None)
    force = getattr(args, "force", False)
    below_version = getattr(args, "below_version", None)
    dry_run = getattr(args, "dry_run", False)

    # Decide candidate row set.
    if below_version:
        rows = manifest.get_documents_by_normalizer_version(source_filter, below_version)
    else:
        rows = manifest.get_documents(source_type=source_filter, status="active")

    # Group rows by source so we instantiate each plugin once.
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source_type"], []).append(row)

    totals = {"candidates": len(rows), "written": 0, "skipped": 0, "failed": 0, "notimpl": 0}

    try:
        for source_type, source_rows in by_source.items():
            source_cfg = get_source_config(file_cfg, source_type)
            if source_type == "notion" and "token" not in source_cfg:
                token_env = source_cfg.get("token_env", "NOTION_TOKEN")
                source_cfg = dict(source_cfg)
                source_cfg["token"] = os.getenv(token_env, "")

            try:
                plugin, client = _make_plugin(source_type, source_cfg)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Could not build plugin for {source_type!r}: {e}")
                totals["failed"] += len(source_rows)
                continue

            try:
                for row in source_rows:
                    source_id = row["source_id"]
                    raw_path_str = row.get("raw_path")
                    if not raw_path_str:
                        totals["skipped"] += 1
                        continue
                    raw_path = Path(raw_path_str)
                    if not raw_path.exists():
                        logger.warning(
                            f"Raw missing for {source_type}/{source_id} at {raw_path} — skipping"
                        )
                        totals["skipped"] += 1
                        continue
                    if (
                        not force
                        and not below_version
                        and row.get("normalized_path")
                        and Path(row["normalized_path"]).exists()
                    ):
                        totals["skipped"] += 1
                        continue

                    if dry_run:
                        print(f"[dry-run] would normalize {source_type}/{source_id}")
                        continue

                    try:
                        raw_bytes = raw_path.read_bytes()
                    except OSError as e:
                        logger.warning(f"Could not read {raw_path}: {e}")
                        totals["failed"] += 1
                        continue

                    metadata = json.loads(row.get("metadata") or "{}")
                    raw = RawDocument(
                        source_id=source_id,
                        title=row.get("title") or "",
                        content=raw_bytes,
                        format=row.get("raw_format") or "",
                        metadata=metadata,
                    )
                    try:
                        normalized = plugin.normalize(raw)
                    except NotImplementedError:
                        totals["notimpl"] += 1
                        continue
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            f"normalize() failed for {source_type}/{source_id}: {e}"
                        )
                        totals["failed"] += 1
                        continue

                    try:
                        written = normalized_store.write(source_type, normalized)
                        manifest.set_normalized_path(
                            source_type,
                            source_id,
                            str(written),
                            normalizer_version=normalized.normalizer_version,
                        )
                        totals["written"] += 1
                    except OSError as e:
                        logger.warning(f"Write failed for {source_type}/{source_id}: {e}")
                        totals["failed"] += 1
            finally:
                await plugin.aclose()
                if client is not None:
                    if hasattr(client, "aclose"):
                        await client.aclose()
                    elif hasattr(client, "close"):
                        await client.close()

        print(
            f"Normalize complete: candidates={totals['candidates']} "
            f"written={totals['written']} skipped={totals['skipped']} "
            f"notimpl={totals['notimpl']} failed={totals['failed']}"
        )
        if not dry_run:
            print(f"Output: {normalized_root_path}")
    finally:
        manifest.close()


async def _cmd_purge(args: argparse.Namespace) -> None:
    """Delete raw files and manifest rows for documents deleted at source."""
    from datetime import timedelta

    from src.harvester.manifest import HarvestManifest
    from src.harvester.raw_store import RawStore

    db_path = paths.data_dir() / "harvest-manifest.db"
    if not db_path.exists():
        print("No manifest found. Nothing to purge.")
        return

    manifest = HarvestManifest(db_path)
    raw_root = paths.data_dir() / "raw"
    raw_store = RawStore(raw_root, converter_version="0.1.0")

    older_than_days = getattr(args, "older_than_days", 0)
    dry_run = getattr(args, "dry_run", False)
    source = getattr(args, "source", None) or "notion"

    deleted_rows = manifest.get_documents(source_type=source, status="deleted_at_source")

    cutoff = None
    if older_than_days > 0:
        from datetime import datetime, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    purged = 0
    for row in deleted_rows:
        if cutoff:
            harvested_at_str = row.get("harvested_at", "")
            try:
                from datetime import datetime
                harvested_at = datetime.fromisoformat(
                    harvested_at_str.replace("Z", "+00:00")
                )
                if harvested_at > cutoff:
                    continue
            except (ValueError, AttributeError):
                pass

        if dry_run:
            print(f"[dry-run] Would purge: {row['source_id']!r} ({row['title']!r})")
        else:
            raw_store.delete(source, row["source_id"])
            with manifest._transaction():
                manifest._conn.execute(
                    "DELETE FROM documents WHERE source_type = ? AND source_id = ?",
                    (source, row["source_id"]),
                )
            print(f"Purged: {row['source_id']!r} ({row['title']!r})")
        purged += 1

    suffix = " (dry run)" if dry_run else ""
    print(f"\nTotal purged{suffix}: {purged}")


async def _cmd_debug(args: argparse.Namespace) -> None:
    """Connection test, document listing, and sample fetch for any source.

    Routes through the plugin registry so any registered source type works
    without changes here.  Uses only the SourcePlugin ABC methods.
    """
    import os

    from src.config import load_config
    from src.config_file import get_source_config, load_config_file

    source_type: str = getattr(args, "source", "notion")

    load_config()
    file_cfg = load_config_file(getattr(args, "config", None))
    source_cfg = get_source_config(file_cfg, source_type)

    # For Notion, resolve the token from env so the factory can find it
    if source_type == "notion" and "token" not in source_cfg:
        token_env = source_cfg.get("token_env", "NOTION_TOKEN")
        source_cfg = dict(source_cfg)
        source_cfg["token"] = os.getenv(token_env, "")

    plugin, client = _make_plugin(source_type, source_cfg)

    try:
        # 1. Connection test
        print(f"Source: {source_type}")
        print("\n1. Testing connection...")
        health = await plugin.test_connection()
        if health.healthy:
            print(f"   OK — {health.message}")
            if health.details:
                for k, v in health.details.items():
                    print(f"   {k}: {v}")
        else:
            print(f"   FAILED — {health.message}")
            return

        # 2. List documents (first 20)
        print("\n2. Listing documents (first 20)...")
        docs = await plugin.list_documents()
        sample = docs[:20]
        for i, doc in enumerate(sample, 1):
            modified = doc.modified_at.strftime("%Y-%m-%d") if doc.modified_at else "unknown"
            doc_type = doc.metadata.get("document_type", "doc")
            print(
                f"   {i:2}. [{modified}] [{doc_type}] {doc.title!r} "
                f"({doc.source_id[:8]}...)"
            )
        if len(docs) > 20:
            print(f"   ... and {len(docs) - 20} more")
        print(f"   Total: {len(docs)} documents")

        # 3. Fetch one document
        if docs:
            first = docs[0]
            print(f"\n3. Fetching sample document: {first.title!r}...")
            raw = await plugin.fetch_document(first)
            normalized = None
            try:
                normalized = plugin.normalize(raw)
            except (NotImplementedError, Exception) as e:  # noqa: BLE001
                print(f"   normalize() failed: {e}")
            print(f"   Format      : {raw.format}")
            print(f"   Content size: {len(raw.content)} bytes")
            if normalized is not None:
                print(f"   Markdown    : {len(normalized.markdown)} chars")
            print(f"   Attachments : {len(raw.attachments)}")

            if raw.metadata:
                print("   Metadata:")
                for k, v in raw.metadata.items():
                    print(f"     {k}: {v}")

            paths.ensure_home()
            data_dir = paths.data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            ext = raw.format if raw.format else "bin"
            content_path = data_dir / f"debug_sample.{ext}"
            md_path = data_dir / "debug_sample.md"

            content_path.write_bytes(raw.content)
            print(f"   Saved raw   : {content_path}")
            if normalized is not None:
                md_path.write_text(normalized.markdown, encoding="utf-8")
                print(f"   Saved md    : {md_path}")

            # 4. Fetch attachments (using only the ABC method)
            if raw.attachments:
                print(f"\n4. Fetching {len(raw.attachments)} attachment(s)...")
                att_dir = data_dir / "debug_attachments"
                att_dir.mkdir(parents=True, exist_ok=True)
                fetched = 0
                for att in raw.attachments:
                    try:
                        att_bytes = await plugin.fetch_attachment(att)
                        out_path = att_dir / att.filename
                        out_path.write_bytes(att_bytes)
                        print(f"   Fetched: {att.filename} ({len(att_bytes)} bytes)")
                        fetched += 1
                    except Exception as e:  # noqa: BLE001
                        print(f"   Failed : {att.filename} — {e}")
                print(f"   Fetched {fetched}/{len(raw.attachments)} attachments to {att_dir}")
            else:
                print("\n4. No attachments on sample document.")
        else:
            print("\n3. No documents available to fetch.")

    finally:
        await plugin.aclose()
        if client is not None:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                await client.close()


# ── Argument parser ────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mnemify",
        description="Mnemify — harvest your tools, compile a brain-map, serve it.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    # harvest
    harvest_p = subparsers.add_parser("harvest", help="Run a full harvest")
    harvest_p.add_argument(
        "--source",
        default=None,
        help=(
            "Source type (notion | obsidian | confluence | jira | gmail | calendar | slack | github). "
            "Omit to harvest every source with `enabled: true` in mnemify.yaml."
        ),
    )
    harvest_p.add_argument(
        "--mode", default="scheduled", help="Run mode: scheduled | on_demand"
    )
    harvest_p.add_argument(
        "--concurrency", type=int, default=None,
        help="Max concurrent fetches. Overrides yaml `concurrency`. "
             "Falls back to yaml then 5 if unset."
    )
    harvest_p.add_argument(
        "--config", metavar="PATH",
        help="Path to mnemify.yaml config file"
    )
    harvest_p.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="List and filter documents but skip fetching and writing"
    )
    harvest_p.add_argument(
        "--force-full", action="store_true", dest="force_full",
        help="Ignore incremental since timestamp; re-harvest everything"
    )
    harvest_p.add_argument(
        "--below-converter-version", metavar="VERSION", dest="below_converter_version",
        help="Re-harvest documents with converter_version < VERSION"
    )

    # status
    status_p = subparsers.add_parser("status", help="Show manifest stats and recent activity")
    status_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output stats as JSON for scripting"
    )

    # inspect
    inspect_p = subparsers.add_parser("inspect", help="Print a document's manifest entry")
    inspect_p.add_argument("source_id", help="Document source_id (from manifest)")
    inspect_p.add_argument(
        "--content", action="store_true",
        help="Also print the raw file content"
    )
    inspect_p.add_argument(
        "--source", default="notion", help="Source type (default: notion)"
    )

    # purge
    purge_p = subparsers.add_parser(
        "purge",
        help="Delete raw files and manifest rows for docs deleted at source"
    )
    purge_p.add_argument(
        "--source", default="notion", help="Source type (default: notion)"
    )
    purge_p.add_argument(
        "--older-than-days", type=int, default=0, dest="older_than_days",
        help="Only purge docs deleted more than N days ago (0 = purge all)"
    )
    purge_p.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Show what would be purged without deleting"
    )

    # normalize
    normalize_p = subparsers.add_parser(
        "normalize",
        help="Convert harvested raw content into normalized markdown sidecars",
    )
    normalize_p.add_argument(
        "--source", default=None,
        help="Source filter (e.g. confluence, jira). Default: all sources.",
    )
    normalize_p.add_argument(
        "--force", action="store_true",
        help="Re-normalize every active document, ignoring existing normalized_path.",
    )
    normalize_p.add_argument(
        "--below-version", metavar="VERSION", dest="below_version",
        help="Re-normalize docs whose normalizer_version is NULL or < VERSION (lex).",
    )
    normalize_p.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Report what would be normalized without writing.",
    )
    normalize_p.add_argument(
        "--config", metavar="PATH",
        help="Path to mnemify.yaml config file",
    )

    # terrain
    terrain_p = subparsers.add_parser(
        "terrain",
        help="Build semantic terrain data from harvested documents",
    )
    terrain_sub = terrain_p.add_subparsers(dest="terrain_command", metavar="action")
    terrain_sub.required = True
    terrain_build_p = terrain_sub.add_parser(
        "build",
        help="Build the v2 brain-map + v3 render-data under .mnemify/",
    )
    terrain_build_p.add_argument(
        "--source",
        default=None,
        help="Optional source filter, e.g. notion or confluence",
    )
    terrain_build_p.add_argument(
        "--ai-mode",
        choices=["openai", "anthropic", "local", "claude"],
        default="openai",
        help=(
            "openai = OpenAI models; anthropic = Anthropic API (ANTHROPIC_API_KEY); "
            "local = deterministic offline clients; "
            "claude = generation on your Claude subscription via the `claude` CLI "
            "(embeddings always use OpenAI). Default: openai"
        ),
    )
    terrain_build_p.add_argument(
        "--llm-model",
        default="gpt-5.6-luna",
        help="OpenAI model for feature extraction and naming",
    )
    terrain_build_p.add_argument(
        "--embedding-model",
        default="text-embedding-3-large",
        help="OpenAI embedding model",
    )

    terrain_schema_p = terrain_sub.add_parser(
        "schema",
        help="Export the v2 brain-map JSON Schema",
    )
    terrain_schema_p.add_argument(
        "--out",
        default="brain-map.schema.json",
        help="Output path for the JSON Schema (default: ./brain-map.schema.json)",
    )

    # debug
    debug_p = subparsers.add_parser(
        "debug",
        help="Connection test + list documents + fetch one sample for any source",
    )
    debug_p.add_argument(
        "--source", default="notion", help="Source type (default: notion)"
    )
    debug_p.add_argument(
        "--config", metavar="PATH",
        help="Path to mnemify.yaml config file"
    )

    # up — serve the web UI + API on localhost
    up_p = subparsers.add_parser(
        "up",
        help="Start the Mnemify web app (FastAPI + built React UI).",
    )
    up_p.add_argument("--host", default="127.0.0.1")
    up_p.add_argument("--port", type=int, default=8783)
    up_p.add_argument(
        "--no-browser",
        action="store_true",
        dest="no_browser",
        help="Don't open a browser tab on start.",
    )
    up_p.add_argument(
        "--reload",
        action="store_true",
        help="Dev: reload the FastAPI app on code changes (requires uvicorn[standard]).",
    )

    # stop — ask a running server to quit (no signals; works on Windows)
    subparsers.add_parser(
        "stop",
        help="Stop the running Mnemify server (reads <home>/server.port).",
    )

    # reset — complete wipe: .mnemify/, Mnemify-owned secrets, yaml flags
    reset_p = subparsers.add_parser(
        "reset",
        help="Wipe every harvested doc, disable every source, and clear Mnemify-owned secrets.",
    )
    reset_p.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt. Use in scripts.",
    )
    reset_p.add_argument(
        "--keep-env",
        action="store_true",
        dest="keep_env",
        help="Leave .env credentials in place; only wipe harvested data + yaml flags.",
    )

    # migrate-home — legacy backend/ layout → platform app-data dir
    migrate_p = subparsers.add_parser(
        "migrate-home",
        help="Move a legacy backend/ state layout into the platform app-data home.",
    )
    migrate_p.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt. Use in scripts.",
    )

    # login — one-time OAuth consent flow for Google sources
    login_p = subparsers.add_parser(
        "login",
        help="Run the one-time OAuth consent flow for a Google source.",
    )
    login_p.add_argument(
        "--source",
        required=True,
        choices=["gmail", "calendar"],
        help="Which Google source to authorise.",
    )
    login_p.add_argument(
        "--token-path",
        dest="token_path",
        default=None,
        help="Override the cached-token path "
             "(default: ~/.mnemify/google/<source>-token.json).",
    )
    login_p.add_argument(
        "--credentials-path",
        dest="credentials_path",
        default=None,
        help="Override the OAuth client_secret JSON path "
             "(default: backend/src/harvester/_google/oauth_client.json).",
    )

    return parser


# ── Server lifecycle helpers (`up` / `stop`) ───────────────────────

#: How many consecutive ports `up` will try before giving up.
PORT_FALLBACK_TRIES = 11


def _loopback(host: str) -> str:
    """The address to *talk to* a server bound on ``host``."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def _read_runtime_files() -> tuple[int | None, int | None]:
    """``(pid, port)`` from ``<home>/server.pid`` + ``server.port``."""
    def _read_int(path) -> int | None:
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001 — missing, empty or garbage: same answer
            return None

    return _read_int(paths.server_pid_file()), _read_int(paths.server_port_file())


def _pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists (no signal is delivered)."""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes

        # PROCESS_QUERY_LIMITED_INFORMATION — the least we can ask for.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Someone else's pid — it exists, it just isn't ours to signal.
        return True
    return True


def _probe_health(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> dict | None:
    """``GET /api/health`` → the decoded body, or ``None`` if it didn't answer 200."""
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/health", timeout=timeout
        ) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — refused, timed out, not our server
        return None


#: How long ``_inspect_instance`` keeps re-probing ``/api/health`` while the
#: recorded pid is alive but not answering yet. ``server.pid`` is written
#: before uvicorn listens, so a freshly launched server has a window of a
#: second or two in which "alive pid, no health" is *starting*, not stale.
HEALTH_WAIT_S = 5.0
#: Pause between two health probes inside that window.
HEALTH_RETRY_INTERVAL_S = 0.25


@dataclass(frozen=True)
class InstanceState:
    """What ``server.pid`` + ``server.port`` say about the recorded process.

    ``status`` is ``"running"`` (pid alive, ``/api/health`` answered ``ok``)
    or ``"starting"`` (pid alive, health still silent after the wait window).
    A dead pid is not a state at all: ``_inspect_instance`` returns ``None``
    and the files are stale.
    """

    status: str
    pid: int
    port: int
    health: dict | None = None

    @property
    def running(self) -> bool:
        return self.status == "running"


def _inspect_instance(
    host: str = "127.0.0.1",
    *,
    wait: float | None = None,
    sleep=None,
    clock=None,
) -> InstanceState | None:
    """Classify the recorded server as running, starting, or gone (``None``).

    A live pid whose port does not answer is re-probed for up to ``wait``
    seconds (default :data:`HEALTH_WAIT_S`): a double-clicked icon or a
    ``mnemify stop`` issued right after ``up`` must not mistake a server that
    is still binding its socket for a crashed one and wipe its files — or
    start a second copy on top of it. If the pid dies during the wait the
    answer is ``None``; if it is still alive and still silent, ``"starting"``.
    """
    import time

    sleep = time.sleep if sleep is None else sleep
    clock = time.monotonic if clock is None else clock
    wait = HEALTH_WAIT_S if wait is None else wait

    pid, port = _read_runtime_files()
    if pid is None or port is None or not _pid_alive(pid):
        return None

    deadline = clock() + wait
    while True:
        health = _probe_health(port, host)
        if health and health.get("ok"):
            return InstanceState("running", pid, port, health)
        if clock() >= deadline:
            break
        sleep(HEALTH_RETRY_INTERVAL_S)
        if not _pid_alive(pid):
            return None
    if not _pid_alive(pid):
        return None
    return InstanceState("starting", pid, port, None)


def _live_instance(host: str = "127.0.0.1", **kw) -> tuple[int, dict] | None:
    """``(port, health)`` of the already-running Mnemify, or ``None``.

    "Running" means both halves agree: the recorded pid is alive *and* the
    recorded port answers a healthy ``/api/health`` (after the startup grace
    of :func:`_inspect_instance`). A server that is still *starting* is not
    "live" for callers that want to talk to it — use ``_inspect_instance``
    to tell it apart from stale files.
    """
    inst = _inspect_instance(host, **kw)
    if inst is None or not inst.running:
        return None
    return inst.port, inst.health or {}


def _terminate_pid(pid: int, *, wait: float = 3.0, sleep=None, clock=None) -> bool:
    """SIGTERM ``pid`` (TerminateProcess on Windows) and wait for it to exit."""
    import os
    import signal
    import time

    sleep = time.sleep if sleep is None else sleep
    clock = time.monotonic if clock is None else clock
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        logger.debug("could not signal pid %s", pid, exc_info=True)
        return False
    deadline = clock() + wait
    while _pid_alive(pid):
        if clock() >= deadline:
            return False
        sleep(0.1)
    return True


def _clear_runtime_files() -> None:
    for f in (paths.server_pid_file(), paths.server_port_file()):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def _claim_runtime_files(port: int):
    """Write ``server.pid`` + ``server.port``; return the matching remover.

    The remover unlinks only files that still name *this* process, so a second
    ``mnemify up`` that bows out (or an old atexit handler) can never delete
    the live instance's files.
    """
    import os

    paths.ensure_home()
    pid_file = paths.server_pid_file()
    port_file = paths.server_port_file()
    mypid = os.getpid()
    pid_file.write_text(f"{mypid}\n", encoding="utf-8")
    port_file.write_text(f"{port}\n", encoding="utf-8")

    def release() -> None:
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(mypid):
                pid_file.unlink(missing_ok=True)
                port_file.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove server.pid/server.port", exc_info=True)

    return release


def _bind_first_free_port(host: str, port: int, tries: int = PORT_FALLBACK_TRIES):
    """Bind ``host`` on the first free port from ``port``. Returns ``(sock, port)``.

    The socket is *kept* and handed to uvicorn (``Server.run(sockets=[sock])``)
    rather than closed and re-bound: that removes the window in which another
    process could take the port between our probe and uvicorn's bind, and
    guarantees ``server.port`` names the port that is actually listening.
    """
    import socket

    last_error: OSError | None = None
    for candidate in range(port, port + max(1, tries)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # POSIX SO_REUSEADDR only permits binding over lingering TIME_WAIT
        # sockets — never over a live listener — so single-instance detection
        # is unaffected and `stop` + immediate restart keeps its port. On
        # Windows the same flag *does* allow stealing a live port, so: never.
        if not sys.platform.startswith("win"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, candidate))
            sock.listen(2048)
            sock.set_inheritable(True)
            return sock, candidate
        except OSError as e:
            last_error = e
            sock.close()
    raise RuntimeError(
        f"no free port in {port}–{port + tries - 1} on {host} ({last_error}). "
        f"Pass --port to pick another range."
    )


def _cmd_up(args: argparse.Namespace) -> None:
    import atexit
    import os

    import uvicorn

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        # The app refuses any request whose Host header is not loopback (DNS
        # rebinding guard in src/api). Bound elsewhere, the browser's Host is
        # this machine's LAN name or address, which only the user knows.
        allowed = os.environ.get("MNEMIFY_ALLOWED_HOSTS", "")
        print(
            f"\n  --host {args.host}: requests must carry a Host header in "
            f"MNEMIFY_ALLOWED_HOSTS (currently {allowed!r}) or they get 403. "
            f"Set it to the name or address you will open in the browser.\n",
            flush=True,
        )

    if args.reload:
        # Dev path only. The reloader supervises a child process, so it needs
        # the import string (an app object can't cross the fork) — and with it
        # there is no Server object to register for `stop`, no pid/port files
        # and no port fallback. MNEMIFY_DEV=1 enables the Vite CORS allowance.
        os.environ["MNEMIFY_DEV"] = "1"
        url = f"http://{args.host}:{args.port}"
        if not args.no_browser:
            _open_browser(url)
        print(f"\n  Mnemify up on {url} (reload)\n", flush=True)
        uvicorn.run(
            "src.api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            log_level="info",
        )
        return

    # ── Single instance ────────────────────────────────────────────
    loopback = _loopback(args.host)
    inst = _inspect_instance(loopback)
    if inst is not None:
        url = f"http://{loopback}:{inst.port}"
        if inst.running:
            print(f"\n  Mnemify is already running at {url}\n", flush=True)
            if not args.no_browser:
                _open_browser(url)
        else:
            # A live pid that has not started listening yet: it is ours (a
            # double-clicked icon, most likely). Leave its files alone.
            print(
                f"\n  Mnemify is already starting (pid {inst.pid}) — "
                f"it will be at {url} in a moment.\n",
                flush=True,
            )
        sys.exit(0)
    # Files that survived a crash or a kill -9 — nobody is listening on them.
    if any(f.exists() for f in (paths.server_pid_file(), paths.server_port_file())):
        logger.info("clearing stale server.pid/server.port (no live server found)")
        _clear_runtime_files()

    # ── Port ───────────────────────────────────────────────────────
    sock, port = _bind_first_free_port(args.host, args.port)
    if port != args.port:
        print(f"  Port {args.port} is in use — using {port} instead.", flush=True)

    from src.api import create_app, lifecycle

    app = create_app()
    config = uvicorn.Config(app, host=args.host, port=port, log_level="info")
    server = uvicorn.Server(config)
    lifecycle.set_server(server)

    release = _claim_runtime_files(port)
    atexit.register(release)

    url = f"http://{loopback}:{port}"
    if not args.no_browser:
        _open_browser(url)
    print(f"\n  Mnemify up on {url}\n", flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        release()
        lifecycle.clear_server()
        try:
            sock.close()
        except OSError:
            pass


def _open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # headless box, no browser configured: not fatal
        logger.debug("could not open a browser for %s", url, exc_info=True)


def _cmd_stop(args: argparse.Namespace) -> None:
    """Ask a running server to quit, via the API (no signals — Windows works)."""
    import urllib.request

    inst = _inspect_instance()
    if inst is None:
        # Only a *dead* pid makes the files stale enough to remove.
        _clear_runtime_files()
        print("Mnemify is not running.")
        return

    if not inst.running:
        # Alive but not yet answering: it has no API to ask, so signal it.
        print(f"Mnemify (pid {inst.pid}) is still starting — stopping it.")
        if _terminate_pid(inst.pid):
            _clear_runtime_files()
            print(f"Mnemify (pid {inst.pid}) stopped.")
            return
        print(
            f"Could not stop pid {inst.pid}. It is still running; try `mnemify stop` again "
            "in a moment."
        )
        sys.exit(1)

    port = inst.port
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/system/shutdown",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-Mnemify-Client": "cli"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as e:  # noqa: BLE001
        print(f"Could not stop Mnemify on port {port}: {e}")
        sys.exit(1)
    if not body.get("ok"):
        print(f"Mnemify refused the shutdown request: {body}")
        sys.exit(1)
    print(f"Mnemify on port {port} is shutting down.")


def _cmd_reset(args: argparse.Namespace) -> None:
    """Complete wipe of harvested data + source configs + (optionally) creds."""
    import shutil

    dd = paths.data_dir()
    yaml_path = paths.yaml_file()
    env_path = paths.env_file()

    # What exactly will be destroyed.
    victims: list[tuple[str, str]] = []
    if dd.exists():
        try:
            size = sum(f.stat().st_size for f in dd.rglob("*") if f.is_file())
            victims.append((f"harvest data at {dd}/", f"{size / 1_048_576:.1f} MB"))
        except Exception:  # noqa: BLE001
            victims.append((f"harvest data at {dd}/", "size unknown"))
    if yaml_path.exists():
        victims.append((f"every sources.*.enabled flag in {yaml_path}", "flipped to false"))
    if not args.keep_env and env_path.exists():
        victims.append(
            (f"Mnemify-owned secrets in {env_path}",
             "NOTION_TOKEN, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, JIRA_EMAIL, JIRA_API_TOKEN")
        )

    if not victims:
        print("Already clean — nothing to remove.")
        return

    print("\nThis will remove:")
    for what, how in victims:
        print(f"  • {what}  ({how})")
    print(
        "\nUntouched: unrelated .env keys, yaml comments, "
        "and structure for any sources you have."
    )

    if not args.yes:
        reply = input("\nProceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted. Nothing changed.")
            return

    # 1. Harvested bytes + manifest + log.
    if dd.exists():
        try:
            shutil.rmtree(dd)
            print(f"  ✓ removed {dd}/")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ could not remove {dd}/: {e}")

    # 2. Disable every source in yaml (keeps structure + comments intact).
    if yaml_path.exists():
        try:
            from src.api.yaml_writer import disable_source, read_config

            cfg = read_config()
            for name in list((cfg.get("sources") or {}).keys()):
                disable_source(name)
            print(f"  ✓ disabled every source in {yaml_path}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ could not rewrite {yaml_path}: {e}")

    # 3. Credentials.
    if not args.keep_env:
        try:
            from src.api.credential_store import delete_secrets

            delete_secrets([
                "NOTION_TOKEN",
                "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN",
                "JIRA_EMAIL", "JIRA_API_TOKEN",
            ])
            print(f"  ✓ removed Mnemify-owned secrets from {env_path}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ could not clean {env_path}: {e}")

    print("\nMemory wiped. Ready when you are.")


def _migration_clashes(dest_dir: Path, names: list[str]) -> list[str]:
    """Names in ``names`` that already exist under ``dest_dir``."""
    return [name for name in names if (dest_dir / name).exists()]


def _rollback_migration(source_dir: Path, dest_dir: Path, moved: list[str]) -> None:
    """Move already-migrated items back, newest first. Reports, never raises."""
    import shutil

    for name in reversed(moved):
        try:
            shutil.move(str(dest_dir / name), str(source_dir / name))
            print(f"  ↩ moved {name} back")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ could not move {name} back: {e} — it is now in {dest_dir}")


def _cmd_migrate_home(args: argparse.Namespace) -> None:
    """Move a legacy ``backend/`` state layout into the platform app-data home.

    Only ever reads from ``paths.backend_dir()`` — the one place the legacy
    layout can live — so it does the same thing regardless of ``MNEMIFY_HOME``
    or the cwd. Refuses to merge into a destination that already holds any of
    the three items rather than guessing which copy wins.
    """
    import os
    import shutil

    # A server that is up (or still coming up) holds the manifest/terrain DBs
    # open and would keep writing into the old home mid-move.
    inst = _inspect_instance()
    if inst is not None:
        state = "running" if inst.running else "starting"
        print(f"Mnemify is {state} (pid {inst.pid}). Run `mnemify stop` first, then retry.")
        sys.exit(1)

    source_dir = paths.backend_dir()
    dest_dir = paths.platform_default()

    movable = [
        name for name in (".mnemify", "mnemify.yaml", ".env")
        if (source_dir / name).exists()
    ]
    if not movable:
        print(f"Nothing to migrate — no .mnemify/, mnemify.yaml or .env in {source_dir}.")
        return

    clashes = _migration_clashes(dest_dir, movable)
    if clashes:
        print(f"Refusing to migrate: {dest_dir} already holds {', '.join(clashes)}.")
        print("Move or remove those first — Mnemify will not merge two homes.")
        sys.exit(1)

    print(f"\nThis will move, from {source_dir}")
    print(f"                 to {dest_dir}:")
    for name in movable:
        print(f"  • {name}")
    if os.environ.get(paths.HOME_ENV):
        print(
            f"\nNote: {paths.HOME_ENV} is set in this environment — unset it for "
            "the new home to take effect."
        )

    if not args.yes:
        reply = input("\nProceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted. Nothing moved.")
            return

    # Re-check right before touching anything: the prompt may have sat open.
    problems = [f"{name} is gone from {source_dir}" for name in movable
                if not (source_dir / name).exists()]
    problems += [f"{dest_dir / name} now exists" for name in _migration_clashes(dest_dir, movable)]
    if problems:
        print("Refusing to migrate — the layout changed while waiting:")
        for problem in problems:
            print(f"  • {problem}")
        sys.exit(1)

    # ``paths._legacy_home`` treats *any* marker left in backend/ as "legacy",
    # so a half-done move would leave Mnemify reading one home and writing
    # another. Ordering cannot help with that; rolling back can.
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for name in movable:
        try:
            shutil.move(str(source_dir / name), str(dest_dir / name))
        except Exception as e:  # noqa: BLE001 — permissions, cross-device, locks…
            print(f"  ✗ could not move {name}: {e}")
            _rollback_migration(source_dir, dest_dir, moved)
            print("\nMigration aborted; the legacy layout was left as it was.")
            sys.exit(1)
        moved.append(name)
        print(f"  ✓ moved {name}")

    print("\nMnemify now reads and writes:")
    for key, value in paths.describe().items():
        print(f"  {key:10} {value}")


def _cmd_login(args: argparse.Namespace) -> None:
    """Run the one-time OAuth consent flow for a Google source.

    Opens the user's browser via a localhost-loopback redirect, walks them
    through Google's consent screen for the source's read-only scope, and
    caches the resulting refresh token (mode 0600) for every subsequent
    harvest to use silently.
    """
    # Gmail/Calendar are in the tree but out of this build's scope, and their
    # Google client libraries are an optional extra — so refuse *before* the
    # import, which would otherwise fail with a bare ModuleNotFoundError.
    try:
        from src.sources import is_enabled
    except ImportError:  # pragma: no cover — pre-`sources.py` checkouts
        is_enabled = None
    if is_enabled is not None and not is_enabled(args.source):
        print(
            "Gmail/Calendar are not enabled in this build.\n"
            "  Set MNEMIFY_SOURCES to re-enable them for development, e.g.\n"
            f"    MNEMIFY_SOURCES=notion,confluence,obsidian,{args.source} "
            f"mnemify login --source {args.source}\n"
            '  You will also need the Google client libraries: `uv sync --extra google`.'
        )
        sys.exit(1)

    default_token_paths = {
        "gmail": "~/.mnemify/google/gmail-token.json",
        "calendar": "~/.mnemify/google/calendar-token.json",
    }
    token_path = args.token_path or default_token_paths[args.source]

    if args.source == "gmail":
        from src.harvester.gmail.auth import run_consent_flow
    else:
        from src.harvester.calendar.auth import run_consent_flow

    print(
        f"\n  Opening browser for {args.source} consent…"
        f"\n  After you click Allow, the refresh token will be written to:"
        f"\n    {Path(token_path).expanduser()}\n"
    )
    run_consent_flow(token_path, client_secrets_path=args.credentials_path)
    print(f"  ✓ {args.source} authorised. You can now run `mnemify harvest --source {args.source}`.\n")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    command_map = {
        "harvest": _cmd_harvest,
        "normalize": _cmd_normalize,
        "terrain": _cmd_terrain,
        "status": _cmd_status,
        "inspect": _cmd_inspect,
        "purge": _cmd_purge,
        "debug": _cmd_debug,
    }

    if args.command == "up":
        # Sync command — uvicorn owns its own event loop.
        _cmd_up(args)
        return
    if args.command == "stop":
        # Sync command — one HTTP POST to the running server.
        _cmd_stop(args)
        return
    if args.command == "reset":
        _cmd_reset(args)
        return
    if args.command == "migrate-home":
        # Sync command — plain filesystem moves.
        _cmd_migrate_home(args)
        return
    if args.command == "login":
        # Sync command — google_auth_oauthlib runs its own local HTTP server.
        _cmd_login(args)
        return

    cmd_fn = command_map.get(args.command)
    if cmd_fn is None:
        parser.print_help()
        sys.exit(1)

    try:
        asyncio.run(cmd_fn(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except PermissionError as e:
        print(f"Permission denied: {e}")
        print(
            f"Mnemify is using {paths.describe()['home']} "
            f"(layout: {paths.layout()}).\n"
            f"Set {paths.HOME_ENV} to a directory you can write to, "
            f"or run `mnemify migrate-home`."
        )
        sys.exit(1)
    except EnvironmentError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
