"""Backfill ``container`` metadata for already-harvested Notion data sources.

Background
----------
Notion API ≥ 2025-09-03 returns ``data_source`` objects from ``/search`` and
hides the wrapping ``database`` container.  Without container metadata, the
breadcrumb walker can't bridge from a data source to the page that actually
owns it (because the container itself is never harvested).  The plugin now
fetches and stashes container info at list time, so any *new* harvest run
populates this naturally.

This script applies the same fetch to *existing* manifest rows so users with
data harvested before the fix don't have to re-harvest everything.  It only
touches the metadata column — no raw content is re-downloaded.

Usage
-----
    cd backend
    python -m scripts.backfill_notion_containers

Reads the Notion token from the standard config (``mnemify.yaml`` →
``NOTION_TOKEN`` env var).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from src.config import load_config
from src.config_file import get_source_config, load_config_file
from src.harvester.manifest import HarvestManifest
from src.harvester.notion.client import NotionClient
from src.harvester.notion.plugin import NotionHarvesterPlugin

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill")

DATA_DIR = Path(".mnemify")


async def main() -> int:
    manifest_path = DATA_DIR / "harvest-manifest.db"
    if not manifest_path.exists():
        logger.error("No manifest at %s — run a harvest first.", manifest_path)
        return 1

    # ``load_config`` pulls .env into the process env so $NOTION_TOKEN is
    # available even when this script is invoked outside the CLI harness.
    load_config()
    cfg = load_config_file()
    try:
        notion_cfg = get_source_config(cfg, "notion")
    except Exception as exc:  # noqa: BLE001
        logger.error("Notion not configured in mnemify.yaml: %s", exc)
        return 1

    token_env = notion_cfg.get("token_env") or "NOTION_TOKEN"
    token = os.environ.get(token_env) or notion_cfg.get("token")
    if not token:
        logger.error(
            "Notion token missing — set $%s in the shell that launches this script.",
            token_env,
        )
        return 1

    m = HarvestManifest(manifest_path)
    data_sources: list[dict] = []
    container_ids: set[str] = set()
    for row in m.get_documents(source_type="notion"):
        md = row.get("metadata") or {}
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:  # noqa: BLE001
                continue
        if md.get("document_type") != "database":
            continue
        if md.get("parent_type") != "database_id":
            continue
        if md.get("container"):
            continue  # already backfilled
        cid = md.get("parent_id")
        if not cid or cid == "workspace":
            continue
        data_sources.append({"row": row, "metadata": md, "container_id": cid})
        container_ids.add(cid)

    if not data_sources:
        logger.info("Nothing to backfill — all data sources already have container info.")
        return 0

    logger.info(
        "Resolving %d unique database containers for %d data sources …",
        len(container_ids),
        len(data_sources),
    )

    async with NotionClient(token=token) as client:
        plugin = NotionHarvesterPlugin(client)
        containers: dict[str, dict] = {}
        sorted_ids = sorted(container_ids)
        results = await asyncio.gather(
            *(plugin._fetch_container_metadata(cid) for cid in sorted_ids),
            return_exceptions=False,
        )
        for cid, info in zip(sorted_ids, results):
            if info is not None:
                containers[cid] = info

    if not containers:
        logger.error("No containers resolved — Notion may have rejected the token.")
        return 1

    updated = 0
    skipped = 0
    for entry in data_sources:
        info = containers.get(entry["container_id"])
        if info is None:
            skipped += 1
            continue
        new_meta = {**entry["metadata"], "container": info}
        m.update_metadata("notion", entry["row"]["source_id"], new_meta)
        updated += 1

    logger.info(
        "Backfill complete: %d updated, %d skipped (container fetch failed).",
        updated,
        skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
