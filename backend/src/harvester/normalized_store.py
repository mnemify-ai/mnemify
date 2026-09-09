"""Normalized content store — atomic writes of the post-normalization markdown sidecar.

Mirrors :mod:`src.harvester.raw_store` layout so raw and normalized artifacts
live in parallel trees:

    {raw_root}/{source_type}/{source_id[:2]}/{source_id}.{ext}
    {normalized_root}/{source_type}/{source_id[:2]}/{source_id}.md

Only ``.md`` is written — normalization always produces markdown.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.harvester import NormalizedDocument
from src.harvester.raw_store import _atomic_write

logger = logging.getLogger(__name__)


class NormalizedStore:
    """Atomic filesystem store for post-normalization markdown."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, source_type: str, source_id: str) -> Path:
        """Return the canonical path for a normalized document (no filesystem touch)."""
        shard = source_id[:2]
        return self.root / source_type / shard / f"{source_id}.md"

    def write(self, source_type: str, normalized: NormalizedDocument) -> Path:
        """Atomically write the normalized markdown to disk.

        Raises OSError on I/O failure — caller should log and continue
        (raw is always preserved, so a normalization failure is recoverable
        via ``mnemify normalize --force``).
        """
        target = self.path_for(source_type, normalized.source_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, normalized.markdown.encode("utf-8"))
        logger.debug(
            "Normalized stored: %s (%d chars, normalizer=%s)",
            target, len(normalized.markdown), normalized.normalizer_version,
        )
        return target

    def delete(self, source_type: str, source_id: str) -> None:
        """Delete the normalized artifact (no-op if missing)."""
        target = self.path_for(source_type, source_id)
        if target.exists():
            try:
                target.unlink()
                logger.debug("Deleted normalized file: %s", target)
            except OSError as e:
                logger.warning("Could not delete %s: %s", target, e)
