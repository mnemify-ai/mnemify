"""Raw content store — atomic writes to the local filesystem.

Manages a sharded directory tree rooted at a configurable path:

    {root}/{source_type}/{source_id[:2]}/{source_id}.{ext}

Two-char shard directory prevents 10k-files-per-dir pain for large workspaces.

Atomic writes use a sibling tmp file + os.replace so readers never see
partial content.

Attachments land under the parent document's shard directory:

    {root}/{source_type}/{parent[:2]}/{parent}/attachments/{hash}{ext}
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from src.harvester import RawDocument

logger = logging.getLogger(__name__)

# Extension map for known formats
_EXT_MAP: dict[str, str] = {
    "json": ".json",
    "md": ".md",
    "xml": ".xml",
    "html": ".html",
}


def _extension(fmt: str) -> str:
    return _EXT_MAP.get(fmt.lower(), ".bin")


class RawStore:
    """Atomic filesystem store for harvested raw content and attachments."""

    def __init__(self, root: Path, converter_version: str = "0.1.0"):
        self.root = Path(root)
        self.converter_version = converter_version
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Path computation ───────────────────────────────────────────

    def path_for(self, source_type: str, source_id: str, fmt: str) -> Path:
        """Return the canonical path for a document without touching the filesystem."""
        shard = source_id[:2]
        ext = _extension(fmt)
        return self.root / source_type / shard / f"{source_id}{ext}"

    # ── Document write ─────────────────────────────────────────────

    def write(self, source_type: str, source_id: str, raw: RawDocument) -> Path:
        """Atomically write raw content to disk.

        Returns the path that was written.
        Raises OSError on I/O failure — caller should catch and treat as failed.
        """
        target = self.path_for(source_type, source_id, raw.format)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, raw.content)
        logger.debug(f"Raw stored: {target} ({len(raw.content)} bytes)")
        return target

    # ── Attachment write ───────────────────────────────────────────

    def write_attachment(
        self,
        source_type: str,
        parent_source_id: str,
        attachment_bytes: bytes,
        filename: str,
    ) -> Path:
        """Atomically write attachment bytes to disk.

        Layout: {root}/{source_type}/{parent[:2]}/{parent}/attachments/{hash}{ext}

        Returns the path that was written.
        """
        content_hash = hashlib.sha256(attachment_bytes).hexdigest()[:16]
        ext = _infer_ext(filename)
        shard = parent_source_id[:2]
        att_dir = self.root / source_type / shard / parent_source_id / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        target = att_dir / f"{content_hash}{ext}"

        # Skip re-writing if file already present with same hash name
        if target.exists():
            logger.debug(f"Attachment already exists: {target}")
            return target

        _atomic_write(target, attachment_bytes)
        logger.debug(f"Attachment stored: {target} ({len(attachment_bytes)} bytes)")
        return target

    # ── Deletion ───────────────────────────────────────────────────

    def delete(self, source_type: str, source_id: str) -> None:
        """Delete all raw files for a source_id (no-op if missing).

        Removes the document file and the attachments sub-directory.
        Used by the purge command.
        """
        shard = source_id[:2]
        shard_dir = self.root / source_type / shard

        # Remove all format variants (we only write one, but be defensive)
        for ext in _EXT_MAP.values():
            candidate = shard_dir / f"{source_id}{ext}"
            if candidate.exists():
                try:
                    candidate.unlink()
                    logger.debug(f"Deleted raw file: {candidate}")
                except OSError as e:
                    logger.warning(f"Could not delete {candidate}: {e}")

        # Remove attachments sub-directory
        att_dir = shard_dir / source_id / "attachments"
        if att_dir.exists():
            try:
                import shutil

                shutil.rmtree(str(att_dir))
                logger.debug(f"Deleted attachments dir: {att_dir}")
            except OSError as e:
                logger.warning(f"Could not delete {att_dir}: {e}")


# ── Internal helpers ────────────────────────────────────────────────


def _atomic_write(target: Path, data: bytes) -> None:
    """Write bytes to target atomically using a sibling tmp file + os.replace."""
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _infer_ext(filename: str) -> str:
    """Derive file extension from a filename, defaulting to .bin."""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
        # Sanity-check: only accept simple alphanumeric extensions
        if ext[1:].isalnum():
            return ext
    return ".bin"
