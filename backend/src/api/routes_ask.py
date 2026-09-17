"""`/api/ask` — BYOK chatbot grounded in the compiled map (Stage 5).

The retrieval reads ``terrain.json`` for the layered graph, pulls a
context bundle out of it, expands the top items with raw source-chunk
text from ``terrain.db`` (best-effort — summaries alone if the db is
absent), and streams a chat response from the user's chosen provider
over SSE.

BYOK contract:
- The user's chat-LLM key arrives in the ``Authorization: Bearer …``
  header. The server forwards it to the provider and never persists or
  logs it.
- When that header is absent, the server falls back to the key stored for
  the provider under Settings → AI & Models (``credential_store``), so a
  configured machine doesn't ask for the same secret a second time. The
  header still wins when present; provider ``claude`` needs no key either
  way (local CLI subscription).
- The embedding for query-side similarity uses the server's
  ``OPENAI_API_KEY`` (already required for compile) when openai mode is
  active. Falls back to the local hash embedder when openai isn't
  available — slower-quality retrieval, but a working endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src import paths
from src.terrain.utils.embedder import EmbeddingClient, LocalHashEmbeddingClient
from src.terrain.utils.models import KnowledgeMap

from . import ask_chunks, ask_expansion, ask_providers, ask_retrieval, credential_store

logger = logging.getLogger(__name__)

router = APIRouter()

def _terrain_path() -> Path:
    """Resolved per request — ``MNEMIFY_HOME`` (and tests) can redirect it."""
    return paths.data_dir() / "terrain.json"


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    # "claude" routes the local `claude` CLI on the user's subscription (no key).
    provider: str = Field(pattern=r"^(anthropic|openai|claude)$")
    model: str = Field(min_length=1, max_length=120)
    history: list[dict] = Field(default_factory=list)


# Claude Code detection is cheap (PATH lookup + reading two small local
# files) but the settings panel may poll it on every open — cache briefly.
_CLAUDE_STATUS_TTL_S = 60.0
_claude_status_cache: tuple[float, dict] | None = None


def _detect_claude_status() -> dict:
    """Best-effort local Claude Code detection for the settings panel.

    ``installed``: the `claude` binary is on PATH. ``authenticated``: True when
    a subscription login is visible on disk, None when we can't tell (e.g.
    macOS keychain-stored credentials) — never a hard False unless we're sure.
    """
    installed = shutil.which("claude") is not None
    authenticated: bool | None = None
    if installed:
        home = Path.home()
        if (home / ".claude" / ".credentials.json").exists():
            authenticated = True
        else:
            try:
                cfg = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
                if isinstance(cfg, dict) and cfg.get("oauthAccount"):
                    authenticated = True
            except (OSError, json.JSONDecodeError):
                pass
    return {"installed": installed, "authenticated": authenticated}


@router.get("/ask/claude-status")
async def claude_status():
    """GET /api/ask/claude-status — is Claude Code usable on this machine?

    Lets the chat settings tell the user whether the key field is optional
    (local login present) or effectively required.
    """
    global _claude_status_cache
    now = time.monotonic()
    if _claude_status_cache and now - _claude_status_cache[0] < _CLAUDE_STATUS_TTL_S:
        return _claude_status_cache[1]
    status = await asyncio.to_thread(_detect_claude_status)
    _claude_status_cache = (now, status)
    return status


@router.post("/ask")
async def ask(
    body: AskRequest,
    authorization: str | None = Header(default=None),
):
    """POST /api/ask — stream a grounded answer over SSE.

    Body: ``{query, provider, model, history?}``. Auth: ``Authorization:
    Bearer <user_api_key>`` (the user's BYOK key for the chat LLM).
    """
    key = _resolve_key(body.provider, authorization)
    if _PROVIDER_KEY_ENV.get(body.provider) and not key:
        raise HTTPException(
            401,
            f"no API key for {body.provider} — add it under Settings → AI & "
            f"Models, or send Authorization: Bearer <key>.",
        )

    if not _terrain_path().is_file():
        raise HTTPException(
            409,
            "no compiled terrain — run /api/terrain/build first",
        )

    try:
        knowledge_map = _load_knowledge_map_cached()
    except Exception as e:  # noqa: BLE001
        logger.exception("ask: failed to load terrain.json")
        raise HTTPException(500, f"terrain load failed: {e}") from e

    if knowledge_map.graph is None or not knowledge_map.graph.nodes:
        raise HTTPException(
            409,
            "terrain has no graph view — re-run /api/terrain/build (Stage 4+ "
            "compiles a chatbot-traversable graph).",
        )

    if body.provider in ("anthropic", "claude"):
        # Agentic path: a Claude Agent SDK session explores the terrain via
        # read-only tools (src/api/ask_agent.py) instead of the fixed
        # retrieve-then-answer pipeline below. Lazy import so a missing
        # claude-agent-sdk dep degrades to a clean error for these providers
        # without affecting openai users.
        from . import ask_agent

        return EventSourceResponse(
            ask_agent.run_agent_session(
                query_text=body.query,
                history=body.history,
                provider=body.provider,
                model=body.model,
                key=key,
                knowledge_map=knowledge_map,
                embedder=_embedder_for_query(),
            )
        )

    # Query understanding (best-effort, one cheap non-streaming call on the
    # user's BYOK provider). Improves seeding for paraphrased questions; on any
    # failure ``understanding`` is None and retrieval falls back to the regex
    # heuristic. The topic paraphrase, when present, is what we embed.
    understanding = await ask_providers.understand_query(
        body.provider, body.model, key, body.query, history=body.history[-2:]
    )
    embed_text = body.query
    if understanding and understanding.get("topicIntent"):
        embed_text = understanding["topicIntent"]

    embedder = _embedder_for_query()
    try:
        query_embedding = embedder.embed(embed_text)
    except Exception:  # noqa: BLE001
        logger.exception("ask: query embed failed; falling back to no semantic seed")
        query_embedding = []

    # Guard against a query/graph embedding-space mismatch (e.g. graph
    # compiled with OpenAI vectors but OPENAI_API_KEY absent at ask time →
    # 64-dim hash fallback). Cosine over mismatched dims is silently 0, which
    # empties retrieval and produces a confidently-ungrounded answer — fail
    # loudly instead.
    graph_dim = _graph_embedding_dim(knowledge_map)
    if query_embedding and graph_dim and len(query_embedding) != graph_dim:
        raise HTTPException(
            503,
            f"retrieval unavailable: query embedding dimension "
            f"({len(query_embedding)}) does not match the compiled graph "
            f"({graph_dim}). Set OPENAI_API_KEY on the server to the "
            f"compile-time embedding key (or recompile) and retry.",
        )

    # Chunk-level semantic search — matches raw source text directly, then
    # seeds the parent note nodes. Best-effort: empty on old terrain.db
    # files (no stamped hashes) or dimension mismatch.
    chunk_matches = ask_chunks.search(query_embedding)
    chunk_hits: dict[str, float] = {}
    chunk_ids_by_note: dict[str, list[str]] = {}
    for hit in chunk_matches:
        chunk_hits[hit.note_node_id] = max(
            chunk_hits.get(hit.note_node_id, 0.0), hit.score
        )
        chunk_ids_by_note.setdefault(hit.note_node_id, []).append(hit.chunk_id)

    retrieval = ask_retrieval.retrieve(
        body.query,
        query_embedding,
        knowledge_map.graph,
        understanding=understanding,
        chunk_hits=chunk_hits,
    )

    # Matched chunks lead each note's expansion list so the budget is spent
    # on the text that actually matched the query.
    for item in retrieval.items:
        matched = chunk_ids_by_note.get(item.node_id)
        if matched and item.node_type == "note":
            rest = [c for c in item.source_chunk_ids if c not in matched]
            item.source_chunk_ids = matched + rest

    if not query_embedding and not retrieval.seed_node_ids:
        # No semantic signal AND no entity-mention seeds — answering now would
        # just be the chat model freewheeling with an empty context bundle.
        raise HTTPException(
            503,
            "retrieval unavailable: query embedding failed and no entity "
            "mentions matched the graph. Retry, or check the server's "
            "embedding configuration.",
        )

    expansion = ask_expansion.expand_bundle(retrieval.items)

    bundle_text = ask_retrieval.render_bundle(retrieval.items)
    system = (
        ask_retrieval.system_prompt()
        + "\n\nContext bundle:\n"
        + bundle_text
    )

    messages = list(body.history) + [{"role": "user", "content": body.query}]

    citations = [
        {
            "citation_id": item.citation_id,
            "node_id": item.node_id,
            "node_type": item.node_type,
            "layer": item.layer,
            "label": item.label,
            "edge_provenance": item.edge_provenance,
            "source_note_ids": item.source_note_ids,
            "source_chunk_ids": item.source_chunk_ids,
            "score": item.score,
            "home_region_id": item.home_region_id,
            # Doc name/excerpt/date for the citation popover. Empty for
            # tag/entity/region items, which never go through chunk
            # expansion — the frontend falls back to label/type/provenance.
            "source_refs": [
                {
                    "doc_title": r.doc_title,
                    "doc_id": r.doc_id,
                    "heading": r.heading,
                    "excerpt": r.excerpt,
                    "source_url": r.source_url,
                    "updated_at": r.updated_at,
                }
                for r in item.source_refs
            ],
        }
        for item in retrieval.items
    ]
    retrieval_debug = {
        "seed_node_ids": retrieval.seed_node_ids,
        "selected_node_ids": [item.node_id for item in retrieval.items],
        "source_note_ids": sorted({
            note_id
            for item in retrieval.items
            for note_id in (
                item.source_note_ids
                or ([item.node_id] if item.node_type == "note" else [])
            )
        }),
        "context_item_count": len(retrieval.items),
        "estimated_context_tokens": max(1, len(bundle_text) // 4) if bundle_text else 0,
        "raw_chunks_expanded": expansion.expanded,
        "expanded_chunk_count": expansion.chunk_count,
        "expansion_chars": expansion.chars,
        "chunk_search_hits": len(chunk_matches),
        "chunk_seeded_note_ids": sorted(chunk_hits),
    }

    async def event_gen():
        # Citations go up-front so the UI can resolve [cN] markers as they
        # stream in; the authoritative "which items the answer actually used"
        # set follows as `citations_used` once the answer is complete.
        yield {
            "event": "retrieval_debug",
            "data": json.dumps(retrieval_debug),
        }
        yield {
            "event": "citations",
            "data": json.dumps({"citations": citations}),
        }
        answer_parts: list[str] = []
        try:
            async for chunk in ask_providers.stream_chat(
                body.provider, body.model, key, messages, system=system
            ):
                answer_parts.append(chunk)
                yield {"event": "delta", "data": json.dumps({"text": chunk})}
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("ask: stream failed")
            yield {"event": "error", "data": json.dumps({"message": str(e)[:200]})}
            return
        valid_ids = {c["citation_id"] for c in citations}
        used = ask_retrieval.extract_used_citations("".join(answer_parts), valid_ids)
        fallback = False
        if not used and citations:
            # The model ignored the citation instruction — fall back to the
            # top-scored items so the chips (and map click-through) survive.
            fallback = True
            used = [c["citation_id"] for c in citations[:5]]
        yield {
            "event": "citations_used",
            "data": json.dumps({"used": used, "fallback": fallback}),
        }
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_gen())


# ── helpers ─────────────────────────────────────────────────────────


#: Which stored secret backs each provider. ``claude`` is absent on purpose:
#: it drives the local `claude` CLI on the user's subscription and needs no
#: key at all (src/api/ask_agent.py `_build_options`).
_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _resolve_key(provider: str, header: str | None) -> str | None:
    """The chat key for this request: browser header first, server store next.

    The BYOK header stays the highest-precedence source — a user who pastes a
    key into the chat panel gets that key, per-browser, and it is still never
    persisted. But requiring it made the server 401 on a machine where the key
    was already configured in Settings → AI & Models, forcing the same secret
    to be entered twice. So an absent header now falls back to the stored key
    for the provider.

    ``claude`` resolves to ``None`` either way — the CLI carries its own
    subscription auth.
    """
    bearer = _extract_bearer(header)
    if bearer:
        return bearer
    env_name = _PROVIDER_KEY_ENV.get(provider)
    return credential_store.get_secret(env_name) if env_name else None


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _graph_embedding_dim(knowledge_map: KnowledgeMap) -> int | None:
    """Dimension of the compiled graph's embedding space (first node that
    carries a vector), or None when no node has one."""
    if knowledge_map.graph is None:
        return None
    for node in knowledge_map.graph.nodes:
        vec = node.embedding or node.context_embedding
        if vec:
            return len(vec)
    return None


def _load_knowledge_map() -> KnowledgeMap:
    raw = _terrain_path().read_text(encoding="utf-8")
    data = json.loads(raw)
    knowledge_map = KnowledgeMap.model_validate(data)
    _hydrate_graph_vectors(knowledge_map)
    return knowledge_map


def _hydrate_graph_vectors(knowledge_map: KnowledgeMap) -> None:
    """Attach raw graph-node vectors from terrain.db to a lean artifact and
    recompute context embeddings. Fat artifacts (pre-strip compiles carrying
    inline vectors) skip untouched. Missing db/table degrades gracefully:
    vectorless nodes just score 0 semantically — chunk search and graph hops
    still work. Never raises."""
    graph = knowledge_map.graph
    if graph is None or not graph.nodes:
        return
    if any(n.embedding or n.context_embedding for n in graph.nodes):
        return  # fat artifact — vectors already inline

    db_path = paths.data_dir() / "terrain.db"
    if not db_path.exists():
        logger.warning(
            "ask: terrain.json has no inline vectors and %s is missing — "
            "semantic scoring degraded", db_path,
        )
        return
    try:
        from src.terrain.utils.graph_embed import apply_context_embeddings
        from src.terrain.utils.store import TerrainStore

        store = TerrainStore(db_path)
        try:
            vectors = store.load_graph_node_vectors()
        finally:
            store.close()
        if not vectors:
            logger.warning(
                "ask: graph_node_vectors table is empty — semantic scoring degraded"
            )
            return
        for node in graph.nodes:
            vec = vectors.get(node.id)
            if vec:
                node.embedding = vec
        apply_context_embeddings(graph.nodes, graph.edges)
    except Exception:  # noqa: BLE001 — retrieval must degrade, not 500
        logger.exception("ask: failed to hydrate graph vectors from terrain.db")


# path → (mtime, parsed KnowledgeMap). Compiles rewrite terrain.json atomically,
# so mtime is a reliable invalidation key; parsing+validating a large
# artifact on every question is pure overhead.
_MAP_CACHE: dict[str, tuple[float, KnowledgeMap]] = {}


def _load_knowledge_map_cached() -> KnowledgeMap:
    terrain_path = _terrain_path()
    key = str(terrain_path.resolve())
    mtime = terrain_path.stat().st_mtime
    cached = _MAP_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    knowledge_map = _load_knowledge_map()
    _MAP_CACHE[key] = (mtime, knowledge_map)
    return knowledge_map


def _embedder_for_query() -> EmbeddingClient:
    if os.getenv("OPENAI_API_KEY"):
        # Use the SAME embedding model the compile pass used, so the query
        # vector is directly comparable to the stored graph-node vectors
        # (model + dimensions must match or cosine search breaks). Read it from
        # the saved compile settings rather than hardcoding a default.
        from src.api.routes_settings import _compile_settings_block
        from src.terrain.agents.openai_clients import OpenAIEmbeddingClient

        return OpenAIEmbeddingClient(model=_compile_settings_block()["embedding_model"])
    # Local hash embeddings (low quality but functional — useful for tests
    # and offline demos).
    return LocalHashEmbeddingClient()
