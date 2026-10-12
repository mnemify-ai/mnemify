"""Offline Notion and Confluence sources for the sample workspace.

The sample corpus (its ``notion/`` and ``confluence/`` folders) is plain markdown
with YAML frontmatter. These plugins present it to the REAL harvester
(``HarvestOrchestrator``) as if it came from a Notion workspace and a
Confluence site, so the manifest, raw/normalized stores, harvest log, document
API and compiler all see genuine ``notion`` / ``confluence`` documents with the
same metadata keys the live plugins write (see ``harvester/notion/plugin.py``
and ``harvester/confluence/plugin.py``).

Nothing here talks to the network. URLs use the reserved .example TLD.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class CorpusDoc:
    path: Path
    meta: dict
    body: str  # markdown without frontmatter


def read_corpus_doc(path: Path) -> CorpusDoc:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise TypeError(f"{path}: frontmatter is not a mapping")
    for key in ("title", "author", "created", "updated"):
        if not meta.get(key):
            raise ValueError(f"{path}: frontmatter missing {key!r}")
    return CorpusDoc(path=path, meta=meta, body=text[m.end():].lstrip("\n"))


def as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def stamp(value, salt: str, *, edited: bool = False) -> datetime:
    """A plausible working-hours timestamp on the given day (UTC), stable per
    doc. Creation lands in the morning and edits in the afternoon (Pacific),
    so a doc created and last edited on the same day still reads in order."""
    d = as_date(value)
    h = int(hashlib.sha1(salt.encode()).hexdigest()[:6], 16)
    start = (20 if edited else 15) * 60  # 15:00 / 20:00 UTC ≈ 8am / 1pm Pacific
    minutes = start + (h % (4 * 60))
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(minutes=minutes)


def stable_hex(*parts: str, n: int = 32) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:n]


def slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")


def corpus_files(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_dir():
            out.extend(sorted(p for p in root.rglob("*.md") if not p.name.startswith(".")))
    return out


class _FixturePlugin(SourcePlugin):
    SOURCE_TYPE = ""

    def __init__(self, roots: list[Path]):
        self.roots = roots
        self._docs: dict[str, tuple[CorpusDoc, DocRef]] = {}

    async def test_connection(self) -> HealthStatus:
        n = len(corpus_files(self.roots))
        return HealthStatus(
            healthy=n > 0,
            source_type=self.SOURCE_TYPE,
            message=f"sample corpus: {n} documents",
        )

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        doc, _ = self._docs[doc_ref.source_id]
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=doc.body.encode("utf-8"),
            format="md",
            metadata={},
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:  # pragma: no cover
        raise NotImplementedError("sample corpus has no attachments")

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=raw.content.decode("utf-8"),
            frontmatter={},
            normalizer_version="sample-0.1.0",
        )

    def _common_meta(self, doc: CorpusDoc) -> dict:
        created = stamp(doc.meta["created"], f"c:{doc.path.name}")
        author = str(doc.meta["author"])
        return {
            "document_type": "page",
            # Live plugins store created_at; "created" too, which older
            # compilers read for Note.createdAt.
            "created_at": created.isoformat(),
            "created": created.isoformat(),
            "last_modified_by": str(doc.meta.get("last_modified_by") or author),
        }


class FixtureNotion(_FixturePlugin):
    """Two-level page tree: ``<Root>/_index.md`` is a top-level page, every
    sibling ``<Root>/<Title>.md`` is its child page."""

    SOURCE_TYPE = "notion"

    def _page_id(self, doc: CorpusDoc) -> str:
        h = stable_hex("notion", str(doc.path.parent.name), str(doc.meta["title"]))
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        docs = [read_corpus_doc(p) for p in corpus_files(self.roots)]
        root_ids: dict[str, tuple[str, str]] = {}
        for d in docs:
            if d.path.name == "_index.md":
                root_ids[d.path.parent.name] = (self._page_id(d), str(d.meta["title"]))
        refs: list[DocRef] = []
        for d in docs:
            pid = self._page_id(d)
            title = str(d.meta["title"])
            meta = self._common_meta(d)
            meta["created_by"] = str(d.meta["author"])
            if d.path.name == "_index.md":
                meta.update({"parent_type": "workspace", "parent_id": None})
            else:
                parent = root_ids.get(d.path.parent.name)
                if parent is None:
                    raise ValueError(f"{d.path}: no _index.md for parent {d.path.parent.name!r}")
                meta.update({"parent_type": "page_id", "parent_id": parent[0], "parent_title": parent[1]})
            modified = stamp(d.meta["updated"], f"u:{d.path.name}", edited=True)
            ref = DocRef(
                source_id=pid,
                title=title,
                source_type=self.SOURCE_TYPE,
                source_url=f"https://stencil.notion.example/{slug(title)}-{pid.replace('-', '')}",
                modified_at=modified,
                metadata=meta,
            )
            self._docs[pid] = (d, ref)
            refs.append(ref)
        return refs


class FixtureConfluence(_FixturePlugin):
    """``<SPACE>/<Title>.md`` → a page in that space."""

    SOURCE_TYPE = "confluence"

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        refs: list[DocRef] = []
        for path in corpus_files(self.roots):
            d = read_corpus_doc(path)
            title = str(d.meta["title"])
            space = str(d.meta.get("space") or path.parent.name).upper()
            page_id = str(10_000_000 + int(stable_hex("confluence", space, title, n=8), 16) % 89_999_999)
            url = f"https://stencil.atlassian.example/wiki/spaces/{space}/pages/{page_id}/{slug(title)}"
            created = stamp(d.meta["created"], f"c:{path.name}")
            modified = stamp(d.meta["updated"], f"u:{path.name}", edited=True)
            meta = self._common_meta(d)
            meta.update(
                {
                    "url": url,
                    "space_key": space,
                    "author_name": str(d.meta["author"]),
                    "updated_at": modified.isoformat(),
                    "labels": [str(x) for x in (d.meta.get("labels") or [])],
                    "version_number": 1 + max(0, (modified - created).days // 9),
                }
            )
            ref = DocRef(
                source_id=page_id,
                title=title,
                source_type=self.SOURCE_TYPE,
                source_url=url,
                modified_at=modified,
                metadata=meta,
            )
            self._docs[page_id] = (d, ref)
            refs.append(ref)
        return refs
