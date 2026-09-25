"""Local files source plugin — implements SourcePlugin for the harvest orchestrator.

Reads any number of folders on this machine (``LocalRoot`` entries). Every
supported file (see ``scanner.SUPPORTED_EXTENSIONS``) becomes a ``DocRef``;
raw bytes are stored as-is and ``normalize`` turns them into markdown —
passthrough for ``.md`` / ``.txt``, ``pypdf`` text extraction for ``.pdf``.

This is the "I have folders of notes / exports / reports" connector. It is
deliberately a sibling of the Obsidian plugin rather than a mode of it: no
``.obsidian/`` marker, no wikilink or attachment handling, a wider set of
file types, and many roots under one source.

Source ID strategy: SHA-256 of ``<root key>::<root-relative POSIX path>``,
truncated to 16 hex characters. Renames produce new IDs and the
orchestrator's deletion detection retires the old one; the root key keeps
``a/notes.md`` in two different folders distinct.
"""

from __future__ import annotations

import hashlib
import logging
import re
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
from .extract import pdf_to_markdown
from .models import SCOPE_SEP, LocalFilesConfig, LocalRoot
from .scanner import FILE_SCOPE_PREFIX, FolderScanner, format_for

logger = logging.getLogger(__name__)

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TITLE_KEY = re.compile(r"^\s*title\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def file_id(root_key: str, relative_posix: str) -> str:
    """Deterministic 16-char hex ID from the root key + relative path."""
    return hashlib.sha256(f"{root_key}{SCOPE_SEP}{relative_posix}".encode()).hexdigest()[:16]


def _peek_title(path: Path) -> str | None:
    """Cheap title read for markdown: frontmatter ``title:``, else the first
    ``# Heading``. Only the first 8 KB is inspected."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    fm = _FRONTMATTER.match(head)
    if fm:
        m = _TITLE_KEY.search(fm.group(1))
        if m:
            return m.group(1).strip().strip("\"'") or None
        head = head[fm.end():]
    for line in head.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
        if stripped:
            break
    return None


def count_supported(root: Path) -> dict[str, int]:
    """Supported files under ``root`` by format (whole tree, default ignores)."""
    by_format: dict[str, int] = {}
    try:
        for path in FolderScanner(root, LocalRoot(path=str(root))).scan():
            fmt = format_for(path) or "other"
            by_format[fmt] = by_format.get(fmt, 0) + 1
    except OSError:
        pass
    return by_format


class LocalFilesHarvesterPlugin(SourcePlugin):
    """Folders-on-disk implementation of the SourcePlugin interface."""

    SOURCE_TYPE = "localfiles"

    def __init__(self, config: LocalFilesConfig) -> None:
        self.config = config
        # (resolved path, root) pairs; the resolved path is what every id uses.
        self.roots: list[tuple[Path, LocalRoot]] = [
            (Path(r.key), r) for r in config.roots if r.path
        ]

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        if not self.roots:
            return HealthStatus(
                healthy=False, source_type=self.SOURCE_TYPE, message="No folders linked yet",
            )
        missing = [str(p) for p, _ in self.roots if not p.is_dir()]
        if missing:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"Folder not found: {missing[0]}"
                    if len(missing) == 1
                    else f"{len(missing)} linked folders not found (first: {missing[0]})"
                ),
                details={"missing": missing},
            )

        per_root: list[dict] = []
        total = 0
        by_format_all: dict[str, int] = {}
        for p, _ in self.roots:
            by_format = count_supported(p)
            n = sum(by_format.values())
            total += n
            for k, v in by_format.items():
                by_format_all[k] = by_format_all.get(k, 0) + v
            per_root.append({"root_path": str(p), "file_count": n, "by_format": by_format})

        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=(
                f"Folder OK: {total} supported file(s) in {self.roots[0][0].name}"
                if len(self.roots) == 1
                else f"{len(self.roots)} folders OK: {total} supported file(s)"
            ),
            details={
                # Single-root callers (the validate route) read these directly.
                "root_path": str(self.roots[0][0]),
                "file_count": total,
                "by_format": by_format_all,
                "roots": per_root,
            },
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """One DocRef per supported file across every root. ``since`` is
        ignored — see the Obsidian plugin for why an mtime pre-filter would
        drop files that just came into scope."""
        results: list[DocRef] = []
        for root_path, root in self.roots:
            if not root_path.is_dir():
                logger.warning(f"LocalFilesHarvesterPlugin: linked folder missing, skipping: {root_path}")
                continue
            root_key = str(root_path)
            for path in FolderScanner(root_path, root).scan():
                try:
                    stat = path.stat()
                except OSError as e:
                    logger.warning(f"Could not stat {path}: {e}")
                    continue
                fmt = format_for(path)
                if fmt is None:
                    continue
                relative_path = path.relative_to(root_path).as_posix()
                folder = path.parent.relative_to(root_path).as_posix()
                if folder == ".":
                    folder = ""
                title = _peek_title(path) if fmt == "md" else None

                results.append(
                    DocRef(
                        source_id=file_id(root_key, relative_path),
                        title=title or path.stem,
                        source_type=self.SOURCE_TYPE,
                        source_url=path.as_uri(),
                        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        metadata={
                            "document_type": "file",
                            "root_path": root_key,
                            "root_name": root_path.name,
                            "relative_path": relative_path,
                            "folder": folder,
                            "extension": path.suffix.lower(),
                            "raw_format": fmt,
                            "size_bytes": stat.st_size,
                            "origin_scope_id": self._origin_scope(root, folder, relative_path),
                        },
                    )
                )
        logger.debug(f"LocalFilesHarvesterPlugin.list_documents: {len(results)} files from {len(self.roots)} root(s)")
        return results

    @staticmethod
    def _origin_scope(root: LocalRoot, folder: str, relative_path: str) -> str:
        """The flat scope id that brought this file in: ``<root>::file:<path>``
        when picked individually, else ``<root>::<longest containing folder>``,
        else the whole-root id ``<root>::``. Scope-aware deletion compares
        these against the ids YAML currently defines."""
        single = f"{FILE_SCOPE_PREFIX}{relative_path}"
        if single in root.watch_folders:
            return f"{root.key}{SCOPE_SEP}{single}"
        for wf in sorted(root.watch_folders, key=len, reverse=True):
            if wf.startswith(FILE_SCOPE_PREFIX):
                continue
            wf_norm = wf.replace("\\", "/").rstrip("/")
            if not wf_norm:
                continue
            if folder == wf_norm or folder.startswith(wf_norm + "/"):
                return f"{root.key}{SCOPE_SEP}{wf}"
        return f"{root.key}{SCOPE_SEP}"

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        relative_path: str = doc_ref.metadata["relative_path"]
        file_path = Path(doc_ref.metadata["root_path"]) / relative_path
        try:
            content = file_path.read_bytes()
        except OSError as e:
            raise RuntimeError(f"Could not read {file_path}: {e}") from e
        fmt = doc_ref.metadata.get("raw_format") or format_for(file_path) or "txt"
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=content,
            format=fmt,
            metadata={
                "document_type": "file",
                "relative_path": relative_path,
                "root_path": doc_ref.metadata["root_path"],
                "folder_name": Path(doc_ref.metadata["root_path"]).name,
            },
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Local files carry no attachments; kept for interface completeness."""
        try:
            return Path(att_ref.url).read_bytes()
        except OSError as e:
            raise RuntimeError(f"Could not read attachment {att_ref.url}: {e}") from e

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Markdown/text pass through; PDF is extracted with pypdf.

        A PDF without a text layer raises ``NoTextLayerError`` — the
        orchestrator logs it, leaves ``normalized_path`` NULL, and the
        compiler's reader skips the document rather than embedding nothing.
        """
        fmt = (raw.format or "").lower()
        label = raw.metadata.get("relative_path") or raw.title
        if fmt == "pdf":
            md = pdf_to_markdown(raw.content, label=label)
            version = "0.1.0-pypdf"
        else:
            md = raw.content.decode("utf-8", errors="replace")
            version = "0.1.0-passthrough"
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=md,
            frontmatter={},
            normalizer_version=version,
        )
