"""Obsidian source plugin — implements SourcePlugin for the harvest orchestrator.

Reads an Obsidian vault from the local filesystem directly (no running
Obsidian required).  Every ``.md`` file in the vault becomes a ``DocRef``;
content is stored byte-for-byte in markdown format.

Source ID strategy: SHA-256 of the vault-relative POSIX path, truncated to
16 hex characters.  Renames produce new IDs; the orchestrator's deletion
detection handles the old ID.

Usage::

    config = ObsidianVaultConfig(vault_path="/path/to/vault")
    plugin = ObsidianHarvesterPlugin(config)

    health = await plugin.test_connection()
    docs   = await plugin.list_documents()
    raw    = await plugin.fetch_document(docs[0])
    text   = plugin.extract_plain_text(raw)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from .models import ObsidianVaultConfig
from .parser import NoteParser
from .scanner import VaultScanner

logger = logging.getLogger(__name__)


def note_id(vault_path: Path, file_path: Path) -> str:
    """Deterministic 16-char hex ID derived from the vault-relative file path.

    64 bits of SHA-256 gives practically zero collision risk across a
    personal vault.  Using the relative path (not the absolute path) ensures
    the ID is portable if the vault is moved.
    """
    relative = file_path.relative_to(vault_path).as_posix()
    return hashlib.sha256(relative.encode()).hexdigest()[:16]


class ObsidianHarvesterPlugin(SourcePlugin):
    """Obsidian implementation of the SourcePlugin interface.

    Reads a local Obsidian vault directory.  No network calls, no running
    Obsidian process required.
    """

    SOURCE_TYPE = "obsidian"

    def __init__(self, config: ObsidianVaultConfig) -> None:
        self.config = config
        self.vault_path = Path(config.vault_path).expanduser().resolve()
        self.scanner = VaultScanner(self.vault_path, config)
        self.parser = NoteParser()

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Verify the vault directory exists, is readable, and looks like an
        Obsidian vault (has a ``.obsidian/`` sub-folder)."""
        if not self.vault_path.exists():
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Vault not found: {self.vault_path}",
            )
        if not self.vault_path.is_dir():
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Vault path is not a directory: {self.vault_path}",
            )
        if not (self.vault_path / ".obsidian").is_dir():
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"No .obsidian/ folder found in {self.vault_path} — "
                    "is this an Obsidian vault?"
                ),
            )

        # Count notes as a sanity check (don't use the full scanner here —
        # we want a raw file count, not a filtered one)
        try:
            md_count = sum(
                1
                for f in self.vault_path.rglob("*.md")
                if not f.is_symlink()
            )
        except OSError:
            md_count = 0

        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"Vault OK: {md_count} markdown files in {self.vault_path.name}",
            details={
                "vault_path": str(self.vault_path),
                "note_count": md_count,
            },
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """Walk the vault and return a DocRef for each markdown file.

        ``since`` is accepted for interface compatibility but ignored. The
        local filesystem has no API cost, and a mtime-based pre-filter would
        drop notes that just came into scope (new watch_folder containing
        long-untouched notes) before the orchestrator's per-doc Layer 1
        short-circuit could see them. Per-doc dedup happens upstream.

        The frontmatter is peeked (fast read) to populate title and tags in
        the DocRef metadata.
        """
        logger.debug(
            f"ObsidianHarvesterPlugin.list_documents: starting scan of "
            f"{self.vault_path.name}"
        )
        results: list[DocRef] = []
        for md_file in self.scanner.scan():
            try:
                stat = md_file.stat()
            except OSError as e:
                logger.warning(f"Could not stat {md_file}: {e}")
                continue

            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            title, metadata = self.parser.peek_frontmatter(md_file)
            logger.debug(
                f"ObsidianHarvesterPlugin: listed {md_file.relative_to(self.vault_path).as_posix()!r} "
                f"title={title!r} modified={modified_at.date()}"
            )

            try:
                relative_path = md_file.relative_to(self.vault_path).as_posix()
            except ValueError:
                logger.warning(f"File outside vault root, skipping: {md_file}")
                continue

            folder = str(md_file.parent.relative_to(self.vault_path))
            # Normalise vault root folder to empty string
            if folder == ".":
                folder = ""

            source_id = note_id(self.vault_path, md_file)

            # Scope-aware deletion (Option B): the origin is the longest
            # configured watch_folder whose prefix matches this file's
            # folder. When watch_folders is empty (= harvest the entire
            # vault), origin is the empty string — the implicit "whole
            # vault" scope, which is always in config.
            origin_scope_id = ""
            watch_folders = self.config.watch_folders or []
            if watch_folders:
                # Match by prefix; longest first so a nested watch_folder
                # wins over its parent.
                normalised_folder = folder.replace("\\", "/")
                best: str | None = None
                for wf in sorted(watch_folders, key=len, reverse=True):
                    wf_norm = wf.replace("\\", "/").rstrip("/")
                    if not wf_norm:
                        continue
                    if normalised_folder == wf_norm or normalised_folder.startswith(
                        wf_norm + "/"
                    ):
                        best = wf
                        break
                if best is not None:
                    origin_scope_id = best

            results.append(
                DocRef(
                    source_id=source_id,
                    title=title or md_file.stem,
                    source_type=self.SOURCE_TYPE,
                    source_url=(
                        f"obsidian://open?vault={self.vault_path.name}"
                        f"&file={relative_path}"
                    ),
                    modified_at=modified_at,
                    metadata={
                        "document_type": "note",
                        "relative_path": relative_path,
                        "folder": folder,
                        "tags": metadata.get("tags", []),
                        "original_frontmatter": metadata,
                        "size_bytes": stat.st_size,
                        "origin_scope_id": origin_scope_id,
                    },
                )
            )

        logger.debug(
            f"ObsidianHarvesterPlugin.list_documents: {len(results)} notes "
            f"returned from {self.vault_path.name}"
        )
        return results

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Read the markdown file from disk and discover embedded attachments.

        Content is stored byte-for-byte in markdown format — no wrapping in
        JSON, no metadata injection.  The user's frontmatter, wikilinks,
        Dataview blocks, and Templater syntax are all preserved exactly.
        """
        relative_path: str = doc_ref.metadata["relative_path"]
        file_path = self.vault_path / relative_path
        logger.debug(f"ObsidianHarvesterPlugin.fetch_document: reading {relative_path!r}")

        try:
            content = file_path.read_bytes()
        except OSError as e:
            raise RuntimeError(
                f"Could not read vault file {file_path}: {e}"
            ) from e

        # Discover embedded attachments
        text_content = content.decode("utf-8", errors="replace")
        attachments = self.parser.find_attachments(
            text_content,
            self.vault_path,
            file_path.parent,
        )

        logger.debug(
            f"ObsidianHarvesterPlugin.fetch_document: {relative_path!r} "
            f"{len(content)} bytes, {len(attachments)} attachments"
        )
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=content,
            format="md",
            metadata={
                "document_type": "note",
                "relative_path": relative_path,
                "vault_name": self.vault_path.name,
            },
            attachments=attachments,
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Read an attachment from the local filesystem.

        ``att_ref.url`` is a local absolute path for Obsidian attachments
        (not a web URL).
        """
        att_path = Path(att_ref.url)
        logger.debug(f"ObsidianHarvesterPlugin.fetch_attachment: reading {att_path.name}")
        try:
            data = att_path.read_bytes()
            logger.debug(
                f"ObsidianHarvesterPlugin.fetch_attachment: {att_path.name} "
                f"{len(data)} bytes"
            )
            return data
        except OSError as e:
            raise RuntimeError(
                f"Could not read attachment {att_path}: {e}"
            ) from e

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Byte-passthrough — Obsidian raw content is already the desired markdown.

        Stamped with ``"0.1.0-passthrough"`` so the manifest clearly
        distinguishes "this source emits markdown directly" from "this
        source was converted by a normalizer."
        """
        md = raw.content.decode("utf-8", errors="replace")
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=md,
            frontmatter={},
            normalizer_version="0.1.0-passthrough",
        )
