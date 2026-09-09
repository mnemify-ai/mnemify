from __future__ import annotations

from langchain_text_splitters import MarkdownHeaderTextSplitter

from src.terrain.preprocessing.chunkers.markdown_default import MarkdownDefaultChunker
from src.terrain.utils.models import TerrainChunk
from src.utils.hashing import sha256_hash


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _line_spans_for_words(content: str) -> list[tuple[int, int]]:
    """Return (line_index, word_count) pairs in document order."""
    return [(i, len(line.split())) for i, line in enumerate(content.splitlines())]


class ConfluenceChunker(MarkdownDefaultChunker):
    """Confluence-tuned chunker.

    Heading-based sectioning, then a table-aware size cap. The default
    chunker post-processes heading sections with a character-recursive
    splitter that doesn't know about markdown tables and will split mid-row
    when a section exceeds the size budget. Confluence skips that pass and
    lets `_split_large` enforce the size cap — keeping tables intact.

    Tables in Confluence (status tables, decision matrices, field schemas)
    carry their meaning row-by-row; shredding them mid-table destroys the
    row→column relationship the LLM needs to read them.
    """

    def _langchain_sections(self, markdown: str) -> list[tuple[list[str], str]]:
        headers = [(f"{'#' * level}", f"h{level}") for level in range(1, 7)]
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
        header_docs = header_splitter.split_text(markdown)
        return [
            (self._heading_path(d.metadata), d.page_content.strip())
            for d in header_docs
            if d.page_content.strip()
        ]

    def _split_large(self, chunks: list[TerrainChunk]) -> list[TerrainChunk]:
        out: list[TerrainChunk] = []
        for chunk in chunks:
            if self._word_count(chunk.content) <= self.max_words:
                out.append(chunk)
                continue
            out.extend(self._split_respecting_tables(chunk))
        return out

    def _split_respecting_tables(self, chunk: TerrainChunk) -> list[TerrainChunk]:
        lines = chunk.content.splitlines()
        segments: list[list[str]] = []
        current: list[str] = []
        current_words = 0
        in_table = False

        for line in lines:
            line_words = len(line.split())
            line_is_table = _is_table_line(line)

            # Entering a table: flush any pending segment first if we're at the
            # word budget. Inside a table we never break.
            if line_is_table and not in_table:
                if current_words >= self.target_words and current:
                    segments.append(current)
                    current = []
                    current_words = 0
                in_table = True
            elif not line_is_table and in_table:
                in_table = False

            current.append(line)
            current_words += line_words

            if not in_table and current_words >= self.target_words:
                segments.append(current)
                current = []
                current_words = 0

        if current:
            segments.append(current)

        if len(segments) <= 1:
            return [chunk]

        out: list[TerrainChunk] = []
        for i, segment in enumerate(segments, start=1):
            text = "\n".join(segment).strip()
            if not text:
                continue
            out.append(
                chunk.model_copy(
                    update={
                        "id": f"{chunk.id}_{i}",
                        "content": text,
                        "content_hash": sha256_hash(text),
                    }
                )
            )
        return out
