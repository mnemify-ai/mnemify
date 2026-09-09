"""Raw-chunk expansion for /api/ask context bundles.

The compiled bundle carries only node labels and compiled summaries —
note items in particular are 160-char excerpts, far too thin for the
chat model to answer detail questions from. This module dereferences the
bundle items back to their raw source chunks in ``terrain.db`` and
attaches full-text excerpts, under a hard character budget.

Expansion is best-effort: a missing or unreadable ``terrain.db`` leaves
the bundle unchanged (the endpoint still answers from summaries alone).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash

from .ask_retrieval import ContextItem, SourceRef

logger = logging.getLogger(__name__)

# ~6k tokens of raw source text per question. Chunk expansion is the main
# lever for answer quality; tune here if BYOK cost becomes a concern.
EXPANSION_BUDGET_CHARS = 24_000
PER_ITEM_CHUNK_CAP = 3
PER_ITEM_CHAR_CAP = 4_000

# The citation popover's excerpt is cosmetic UI text, not prompt budget — kept
# short and independent of the (much larger) prompt-excerpt caps above so it
# never meaningfully grows the /api/ask SSE payload.
SOURCE_REF_EXCERPT_CHARS = 280

_TERRAIN_DB_PATH = Path(".mnemify/terrain.db")


@dataclass
class ExpansionResult:
    expanded: bool = False
    chunk_count: int = 0
    chars: int = 0
    errors: list[str] = field(default_factory=list)


def expand_bundle(
    items: list[ContextItem],
    store: TerrainStore | None = None,
    *,
    budget_chars: int = EXPANSION_BUDGET_CHARS,
    db_path: Path = _TERRAIN_DB_PATH,
) -> ExpansionResult:
    """Attach raw source-chunk excerpts to bundle items, in bundle (score)
    order, until the character budget runs out.

    Only ``note`` and ``signal`` items are expanded in v1 — tags and
    regions already carry compiled notes up to 1200 chars, while note
    excerpts are truncated to 160 chars at compile time.

    ``items`` are mutated in place (``raw_excerpts`` filled in).
    """
    result = ExpansionResult()
    own_store = False
    if store is None:
        if not db_path.is_file():
            return result
        try:
            store = TerrainStore(db_path)
            own_store = True
        except Exception:  # noqa: BLE001
            logger.exception("ask expansion: failed to open terrain.db")
            return result

    try:
        chunk_ids_by_item = _resolve_chunk_ids(items, store)
        if not any(chunk_ids_by_item.values()):
            return result

        remaining = budget_chars
        for item in items:  # bundle order == rerank score order
            if remaining <= 0:
                break
            chunk_ids = chunk_ids_by_item.get(item.citation_id) or []
            if not chunk_ids:
                continue
            chunks = store.get_chunks_by_ids(chunk_ids[:PER_ITEM_CHUNK_CAP])
            item_budget = min(PER_ITEM_CHAR_CAP, remaining)
            for chunk in chunks:
                if item_budget <= 0 or remaining <= 0:
                    break
                excerpt = _format_excerpt(chunk, max_chars=min(item_budget, remaining))
                if not excerpt:
                    continue
                item.raw_excerpts.append(excerpt)
                item.source_refs.append(_build_source_ref(chunk))
                item_budget -= len(excerpt)
                remaining -= len(excerpt)
                result.chunk_count += 1
        result.chars = budget_chars - remaining
        result.expanded = result.chunk_count > 0
        return result
    except Exception as e:  # noqa: BLE001
        logger.exception("ask expansion: failed; answering from summaries only")
        result.errors.append(str(e)[:200])
        return result
    finally:
        if own_store and store is not None:
            store.close()


def _resolve_chunk_ids(
    items: list[ContextItem], store: TerrainStore
) -> dict[str, list[str]]:
    """Map each expandable bundle item to its source chunk ids.

    Signals carry ``source_chunk_ids`` directly. Note nodes don't (in
    artifacts compiled before sourceChunkIds stamping landed), but their id
    is derived as ``n-{short_hash(doc_id, 8)}``, so we can rebuild the
    mapping from the chunks table without a recompile.
    """
    out: dict[str, list[str]] = {}
    note_items = [
        it for it in items if it.node_type == "note" and not it.source_chunk_ids
    ]
    note_id_to_chunks: dict[str, list[str]] = {}
    if note_items:
        for doc_id, chunk_ids in store.get_doc_chunk_index().items():
            note_id_to_chunks[f"n-{short_hash(doc_id, 8)}"] = chunk_ids

    for item in items:
        if item.node_type not in ("note", "signal"):
            continue
        if item.source_chunk_ids:
            out[item.citation_id] = list(item.source_chunk_ids)
        elif item.node_type == "note":
            out[item.citation_id] = note_id_to_chunks.get(item.node_id, [])
    return out


def _truncate_content(content: str, max_chars: int) -> str:
    content = (content or "").strip()
    if not content:
        return ""
    if max_chars <= 0:
        return ""
    if len(content) > max_chars:
        content = content[: max_chars - 1].rstrip() + "…"
    return content


def _format_excerpt(chunk: dict, *, max_chars: int) -> str:
    heading = " > ".join(chunk.get("heading_path") or [])
    header = chunk.get("doc_title") or chunk.get("doc_id") or ""
    if heading:
        header = f"{header} > {heading}" if header else heading
    body_budget = max_chars - len(header) - 4
    content = _truncate_content(chunk.get("content") or "", body_budget)
    if not content:
        return ""
    return f"[{header}]\n{content}" if header else content


def _build_source_ref(
    chunk: dict, *, max_chars: int = SOURCE_REF_EXCERPT_CHARS
) -> SourceRef:
    """Structured, UI-facing counterpart to ``_format_excerpt`` — same chunk,
    short independent excerpt cap, no header-line munging (fields stay
    separate so the frontend can lay them out itself)."""
    heading = " > ".join(chunk.get("heading_path") or []) or None
    return SourceRef(
        doc_title=chunk.get("doc_title") or chunk.get("doc_id") or "",
        doc_id=chunk.get("doc_id"),
        heading=heading,
        excerpt=_truncate_content(chunk.get("content") or "", max_chars),
        source_url=chunk.get("source_url"),
        updated_at=chunk.get("updated_at"),
    )
