"""Mnemify CLI — harvest, compile, inspect, and manage content.

Commands:
  harvest   Run a full harvest for a source (default: notion)
  compile   Compile harvested raw content into the knowledge graph (Tier 1)
  status    Show manifest stats and recent run history
  inspect   Print metadata and content for a specific document by source_id
  debug     Connection test + document listing + sample fetch for any source
  purge     Delete raw files for docs marked deleted_at_source

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
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(".mnemify")


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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = HarvestManifest(DATA_DIR / "harvest-manifest.db")
    harvest_logger = HarvestLogger(DATA_DIR / "harvest-log.jsonl")

    raw_root_str = file_cfg.get("raw_root", str(DATA_DIR / "raw"))
    converter_version = file_cfg.get("converter_version", "0.1.0")
    raw_root_path = (
        Path(raw_root_str)
        if Path(raw_root_str).is_absolute()
        else Path.cwd() / raw_root_str
    )
    raw_store = RawStore(raw_root_path, converter_version=converter_version)

    normalized_root_str = file_cfg.get("normalized_root", str(DATA_DIR / "normalized"))
    normalized_root_path = (
        Path(normalized_root_str)
        if Path(normalized_root_str).is_absolute()
        else Path.cwd() / normalized_root_str
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

    db_path = DATA_DIR / "harvest-manifest.db"
    if not db_path.exists():
        if getattr(args, "json_output", False):
            print(json.dumps({"error": "No manifest found"}))
        else:
            print("No manifest found. Run 'harvest' first.")
        return

    manifest = HarvestManifest(db_path)
    stats = manifest.stats()

    if getattr(args, "json_output", False):
        print(json.dumps(stats, indent=2, default=str))
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

    log_path = DATA_DIR / "harvest-log.jsonl"
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

    db_path = DATA_DIR / "harvest-manifest.db"
    if not db_path.exists():
        print("No harvest manifest found. Run 'harvest' first.")
        sys.exit(1)

    compiler = TerrainCompiler(
        data_dir=DATA_DIR,
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

    db_path = DATA_DIR / "harvest-manifest.db"
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

    db_path = DATA_DIR / "harvest-manifest.db"
    if not db_path.exists():
        print("No harvest manifest found. Run 'harvest' first.")
        sys.exit(1)

    manifest = HarvestManifest(db_path)

    normalized_root_str = file_cfg.get("normalized_root", str(DATA_DIR / "normalized"))
    normalized_root_path = (
        Path(normalized_root_str)
        if Path(normalized_root_str).is_absolute()
        else Path.cwd() / normalized_root_str
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

    db_path = DATA_DIR / "harvest-manifest.db"
    if not db_path.exists():
        print("No manifest found. Nothing to purge.")
        return

    manifest = HarvestManifest(db_path)
    raw_root = DATA_DIR / "raw"
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

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            ext = raw.format if raw.format else "bin"
            content_path = DATA_DIR / f"debug_sample.{ext}"
            md_path = DATA_DIR / "debug_sample.md"

            content_path.write_bytes(raw.content)
            print(f"   Saved raw   : {content_path}")
            if normalized is not None:
                md_path.write_text(normalized.markdown, encoding="utf-8")
                print(f"   Saved md    : {md_path}")

            # 4. Fetch attachments (using only the ABC method)
            if raw.attachments:
                print(f"\n4. Fetching {len(raw.attachments)} attachment(s)...")
                att_dir = DATA_DIR / "debug_attachments"
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


def _cmd_up(args: argparse.Namespace) -> None:
    import uvicorn
    import webbrowser

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    print(f"\n  Mnemify up on {url}\n")
    uvicorn.run(
        "src.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def _cmd_reset(args: argparse.Namespace) -> None:
    """Complete wipe of harvested data + source configs + (optionally) creds."""
    import shutil

    data_dir = DATA_DIR
    yaml_path = Path("mnemify.yaml")
    env_path = Path(".env")

    # What exactly will be destroyed.
    victims: list[tuple[str, str]] = []
    if data_dir.exists():
        try:
            size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
            victims.append((f"harvest data at {data_dir}/", f"{size / 1_048_576:.1f} MB"))
        except Exception:  # noqa: BLE001
            victims.append((f"harvest data at {data_dir}/", "size unknown"))
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
    if data_dir.exists():
        try:
            shutil.rmtree(data_dir)
            print(f"  ✓ removed {data_dir}/")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ could not remove {data_dir}/: {e}")

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


def _cmd_login(args: argparse.Namespace) -> None:
    """Run the one-time OAuth consent flow for a Google source.

    Opens the user's browser via a localhost-loopback redirect, walks them
    through Google's consent screen for the source's read-only scope, and
    caches the resulting refresh token (mode 0600) for every subsequent
    harvest to use silently.
    """
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
    if args.command == "reset":
        _cmd_reset(args)
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
    except EnvironmentError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
