"""Harvest the sample corpus into a scratch Mnemify home.

    MNEMIFY_HOME=/tmp/mnemify-sample uv run --project backend \\
        python scripts/sample-data/seed.py [--late]

* Obsidian and local notes go through the real ``obsidian`` / ``localfiles``
  harvesters (copied into ``$MNEMIFY_HOME/src``; file mtimes set from each
  note's frontmatter ``updated`` date, since those plugins date docs by mtime).
* Notion and Confluence go through the real ``HarvestOrchestrator`` with the
  offline fixture plugins in ``fixture_plugin.py``.
* ``--late`` adds the corpus's ``late/`` on top and harvests again WITHOUT the
  deletion pass. Run it after the compile so "what changed since the last
  compile" has something to show.

Refuses any home sample_guard.py doesn't accept: it must be explicit, new or
empty on first use, and never the repo's ``backend/.mnemify`` or Mnemify's
default home (both hold real data).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "backend"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from sample_guard import corpus_dir, scratch_home


def write_yaml(home: Path, vault: Path, notes: Path) -> None:
    import yaml

    cfg = {
        "server": {"idle_timeout_minutes": 0},
        "sources": {
            "obsidian": {"enabled": True, "vault_path": str(vault)},
            "localfiles": {"enabled": True, "roots": [{"path": str(notes)}]},
        },
    }
    (home / "mnemify.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def copy_tree(src: Path, dst: Path) -> list[Path]:
    """Copy markdown files, then date each by its frontmatter `updated`."""
    from fixture_plugin import read_corpus_doc, stamp

    copied: list[Path] = []
    for path in sorted(src.rglob("*.md")):
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        doc = read_corpus_doc(path)
        ts = stamp(doc.meta["updated"], f"u:{path.name}", edited=True).timestamp()
        os.utime(target, (ts, ts))
        copied.append(target)
    return copied


async def harvest(home: Path, *, late: bool) -> None:
    from fixture_plugin import FixtureConfluence, FixtureNotion

    from src import paths
    from src.harvester.logger import HarvestLogger
    from src.harvester.manifest import HarvestManifest
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.orchestrator import HarvestOrchestrator
    from src.harvester.raw_store import RawStore
    from src.harvester.registry import create_plugin

    data_dir = paths.data_dir()
    assert home in data_dir.parents, f"data dir {data_dir} escaped {home}"
    paths.ensure_home()
    manifest = HarvestManifest(data_dir / "harvest-manifest.db")
    logger = HarvestLogger(data_dir / "harvest-log.jsonl")
    raw_store = RawStore(data_dir / "raw")
    normalized_store = NormalizedStore(data_dir / "normalized")

    vault = home / "src" / "Maya"
    notes = home / "src" / "Notes"

    corpus = corpus_dir()

    def roots(name: str) -> list[Path]:
        out = [corpus / name]
        if late:
            out.append(corpus / "late" / name)
        return out

    plugins = [
        ("notion", FixtureNotion(roots("notion")), None),
        ("confluence", FixtureConfluence(roots("confluence")), None),
        ("obsidian", *create_plugin("obsidian", {"vault_path": str(vault)})),
        ("localfiles", *create_plugin("localfiles", {"roots": [{"path": str(notes)}]})),
    ]
    try:
        for source_type, plugin, client in plugins:
            orchestrator = HarvestOrchestrator(
                plugin=plugin,
                manifest=manifest,
                harvest_logger=logger,
                raw_store=raw_store,
                normalized_store=normalized_store,
                max_concurrent=8,
                # The late pass only ADDS documents; never let it retire any.
                skip_mark_deleted=late,
            )
            result = await orchestrator.run(source_type=source_type, mode="manual")
            print(f"[{source_type}] {result.summary()}")
            if result.failed:
                sys.exit(f"{source_type}: {result.failed} documents failed to harvest")
            await plugin.aclose()
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()
    finally:
        manifest.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--late", action="store_true", help="add the corpus's late/ docs and harvest again (after compile)")
    args = ap.parse_args()

    # The main seed initialises a new, empty home; --late only reuses one.
    home = scratch_home(create=not args.late)
    vault = home / "src" / "Maya"
    notes = home / "src" / "Notes"
    if not args.late:
        for d in (vault, notes):
            if d.exists():
                shutil.rmtree(d)
    corpus = corpus_dir()
    copy_tree(corpus / "obsidian" / "Maya", vault)
    copy_tree(corpus / "notes", notes)
    if args.late:
        copy_tree(corpus / "late" / "obsidian" / "Maya", vault)
        copy_tree(corpus / "late" / "notes", notes)
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    write_yaml(home, vault, notes)

    started = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"Seeding {home} ({'late batch' if args.late else 'main corpus'}) at {started}")
    asyncio.run(harvest(home, late=args.late))


if __name__ == "__main__":
    main()
