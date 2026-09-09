from __future__ import annotations

import re

from src.terrain.utils.models import SourceDocument, TerrainChunk
from src.utils.hashing import sha256_hash, short_hash

from langchain_text_splitters import (
    Language,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


# Bare URLs + markdown link targets `[text](url)`. The second alternative is
# strictly preferred (parenthesized link target wins over bare URL match)
# because the trailing `)` would otherwise leak into the captured URL.
_URL_PATTERN = re.compile(r"https?://[^\s)\]<>]+")
# Twitter/Slack-style @handles. Requires a leading non-word char so
# "abc@example.com" doesn't match. Two-char minimum dodges noise like
# "@a".
_MENTION_PATTERN = re.compile(r"(?<![\w])@([A-Za-z0-9_][A-Za-z0-9_.-]{1,})")
# Jira issue keys: PROJECT-1234. Capture the full key.
_JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")


def _ordered_union(*lists: list[str]) -> list[str]:
    """Concatenate lists, dropping duplicates while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for items in lists:
        for item in items:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


class MarkdownDefaultChunker:
    """Source-agnostic markdown chunker.

    Splits on markdown headings via LangChain, then merges sub-min chunks
    and shards over-max chunks. Per-source chunkers inherit from this and
    override only the steps that need source-specific behavior.
    """

    def __init__(self, min_words: int = 120, target_words: int = 900, max_words: int = 1400):
        self.min_words = min_words
        self.target_words = target_words
        self.max_words = max_words

    def chunk(self, documents: list[SourceDocument]) -> list[TerrainChunk]:
        chunks: list[TerrainChunk] = []
        for doc in documents:
            chunks.extend(self._chunks_for_doc(doc))
        return chunks

    def _chunks_for_doc(self, doc: SourceDocument) -> list[TerrainChunk]:
        content = self._preprocess(doc)
        sections = self._sections(content)
        chunks = [self._make_chunk(doc, path, text, i) for i, (path, text) in enumerate(sections)]
        chunks = self._merge_tiny(chunks)
        return self._split_large(chunks)

    def _preprocess(self, doc: SourceDocument) -> str:
        """Hook for per-source content transforms before sectioning."""
        return doc.content

    def _sections(self, markdown: str) -> list[tuple[list[str], str]]:
        sections = self._langchain_sections(markdown)
        if sections:
            return sections
        return self._fallback_sections(markdown)

    def _langchain_sections(self, markdown: str) -> list[tuple[list[str], str]]:
        headers = [(f"{'#' * level}", f"h{level}") for level in range(1, 7)]
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
        # ~6 chars/word; overlap is min_words worth of chars, clamped strictly
        # below chunk_size (langchain rejects overlap >= size).
        chunk_size = self.target_words * 6
        chunk_overlap = min(self.min_words, max(self.target_words - 1, 1)) * 6
        recursive_splitter = RecursiveCharacterTextSplitter.from_language(
            Language.MARKDOWN,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        header_docs = header_splitter.split_text(markdown)
        docs = recursive_splitter.split_documents(header_docs)
        return [
            (self._heading_path(d.metadata), d.page_content.strip())
            for d in docs
            if d.page_content.strip()
        ]

    def _heading_path(self, metadata: dict) -> list[str]:
        return [
            str(metadata[key])
            for key in ("h1", "h2", "h3", "h4", "h5", "h6")
            if metadata.get(key)
        ]

    def _fallback_sections(self, markdown: str) -> list[tuple[list[str], str]]:
        current_path: list[str] = []
        current_lines: list[str] = []
        sections: list[tuple[list[str], str]] = []
        for line in markdown.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and current_lines:
                sections.append((current_path[:], "\n".join(current_lines).strip()))
                current_lines = []
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                current_path = current_path[: level - 1] + [title]
                current_lines.append(line)
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_path[:], "\n".join(current_lines).strip()))
        return [(p, t) for p, t in sections if t]

    def _make_chunk(self, doc: SourceDocument, heading_path: list[str], text: str, index: int) -> TerrainChunk:
        metadata = doc.metadata
        ancestors = metadata.get("ancestors") or []
        ancestor_ids = [str(a.get("id")) for a in ancestors if isinstance(a, dict) and a.get("id")]
        ancestor_titles = [
            str(a.get("title")) for a in ancestors if isinstance(a, dict) and a.get("title")
        ]
        parent_id = metadata.get("parent_id")
        parent_title = metadata.get("parent_title")
        breadcrumbs = ancestor_titles + ([doc.title] if doc.title not in ancestor_titles else [])
        content_hash = sha256_hash(text)
        chunk_id = f"chunk_{short_hash(f'{doc.id}:{index}:{content_hash}', 20)}"
        return TerrainChunk(
            id=chunk_id,
            doc_id=doc.id,
            source_type=doc.source_type,
            source_id=doc.source_id,
            doc_title=doc.title,
            source_url=doc.source_url,
            source_parent_id=str(parent_id) if parent_id else None,
            source_parent_title=str(parent_title) if parent_title else None,
            source_ancestor_ids=ancestor_ids,
            source_breadcrumb_titles=breadcrumbs,
            heading_path=heading_path,
            content=text,
            content_hash=content_hash,
            urls=self._extract_urls(text),
            mentions=self._extract_mentions(text),
        )

    def _extract_urls(self, text: str) -> list[str]:
        # Match bare URLs and markdown-link targets; dedupe preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for raw in _URL_PATTERN.findall(text):
            url = raw.rstrip(".,;:!?)]>")
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out

    def _extract_mentions(self, text: str) -> list[str]:
        # @handles (stored with the @ prefix so they're distinguishable from
        # arbitrary names) and Jira-style ABC-123 keys. Per-source chunkers
        # can extend or override; this is the cross-source baseline.
        seen: set[str] = set()
        out: list[str] = []
        for handle in _MENTION_PATTERN.findall(text):
            token = f"@{handle}"
            if token not in seen:
                seen.add(token)
                out.append(token)
        for key in _JIRA_KEY_PATTERN.findall(text):
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    def _merge_tiny(self, chunks: list[TerrainChunk]) -> list[TerrainChunk]:
        merged: list[TerrainChunk] = []
        pending: TerrainChunk | None = None
        for chunk in chunks:
            if pending is None:
                pending = chunk
                continue
            if self._word_count(pending.content) < self.min_words:
                combined = f"{pending.content}\n\n{chunk.content}"
                pending = pending.model_copy(
                    update={
                        "content": combined,
                        "content_hash": sha256_hash(combined),
                        # Accumulate structural context across the merged chunks
                        # instead of dropping the trailing chunk's signal.
                        "heading_path": _ordered_union(
                            pending.heading_path, chunk.heading_path
                        ),
                        "wikilinks": _ordered_union(pending.wikilinks, chunk.wikilinks),
                        "urls": _ordered_union(pending.urls, chunk.urls),
                        "mentions": _ordered_union(pending.mentions, chunk.mentions),
                        "frontmatter_tags": _ordered_union(
                            pending.frontmatter_tags, chunk.frontmatter_tags
                        ),
                    }
                )
            else:
                merged.append(pending)
                pending = chunk
        if pending is not None:
            merged.append(pending)
        return merged

    def _split_large(self, chunks: list[TerrainChunk]) -> list[TerrainChunk]:
        out: list[TerrainChunk] = []
        for chunk in chunks:
            words = chunk.content.split()
            if len(words) <= self.max_words:
                out.append(chunk)
                continue
            for i in range(0, len(words), self.target_words):
                text = " ".join(words[i : i + self.target_words])
                content_hash = sha256_hash(text)
                out.append(
                    chunk.model_copy(
                        update={
                            "id": f"{chunk.id}_{i // self.target_words + 1}",
                            "content": text,
                            "content_hash": content_hash,
                        }
                    )
                )
        return out

    def _word_count(self, text: str) -> int:
        return len(text.split())
