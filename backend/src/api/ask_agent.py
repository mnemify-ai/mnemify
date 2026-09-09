"""Agentic `/api/ask` path (providers ``claude`` and ``anthropic``).

Runs a Claude Agent SDK session over the local Claude Code runtime and
exposes the existing retrieval machinery as read-only in-process MCP
tools, so the model explores the terrain itself — rephrasing queries,
following graph edges, and reading raw source text — instead of
answering from a single fixed retrieval pass.

Auth mirrors the legacy split: provider ``claude`` inherits the
logged-in Claude Code subscription (no key), provider ``anthropic``
injects the user's BYOK key into the CLI subprocess env only — the
server process env is never touched.

SSE contract: emits the same ``citations`` / ``delta`` /
``citations_used`` / ``done`` / ``error`` events as the legacy pipeline
(``citations`` re-sent cumulatively as tools register new items), plus
additive ``agent_step`` events driving the UI's step timeline.
``retrieval_debug`` is not emitted on this path — the timeline replaces
it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from src.terrain.utils.embedder import EmbeddingClient
from src.terrain.utils.models import KnowledgeMap, GraphNode
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash

from . import ask_chunks, ask_expansion, ask_retrieval
from .ask_retrieval import ContextItem, SourceRef

logger = logging.getLogger(__name__)

TOOL_NAMES = ("terrain_overview", "retrieve_context", "explore_node", "read_chunks")

# Loop/budget caps. max_turns bounds the whole session; per-tool output is
# capped below so a runaway exploration can't flood the context either.
MAX_TURNS = 16
HISTORY_CHAR_CAP = 8_000
READ_CHUNKS_MAX = 6
READ_CHUNKS_CHAR_CAP = 8_000
EDGE_LIST_CAP = 20

_SENTINEL: Any = object()


AGENT_SYSTEM_PROMPT = (
    "You are a research assistant answering questions from the user's "
    "compiled personal knowledge graph (their \"knowledge map\"). You "
    "cannot see the corpus directly — explore it with the tools below:\n"
    "- Call `terrain_overview` first to orient yourself.\n"
    "- Use `retrieve_context` with focused queries; if results look thin or "
    "off-topic, rephrase and query again rather than settling.\n"
    "- Use `explore_node` to follow graph connections from a promising node.\n"
    "- Use `read_chunks` when you need exact source wording before quoting "
    "or making a detailed claim.\n\n"
    "Every context item carries a citation id like `[c3]`. In your final "
    "answer, cite every item you actually draw on — and only items you "
    "used — so each factual claim carries at least one marker. If an item's "
    "edge_provenance is `inferred` or `ambiguous`, acknowledge that the "
    "connection is derived. Do not narrate between tool calls; call tools "
    "silently, then write one complete, well-cited answer. If the map "
    "does not contain the answer, say so plainly — do not invent. Stay "
    "within a handful of tool calls: stop exploring when additional results "
    "stop improving the evidence."
)


# ── citation registry ────────────────────────────────────────────────


class CitationRegistry:
    """Session-stable citation ids across multiple tool calls.

    ``ask_retrieval._build_bundle`` assigns ``c1..cN`` positionally per
    call, so two ``retrieve_context`` calls would collide. The registry
    dedupes by ``node_id`` and hands out ids in first-registration order;
    ``register`` rewrites ``item.citation_id`` in place so the existing
    ``render_bundle`` formatter emits registry ids unchanged.
    """

    def __init__(self) -> None:
        self._items: dict[str, ContextItem] = {}  # node_id -> first item
        self._order: list[str] = []

    def register(self, item: ContextItem) -> str:
        existing = self._items.get(item.node_id)
        if existing is not None:
            # Keep the first registration as the canonical metadata; adopt
            # richer excerpts/source info if a later pass expanded the same
            # node (e.g. explore_node first, retrieve_context's chunk
            # expansion later).
            if item.raw_excerpts and not existing.raw_excerpts:
                existing.raw_excerpts = list(item.raw_excerpts)
            if item.source_refs and not existing.source_refs:
                existing.source_refs = list(item.source_refs)
            if item.home_region_id and not existing.home_region_id:
                existing.home_region_id = item.home_region_id
            item.citation_id = existing.citation_id
            return existing.citation_id
        cid = f"c{len(self._order) + 1}"
        item.citation_id = cid
        self._items[item.node_id] = item
        self._order.append(item.node_id)
        return cid

    def register_node(self, node: GraphNode) -> str:
        item = ContextItem(
            citation_id="",
            node_id=node.id,
            node_type=node.type,
            layer=node.layer,
            label=node.label,
            summary=node.summary or "",
            source_note_ids=list(node.sourceNoteIds),
            source_chunk_ids=list(node.sourceChunkIds),
            home_region_id=node.homeRegionId,
        )
        return self.register(item)

    def attach_source_ref(self, node_id: str, ref: SourceRef) -> None:
        """Attach a structured source ref to an already-registered citation
        (used by `read_chunks`, which registers a bare node then reads its
        chunks in a separate step)."""
        item = self._items.get(node_id)
        if item is not None:
            item.source_refs.append(ref)

    def snapshot(self) -> list[dict]:
        """Cumulative citations in the exact dict shape the legacy route
        emits (`routes_ask.py` citations event)."""
        out: list[dict] = []
        for node_id in self._order:
            item = self._items[node_id]
            out.append(
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
            )
        return out

    def valid_ids(self) -> set[str]:
        return {self._items[n].citation_id for n in self._order}


# ── per-request context ──────────────────────────────────────────────


@dataclass
class AgentContext:
    knowledge_map: KnowledgeMap
    embedder: EmbeddingClient
    db_path: Path
    registry: CitationRegistry = field(default_factory=CitationRegistry)
    queue: "asyncio.Queue[Any]" = field(default_factory=asyncio.Queue)
    # Loop the SSE generator (and its queue) live on. When the SDK session
    # runs on a dedicated subprocess-capable loop in a worker thread (see
    # run_agent_session), emits from that thread hop back via
    # call_soon_threadsafe. None (tests) → direct put.
    server_loop: "asyncio.AbstractEventLoop | None" = None
    _edge_index: dict | None = None
    _step_seq: int = 0

    @property
    def graph(self):
        return self.knowledge_map.graph

    def edges_by_node(self) -> dict:
        if self._edge_index is None:
            self._edge_index = ask_retrieval._index_edges(self.graph.edges)
        return self._edge_index

    def next_step_id(self) -> str:
        self._step_seq += 1
        return f"s{self._step_seq}"

    def push_raw(self, item: Any) -> None:
        """Thread-safe queue push: direct on the owning loop, hop via
        call_soon_threadsafe from any other thread/loop."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self.server_loop is None or running is self.server_loop:
            self.queue.put_nowait(item)
        else:
            self.server_loop.call_soon_threadsafe(self.queue.put_nowait, item)

    def emit(self, event: str, payload: dict) -> None:
        self.push_raw({"event": event, "data": payload})

    def emit_citations(self) -> None:
        self.emit("citations", {"citations": self.registry.snapshot()})


def _step_start(ctx: AgentContext, tool: str, label: str) -> str:
    step_id = ctx.next_step_id()
    ctx.emit(
        "agent_step",
        {"id": step_id, "tool": tool, "label": label, "status": "running", "detail": None},
    )
    return step_id


def _step_end(
    ctx: AgentContext,
    step_id: str,
    tool: str,
    label: str,
    *,
    status: str = "done",
    detail: str | None = None,
    node_ids: list[str] | None = None,
) -> None:
    ctx.emit(
        "agent_step",
        {
            "id": step_id,
            "tool": tool,
            "label": label,
            "status": status,
            "detail": detail,
            # Terrain region ids this step touched — the frontend pulses them
            # on the 3D map so exploration is visible where the knowledge is.
            # Always present (possibly empty) so the client needs no fallback.
            "node_ids": node_ids or [],
        },
    )


# Cap on ids per step — a pulse is a glance, not a heat map, and a wide
# retrieve_context can otherwise light up the whole terrain at once.
PULSE_ID_CAP = 12


def _pulse_ids(items: Iterable[ContextItem]) -> list[str]:
    """Region ids the frontend can pulse for a set of touched nodes.

    A region node pulses itself; anything else (note/entity/tag/signal)
    pulses its home region, which is the only thing the map draws a
    medallion for. Deduped, first-touch order, capped at
    :data:`PULSE_ID_CAP`.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        rid = item.node_id if item.node_type == "region" else item.home_region_id
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
        if len(out) >= PULSE_ID_CAP:
            break
    return out


def _node_pulse_ids(node: GraphNode) -> list[str]:
    """Region ids to pulse for a single explored node — itself when it is a
    region, otherwise its home region."""
    rid = node.id if node.type == "region" else node.homeRegionId
    return [rid] if rid else []


# ── node resolution ──────────────────────────────────────────────────


def _resolve_node(ctx: AgentContext, ref: str) -> tuple[GraphNode | None, list[GraphNode]]:
    """Resolve a node by exact id, exact label, or label substring.

    Returns ``(node, candidates)`` — ``node`` when the match is
    unambiguous, otherwise up to 8 candidates for the agent to pick from.
    """
    ref = (ref or "").strip()
    if not ref:
        return None, []
    for node in ctx.graph.nodes:
        if node.id == ref:
            return node, []
    lowered = ref.lower()
    exact = [n for n in ctx.graph.nodes if n.label.lower() == lowered]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, exact[:8]
    partial = [n for n in ctx.graph.nodes if lowered in n.label.lower()]
    if len(partial) == 1:
        return partial[0], []
    return None, partial[:8]


def _node_label(ctx: AgentContext, node_id: str) -> str:
    for node in ctx.graph.nodes:
        if node.id == node_id:
            return node.label
    return node_id


# ── tool handlers ────────────────────────────────────────────────────


def build_tool_handlers(ctx: AgentContext) -> dict[str, Any]:
    """Plain async handlers keyed by tool name (testable without the SDK).

    Every handler returns the MCP content shape
    ``{"content": [{"type": "text", "text": ...}]}`` and never raises —
    failures come back as ``ERROR: ...`` text the agent can adapt to.
    """

    def _text(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    async def terrain_overview(args: dict) -> dict:
        label = "Surveying the map"
        step = _step_start(ctx, "terrain_overview", label)
        try:
            graph = ctx.graph
            by_type: dict[str, int] = {}
            for node in graph.nodes:
                by_type[node.type] = by_type.get(node.type, 0) + 1
            lines = [
                f"Workspace: {ctx.knowledge_map.workspace}",
                "Node counts: "
                + ", ".join(f"{t}={n}" for t, n in sorted(by_type.items()))
                + f"; edges={len(graph.edges)}",
                "",
                "Regions:",
            ]
            for node in graph.nodes:
                if node.type == "region":
                    summary = (node.summary or "").strip().replace("\n", " ")[:200]
                    lines.append(f"- {node.label} ({node.id}): {summary}")
            tags = sorted(
                (n for n in graph.nodes if n.type == "tag"),
                key=lambda n: -n.centrality,
            )[:10]
            if tags:
                lines.append("")
                lines.append("Top tags by centrality:")
                for node in tags:
                    lines.append(f"- {node.label} ({node.id})")
            if graph.surprisingConnections:
                lines.append("")
                lines.append("Surprising connections:")
                for edge in graph.surprisingConnections:
                    lines.append(
                        f"- {_node_label(ctx, edge.from_)} ~ {_node_label(ctx, edge.to)}"
                    )
            detail = f"{len(graph.nodes)} nodes, {len(graph.edges)} edges"
            _step_end(ctx, step, "terrain_overview", label, detail=detail)
            return _text("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            logger.exception("ask agent: terrain_overview failed")
            _step_end(
                ctx, step, "terrain_overview", label, status="error", detail=str(e)[:120]
            )
            return _text(f"ERROR: overview failed: {e}")

    async def retrieve_context(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        label = f'Searching the map: "{query[:60]}"'
        step = _step_start(ctx, "retrieve_context", label)
        try:
            if not query:
                _step_end(
                    ctx, step, "retrieve_context", label,
                    status="error", detail="empty query",
                )
                return _text("ERROR: retrieve_context requires a non-empty `query`.")

            try:
                embedding = await asyncio.to_thread(ctx.embedder.embed, query)
            except Exception:  # noqa: BLE001
                logger.exception("ask agent: query embed failed")
                embedding = []

            graph_dim = _graph_dim(ctx.knowledge_map)
            if embedding and graph_dim and len(embedding) != graph_dim:
                _step_end(
                    ctx, step, "retrieve_context", label,
                    status="error", detail="embedding dimension mismatch",
                )
                return _text(
                    f"ERROR: query embedding dimension ({len(embedding)}) does not "
                    f"match the compiled graph ({graph_dim}). Semantic search is "
                    "unavailable — try explore_node with names from terrain_overview."
                )

            chunk_matches = await asyncio.to_thread(
                ask_chunks.search, embedding, db_path=ctx.db_path
            )
            chunk_hits: dict[str, float] = {}
            chunk_ids_by_note: dict[str, list[str]] = {}
            for hit in chunk_matches:
                chunk_hits[hit.note_node_id] = max(
                    chunk_hits.get(hit.note_node_id, 0.0), hit.score
                )
                chunk_ids_by_note.setdefault(hit.note_node_id, []).append(hit.chunk_id)

            retrieval = await asyncio.to_thread(
                ask_retrieval.retrieve,
                query,
                embedding,
                ctx.graph,
                understanding=None,
                chunk_hits=chunk_hits,
            )
            items = retrieval.items

            if not embedding and not retrieval.seed_node_ids:
                _step_end(
                    ctx, step, "retrieve_context", label,
                    status="error", detail="no semantic signal, no mention seeds",
                )
                return _text(
                    "ERROR: query embedding failed and no entity mentions matched. "
                    "Try again with distinctive proper nouns from the question, or "
                    "navigate via terrain_overview + explore_node."
                )

            # Matched chunks lead each note's expansion list (same reorder as
            # the legacy route) so the budget lands on text that matched.
            for item in items:
                matched = chunk_ids_by_note.get(item.node_id)
                if matched and item.node_type == "note":
                    rest = [c for c in item.source_chunk_ids if c not in matched]
                    item.source_chunk_ids = matched + rest

            expansion = await asyncio.to_thread(
                ask_expansion.expand_bundle, items, db_path=ctx.db_path
            )
            for item in items:
                ctx.registry.register(item)
            ctx.emit_citations()

            detail = f"{len(items)} items, {expansion.chunk_count} source chunks"
            _step_end(
                ctx, step, "retrieve_context", label,
                detail=detail, node_ids=_pulse_ids(items),
            )
            if not items:
                return _text(
                    "No matching context found. Rephrase the query or explore "
                    "the graph directly."
                )
            return _text(ask_retrieval.render_bundle(items))
        except Exception as e:  # noqa: BLE001
            logger.exception("ask agent: retrieve_context failed")
            _step_end(
                ctx, step, "retrieve_context", label, status="error", detail=str(e)[:120]
            )
            return _text(f"ERROR: retrieval failed: {e}")

    async def explore_node(args: dict) -> dict:
        ref = str(args.get("node_ref") or "").strip()
        label = f"Exploring: {ref[:60]}" if ref else "Exploring node"
        step = _step_start(ctx, "explore_node", label)
        try:
            node, candidates = _resolve_node(ctx, ref)
            if node is None:
                if candidates:
                    listing = "\n".join(
                        f"- {n.label} ({n.id}, {n.type})" for n in candidates
                    )
                    _step_end(
                        ctx, step, "explore_node", label,
                        detail=f"{len(candidates)} candidates",
                    )
                    return _text(
                        f"Ambiguous reference {ref!r} — candidates:\n{listing}\n"
                        "Call explore_node again with the exact id."
                    )
                _step_end(
                    ctx, step, "explore_node", label,
                    status="error", detail="no match",
                )
                return _text(
                    f"ERROR: no node matches {ref!r}. Use ids or labels from "
                    "terrain_overview / retrieve_context results."
                )

            cid = ctx.registry.register_node(node)
            ctx.emit_citations()

            layer_label = {0: "note", 1: "entity", 2: "tag/signal", 3: "region"}.get(
                node.layer, "node"
            )
            lines = [f"[{cid}] {node.label} — type={node.type} layer={layer_label}"]
            if node.summary:
                lines.append(f"summary: {node.summary}")
            if node.signalKind:
                lines.append(
                    f"signal: kind={node.signalKind} severity={node.severity} "
                    f"status={node.status} owner={node.owner or '-'}"
                )
            if node.homeRegionId:
                lines.append(f"home region: {_node_label(ctx, node.homeRegionId)}")
            if node.sourceNoteIds:
                lines.append(f"source_note_ids: {', '.join(node.sourceNoteIds[:8])}")
            if node.sourceChunkIds:
                lines.append(
                    f"source_chunk_ids: {', '.join(node.sourceChunkIds[:12])}"
                )

            edges = [
                e
                for e in ctx.edges_by_node().get(node.id, [])
                if ask_retrieval._edge_passes(e)
            ]
            edges.sort(key=lambda e: -e.weight)
            if edges:
                lines.append("")
                lines.append("Connections:")
                for e in edges[:EDGE_LIST_CAP]:
                    other_id = e.to if e.from_ == node.id else e.from_
                    lines.append(
                        f"- {_node_label(ctx, other_id)} ({other_id}) "
                        f"[{e.type} w={e.weight:.2f} conf={e.confidence:.2f} "
                        f"{e.provenance}]"
                    )
            _step_end(
                ctx, step, "explore_node", f"Exploring: {node.label[:60]}",
                detail=f"{len(edges)} connections",
                node_ids=_node_pulse_ids(node),
            )
            return _text("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            logger.exception("ask agent: explore_node failed")
            _step_end(
                ctx, step, "explore_node", label, status="error", detail=str(e)[:120]
            )
            return _text(f"ERROR: explore failed: {e}")

    async def read_chunks(args: dict) -> dict:
        label = "Reading source text"
        step = _step_start(ctx, "read_chunks", label)
        try:
            chunk_ids = [str(c) for c in (args.get("chunk_ids") or []) if str(c).strip()]
            node_ref = str(args.get("node_ref") or "").strip()
            max_chars = int(args.get("max_chars") or READ_CHUNKS_CHAR_CAP)
            max_chars = max(500, min(max_chars, READ_CHUNKS_CHAR_CAP))

            if not chunk_ids and node_ref:
                node, candidates = _resolve_node(ctx, node_ref)
                if node is None:
                    detail = "ambiguous node_ref" if candidates else "no match"
                    _step_end(
                        ctx, step, "read_chunks", label, status="error", detail=detail
                    )
                    return _text(
                        f"ERROR: could not resolve node_ref {node_ref!r}"
                        + (
                            " — candidates: "
                            + ", ".join(f"{n.label} ({n.id})" for n in candidates)
                            if candidates
                            else ""
                        )
                    )
                chunk_ids = list(node.sourceChunkIds)
            if not chunk_ids:
                _step_end(
                    ctx, step, "read_chunks", label,
                    status="error", detail="no chunk ids",
                )
                return _text(
                    "ERROR: pass `chunk_ids` (from retrieve_context / "
                    "explore_node results) or a `node_ref` that carries "
                    "source_chunk_ids."
                )
            chunk_ids = chunk_ids[:READ_CHUNKS_MAX]

            def _load() -> list[dict]:
                store = TerrainStore(ctx.db_path)
                try:
                    return store.get_chunks_by_ids(chunk_ids)
                finally:
                    store.close()

            rows = await asyncio.to_thread(_load)
            if not rows:
                _step_end(
                    ctx, step, "read_chunks", label,
                    status="error", detail="chunks not found",
                )
                return _text("ERROR: none of the requested chunk ids exist.")

            per_chunk = max(500, max_chars // len(rows))
            note_ids_by_node = {n.id: n for n in ctx.graph.nodes if n.type == "note"}
            parts: list[str] = []
            titles: list[str] = []
            for chunk in rows:
                excerpt = ask_expansion._format_excerpt(chunk, max_chars=per_chunk)
                if not excerpt:
                    continue
                note_id = f"n-{short_hash(chunk['doc_id'], 8)}"
                note = note_ids_by_node.get(note_id)
                if note is not None:
                    cid = ctx.registry.register_node(note)
                    ctx.registry.attach_source_ref(
                        note.id, ask_expansion._build_source_ref(chunk)
                    )
                    excerpt = f"[{cid}] {excerpt}"
                parts.append(excerpt)
                title = chunk.get("doc_title") or ""
                if title and title not in titles:
                    titles.append(title)
            ctx.emit_citations()
            detail = ", ".join(titles[:3]) or f"{len(parts)} chunks"
            _step_end(ctx, step, "read_chunks", label, detail=detail)
            return _text("\n\n".join(parts) if parts else "ERROR: chunks were empty.")
        except Exception as e:  # noqa: BLE001
            logger.exception("ask agent: read_chunks failed")
            _step_end(
                ctx, step, "read_chunks", label, status="error", detail=str(e)[:120]
            )
            return _text(f"ERROR: read failed: {e}")

    return {
        "terrain_overview": terrain_overview,
        "retrieve_context": retrieve_context,
        "explore_node": explore_node,
        "read_chunks": read_chunks,
    }


# ── SDK wiring ───────────────────────────────────────────────────────

_TOOL_SCHEMAS: dict[str, tuple[str, dict]] = {
    "terrain_overview": (
        "Orient yourself: workspace stats, all regions with summaries, top "
        "tags, and surprising cross-links. Call this first.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "retrieve_context": (
        "Hybrid semantic + graph retrieval over the terrain. Returns a "
        "ranked, citation-tagged context bundle with raw source excerpts. "
        "Rephrase and call again if results look thin.",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Focused search phrasing of what you need.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "explore_node": (
        "Inspect one graph node (by id or label) — full summary, metadata, "
        "and its typed, weighted connections to neighboring nodes.",
        {
            "type": "object",
            "properties": {
                "node_ref": {
                    "type": "string",
                    "description": "Node id (preferred) or label substring.",
                }
            },
            "required": ["node_ref"],
            "additionalProperties": False,
        },
    ),
    "read_chunks": (
        "Read raw source text for specific chunk ids, or for a note node's "
        "sources. Use before quoting exact wording.",
        {
            "type": "object",
            "properties": {
                "chunk_ids": {"type": "array", "items": {"type": "string"}},
                "node_ref": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ),
}


def build_mcp_server(ctx: AgentContext):
    from claude_agent_sdk import create_sdk_mcp_server, tool

    handlers = build_tool_handlers(ctx)
    tools = [
        tool(name, _TOOL_SCHEMAS[name][0], _TOOL_SCHEMAS[name][1])(handlers[name])
        for name in TOOL_NAMES
    ]
    return create_sdk_mcp_server(name="terrain", version="1.0.0", tools=tools)


def _build_options(ctx: AgentContext, provider: str, model: str, key: str | None):
    from claude_agent_sdk import ClaudeAgentOptions

    env: dict[str, str] = {}
    if provider == "anthropic" and key:
        # BYOK: the key rides only in the CLI subprocess env — never the
        # server process env. Without it (provider "claude") the subprocess
        # uses the logged-in Claude Code subscription.
        env["ANTHROPIC_API_KEY"] = key
    return ClaudeAgentOptions(
        system_prompt=AGENT_SYSTEM_PROMPT,
        mcp_servers={"terrain": build_mcp_server(ctx)},
        tools=[],  # no built-ins: no Bash/Read/filesystem access
        allowed_tools=[f"mcp__terrain__{n}" for n in TOOL_NAMES],
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "Task",
        ],
        permission_mode="dontAsk",
        max_turns=MAX_TURNS,
        model=model,
        env=env,
        setting_sources=None,
        include_partial_messages=True,
    )


def _render_prompt(query: str, history: list[dict]) -> str:
    turns: list[str] = []
    for turn in history:
        role = str(turn.get("role", "user"))
        content = str(turn.get("content", "")).strip()
        if content:
            turns.append(f"{role}: {content}")
    # Cap the rendered history, dropping oldest turns first.
    while turns and sum(len(t) + 1 for t in turns) > HISTORY_CHAR_CAP:
        turns.pop(0)
    if not turns:
        return query
    return (
        "<conversation_history>\n"
        + "\n".join(turns)
        + "\n</conversation_history>\n\n"
        + f"Current question: {query}"
    )


def _graph_dim(knowledge_map: KnowledgeMap) -> int | None:
    if knowledge_map.graph is None:
        return None
    for node in knowledge_map.graph.nodes:
        vec = node.embedding or node.context_embedding
        if vec:
            return len(vec)
    return None


def _sdk_query(*, prompt: str, options: Any):
    """Indirection seam so tests can fake the SDK stream."""
    from claude_agent_sdk import query

    return query(prompt=prompt, options=options)


def _loop_supports_subprocess() -> bool:
    """Whether the *current* event loop can spawn subprocesses.

    On Windows only the ProactorEventLoop can; uvicorn's reload mode (and
    anything else using ``use_subprocess=True``) runs the app on a
    SelectorEventLoop, where ``loop.subprocess_exec`` raises
    NotImplementedError and the SDK cannot start the Claude CLI. In that
    case ``run_agent_session`` moves the session to a dedicated Proactor
    loop in a worker thread.
    """
    if sys.platform != "win32":
        return True
    return isinstance(asyncio.get_running_loop(), asyncio.ProactorEventLoop)


# ── session runner ───────────────────────────────────────────────────


async def run_agent_session(
    *,
    query_text: str,
    history: list[dict],
    provider: str,
    model: str,
    key: str | None,
    knowledge_map: KnowledgeMap,
    embedder: EmbeddingClient,
    db_path: Path | None = None,
) -> AsyncIterator[dict]:
    """Yield SSE dicts (``{"event", "data"}``, data pre-serialized) for an
    agentic ask session. Cancelling the generator (client disconnect)
    cancels the SDK session and kills the CLI subprocess."""
    from claude_agent_sdk import (
        AssistantMessage,
        CLIConnectionError,
        CLINotFoundError,
        ClaudeSDKError,
        ProcessError,
        ResultMessage,
        StreamEvent,
        TextBlock,
    )

    ctx = AgentContext(
        knowledge_map=knowledge_map,
        embedder=embedder,
        db_path=db_path or ask_expansion._TERRAIN_DB_PATH,
    )
    prompt = _render_prompt(query_text, history)
    options = _build_options(ctx, provider, model, key)
    queue = ctx.queue

    async def consume() -> None:
        try:
            await _consume_session()
        finally:
            ctx.push_raw(_SENTINEL)

    async def _consume_session() -> None:
        answer_parts: list[str] = []
        delta_chars = 0
        try:
            async for message in _sdk_query(prompt=prompt, options=options):
                if isinstance(message, StreamEvent):
                    if message.parent_tool_use_id:
                        continue
                    ev = message.event or {}
                    if ev.get("type") != "content_block_delta":
                        continue
                    delta = ev.get("delta") or {}
                    text = delta.get("text") or ""
                    if delta.get("type") == "text_delta" and text:
                        answer_parts.append(text)
                        delta_chars += len(text)
                        ctx.emit("delta", {"text": text})
                elif isinstance(message, AssistantMessage):
                    # Fallback when partial streaming yields no text (its
                    # deltas would have arrived before the completed
                    # message, so delta_chars > 0 whenever streaming works).
                    if delta_chars == 0:
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                answer_parts.append(block.text)
                                ctx.emit("delta", {"text": block.text})
                elif isinstance(message, ResultMessage):
                    if message.is_error and not answer_parts:
                        raise RuntimeError(
                            f"agent session failed ({message.subtype})"
                        )
        except asyncio.CancelledError:
            raise
        except CLINotFoundError:
            logger.exception("ask agent: claude CLI not found")
            ctx.emit(
                "error",
                {
                    "message": (
                        "Claude Code CLI not found on the server. Install it and "
                        "log in (`claude` → `/login`), or switch the Ask provider "
                        "to OpenAI in Settings."
                    )
                },
            )
            return
        except (CLIConnectionError, ProcessError, ClaudeSDKError) as e:
            logger.exception("ask agent: SDK session failed")
            ctx.emit("error", {"message": f"agent session failed: {str(e)[:200]}"})
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("ask agent: session failed")
            ctx.emit("error", {"message": str(e)[:200]})
            return

        # Terminal events — skipped entirely on error (error replaces the
        # tail, matching the legacy contract).
        text = "".join(answer_parts)
        used = ask_retrieval.extract_used_citations(text, ctx.registry.valid_ids())
        snapshot = ctx.registry.snapshot()
        fallback = False
        if not used and snapshot:
            fallback = True
            used = [c["citation_id"] for c in snapshot[:5]]
        ctx.emit("citations_used", {"used": used, "fallback": fallback})
        ctx.emit("done", {})

    ctx.server_loop = asyncio.get_running_loop()

    task: "asyncio.Task | None" = None
    stop: "threading.Event | None" = None
    if _loop_supports_subprocess():
        task = asyncio.create_task(consume())
    else:
        # The current loop can't spawn subprocesses (Windows
        # SelectorEventLoop — e.g. uvicorn --reload), so the SDK session
        # runs on a dedicated Proactor loop in a worker thread; its events
        # hop back to this loop via ctx.push_raw.
        stop = threading.Event()

        def _thread_main() -> None:
            loop = (
                asyncio.ProactorEventLoop()
                if sys.platform == "win32"
                else asyncio.new_event_loop()
            )
            asyncio.set_event_loop(loop)
            try:
                session = loop.create_task(consume())

                def _poll_stop() -> None:
                    if session.done():
                        return
                    if stop.is_set():
                        session.cancel()
                    else:
                        loop.call_later(0.2, _poll_stop)

                loop.call_soon(_poll_stop)
                with suppress(asyncio.CancelledError):
                    loop.run_until_complete(session)
            except Exception:  # noqa: BLE001
                logger.exception("ask agent: session thread crashed")
                ctx.push_raw(_SENTINEL)  # harmless duplicate if already sent
            finally:
                loop.close()

        threading.Thread(
            target=_thread_main, name="ask-agent-session", daemon=True
        ).start()

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield {"event": item["event"], "data": json.dumps(item["data"])}
    except asyncio.CancelledError:
        if task is not None:
            task.cancel()
        if stop is not None:
            stop.set()
        raise
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        if stop is not None:
            stop.set()
