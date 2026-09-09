"""Hybrid graph-scoped retrieval for /api/ask (Stage 5).

The chatbot's context bundle is built in six steps:

1. **Query understanding** (heuristic, no extra LLM call for v0.5) —
   extract explicit mentions from the query (capitalized phrases,
   ``@handles``, ``[[wikilinks]]``).
2. **Parallel seeding** across the entity, tag, region, and attention
   signal layers.
3. **Within-layer 1-hop walk** from each seed.
4. **Cross-layer walk** for the top seeds (entity → tag, tag → entity).
5. **Four-signal rerank** — semantic similarity (blended raw +
   ``context_embedding``), recency, centrality, and personal affinity
   (the last defaults to 0 until Stage 6 lands).
6. **Context bundle** — ordered list of node summaries with citation
   ids and edge provenance for the LLM to cite.

The retrieval reads :class:`GraphView` directly off the compiled
``terrain.json``. No new persistence is introduced.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from src.terrain.utils.models import GraphEdge, GraphNode, GraphView


# Default weights for the four-signal rerank. Tuned by hand; calibrate
# against real questions before shipping if quality is uneven.
W_SEMANTIC = 0.55
W_RECENCY = 0.15
W_CENTRALITY = 0.10
W_PERSONAL = 0.20

# Stage 4.6 blend — chatbot similarity uses 0.7 * context + 0.3 * raw.
CONTEXT_BLEND = 0.7

# Note nodes carry no embedding of their own (excerpts are short and we don't
# embed them). They inherit relevance from the tags/entities they connect to,
# discounted so a note ranks just below its most-relevant neighbor. Without
# this a note scores 0 on every signal and can never be cited.
NOTE_SEM_DISCOUNT = 0.85

# Limits / thresholds.
TAG_SEED_K = 5
REGION_SEED_K = 2
SIGNAL_SEED_K = 6
WITHIN_LAYER_K = 5
CROSS_LAYER_K = 3
CHUNK_NOTE_SEED_K = 6
CANDIDATE_CAP = 40
TOP_K_RERANKED = 15
MIN_EDGE_WEIGHT = 0.4
MIN_EDGE_CONFIDENCE = 0.6

# Per-edge-type confidence floors. The compiler emits `linked-to` at
# confidence 0.5 and `co-occurs`/`region-rel` at max(0.3, weight) — a uniform
# 0.6 gate made every lateral tag↔tag connection unwalkable. Lower floors for
# the inferred-lateral types keep the strict default for everything else.
EDGE_CONFIDENCE_FLOORS = {
    "linked-to": 0.45,
    "co-occurs": 0.45,
    "region-rel": 0.45,
}

# Bundle relevance floor — items scoring below this are dropped from the
# context bundle (but the bundle always keeps at least MIN_BUNDLE_ITEMS so a
# weak-signal query still gets grounded rather than answering from nothing).
MIN_ITEM_SCORE = 0.08
MIN_BUNDLE_ITEMS = 3

# Soft rerank boost for nodes whose type matches the query understanding's
# nodeTypes hint. A boost (never a filter) so a wrong LLM guess can't hide
# relevant nodes of other types.
NODE_TYPE_BOOST = 0.05


_CAPITALIZED = re.compile(r"\b([A-Z][\w-]+(?:\s+[A-Z][\w-]+){0,3})\b")
_MENTION = re.compile(r"@([A-Za-z0-9_][A-Za-z0-9_.-]+)")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


@dataclass
class SourceRef:
    """Structured, UI-facing source info for one expanded chunk — the
    citation popover's "why does Mnemify believe this?" payload. Parallel
    to (not a replacement for) the pre-formatted ``raw_excerpts`` strings,
    which still feed the LLM prompt via ``render_bundle``."""

    doc_title: str
    doc_id: str | None = None
    heading: str | None = None
    excerpt: str = ""
    source_url: str | None = None
    updated_at: str | None = None


@dataclass
class ContextItem:
    citation_id: str
    node_id: str
    node_type: str
    layer: int
    label: str
    summary: str
    edge_provenance: str | None = None
    source_note_ids: list[str] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)
    score: float = 0.0
    # Raw source-chunk excerpts attached by ask_expansion (each already
    # carries a doc-title/heading header line).
    raw_excerpts: list[str] = field(default_factory=list)
    # Structured parallel to raw_excerpts, for the /api/ask citations payload
    # (doc name/excerpt/date the frontend renders in the citation popover).
    source_refs: list[SourceRef] = field(default_factory=list)
    # The node's home region (GraphNode.homeRegionId), when it has one — lets
    # the frontend "Show on terrain" action focus a region for citations that
    # aren't themselves a region or tag (notes, entities, signals).
    home_region_id: str | None = None


@dataclass
class Retrieval:
    items: list[ContextItem] = field(default_factory=list)
    seed_node_ids: list[str] = field(default_factory=list)


def _resolve_mentions(query: str, understanding: dict | None) -> list[str]:
    """Merge LLM-extracted mentions (priority) with the regex heuristic
    (backstop). Falls back to regex-only when no understanding is supplied."""
    regex_mentions = extract_mentions(query)
    if not understanding:
        return regex_mentions
    llm_mentions = [str(m).strip() for m in understanding.get("mentions", []) if str(m).strip()]
    if not llm_mentions:
        return regex_mentions
    merged = list(llm_mentions)
    seen = {m.lower() for m in merged}
    for m in regex_mentions:
        if m.lower() not in seen:
            seen.add(m.lower())
            merged.append(m)
    return merged


def extract_mentions(query: str) -> list[str]:
    """Heuristic mention extraction (no LLM). Captures @handles,
    [[wikilinks]], and capitalized phrases."""
    out: list[str] = []
    seen: set[str] = set()

    for match in _MENTION.findall(query):
        token = match.lower()
        if token not in seen:
            seen.add(token)
            out.append(match)
    for match in _WIKILINK.findall(query):
        token = match.strip().lower()
        if token and token not in seen:
            seen.add(token)
            out.append(match.strip())
    for match in _CAPITALIZED.findall(query):
        token = match.lower()
        if token in seen:
            continue
        if len(token.split()) == 1 and len(token) < 4:
            continue  # skip short single-cap words ("OCR" is fine but "Use" isn't)
        seen.add(token)
        out.append(match)
    return out


def retrieve(
    query: str,
    query_embedding: list[float],
    graph: GraphView,
    *,
    user_affinity: dict[str, float] | None = None,
    understanding: dict | None = None,
    chunk_hits: dict[str, float] | None = None,
    weights: tuple[float, float, float, float] = (
        W_SEMANTIC, W_RECENCY, W_CENTRALITY, W_PERSONAL,
    ),
) -> Retrieval:
    """Run the hybrid retrieval pass; return the ordered context bundle.

    ``user_affinity`` (Stage 6) is an optional per-node-id score in
    [0, 1]; absent values default to 0 and silently drop the personal
    weight from the rerank.

    ``understanding`` (Stage 5 LLM query understanding) is an optional
    ``{nodeTypes, mentions, topicIntent}`` dict. When it carries mentions they
    take priority over the regex heuristic (with regex results merged in as a
    backstop); when absent, retrieval falls back to regex entirely.

    ``chunk_hits`` (chunk-level semantic search, ask_chunks) maps note node
    ids to their best chunk cosine. Matched notes are seeded directly and
    score with real semantic evidence instead of the inherited-neighbor
    approximation — this is what lets retrieval pick the *right* note among
    a tag's siblings.
    """
    if not graph.nodes:
        return Retrieval()

    nodes_by_id: dict[str, GraphNode] = {n.id: n for n in graph.nodes}
    edges_by_node = _index_edges(graph.edges)

    # 1. Query understanding — prefer LLM-extracted mentions, backfill with the
    #    regex heuristic so we never lose a literal proper-noun match.
    mentions = _resolve_mentions(query, understanding)

    # 2. Parallel seeding.
    entity_seeds = _seed_entities(graph, mentions)
    note_seeds = _seed_chunk_notes(nodes_by_id, chunk_hits, k=CHUNK_NOTE_SEED_K)
    tag_seeds = _seed_tags(graph, query_embedding, k=TAG_SEED_K)
    region_seeds = _seed_regions(graph, query_embedding, k=REGION_SEED_K)
    signal_seeds = _seed_signals(graph, query_embedding, k=SIGNAL_SEED_K)

    seeds = _dedupe_keep_order(
        entity_seeds + note_seeds + signal_seeds + tag_seeds + region_seeds
    )
    if not seeds:
        # Fallback: top tag seeds even with no mention match.
        seeds = tag_seeds

    # 3. Within-layer + 4. cross-layer walks. Keep insertion order (seeds
    # first) so the CANDIDATE_CAP truncation below is deterministic and never
    # silently drops a seed — capping a set would slice in arbitrary hash order.
    candidate_ids: set[str] = set()
    candidate_order: list[str] = []

    def _add_candidate(cid: str) -> None:
        if cid not in candidate_ids:
            candidate_ids.add(cid)
            candidate_order.append(cid)

    for seed in seeds:
        _add_candidate(seed.id)
    for seed in seeds:
        for neighbor in _within_layer_hop(
            seed, nodes_by_id, edges_by_node, k=WITHIN_LAYER_K
        ):
            _add_candidate(neighbor.id)
    for seed in seeds[: 2 * CROSS_LAYER_K]:
        for cross in _cross_layer_hop(seed, nodes_by_id, edges_by_node):
            _add_candidate(cross.id)

    # 5. Four-signal rerank. When the candidate pool overflows the cap, keep
    # every seed and fill the remaining slots by semantic score (id tiebreak)
    # rather than insertion order, so a strong late-walked candidate isn't
    # silently crowded out by an early seed's weak neighbors.
    seed_id_set = {s.id for s in seeds}
    candidate_nodes = [
        nodes_by_id[cid] for cid in candidate_order if cid in nodes_by_id
    ]
    if len(candidate_nodes) > CANDIDATE_CAP:
        kept = [n for n in candidate_nodes if n.id in seed_id_set]
        rest = [n for n in candidate_nodes if n.id not in seed_id_set]
        rest.sort(
            key=lambda n: (-_semantic_score(query_embedding, n), n.id)
        )
        candidates = (kept + rest)[:CANDIDATE_CAP]
    else:
        candidates = candidate_nodes
    max_degree = max(
        (n.centrality for n in candidates), default=1.0
    ) or 1.0
    affinity = user_affinity or {}
    scored = []
    w_sem, w_rec, w_cent, w_pers = weights
    if not affinity:
        # Personal affinity (Stage 6) isn't wired yet — renormalize the live
        # weights so semantic similarity keeps its intended dominance instead
        # of 20% of the score being permanently unreachable.
        live = w_sem + w_rec + w_cent
        if live > 0:
            w_sem, w_rec, w_cent = w_sem / live, w_rec / live, w_cent / live
        w_pers = 0.0
    node_type_hint = set(understanding.get("nodeTypes") or []) if understanding else set()
    hits = chunk_hits or {}
    for node in candidates:
        if node.type == "note" and not node.embedding:
            sem = _note_semantic_score(
                node, query_embedding, nodes_by_id, edges_by_node
            )
            # A direct chunk match is real semantic evidence for this exact
            # note — stronger than the inherited-neighbor approximation,
            # which is identical for every sibling of the same tag.
            sem = max(sem, hits.get(node.id, 0.0))
        else:
            sem = _semantic_score(query_embedding, node)
        rec = float(getattr(node, "recency", 0.0))  # stamped at graph emission
                                                     # (tag nodes from Tag.recencyScore;
                                                     # other layers default to 0).
        cent = float(node.centrality) / float(max_degree)
        pers = float(affinity.get(node.id, 0.0))
        score = (
            w_sem * sem
            + w_rec * rec
            + w_cent * cent
            + w_pers * pers
        )
        if node.type in node_type_hint:
            score += NODE_TYPE_BOOST
        scored.append((node, score))
    scored.sort(key=lambda kv: -kv[1])
    top = scored[:TOP_K_RERANKED]

    # Relevance floor: drop weak tail items so the bundle (and the citation
    # chips built from it) only carries nodes that plausibly inform the
    # answer. Always keep a small minimum so retrieval degrades gracefully.
    floored = [(n, s) for n, s in top if s >= MIN_ITEM_SCORE]
    if len(floored) < MIN_BUNDLE_ITEMS:
        floored = top[:MIN_BUNDLE_ITEMS]

    # 6. Bundle.
    items = _build_bundle(floored, edges_by_node, seeds)
    return Retrieval(items=items, seed_node_ids=[s.id for s in seeds])


def system_prompt() -> str:
    return (
        "You are a helpful assistant grounded in the user's compiled "
        "knowledge graph. Answer the user's question using ONLY the "
        "context items below. Cite items by their citation_id in square "
        "brackets, e.g. ``[c3]``. Cite EVERY context item you actually "
        "draw on, and do not cite items you did not use — every factual "
        "claim should carry at least one such marker. If an item's "
        "edge_provenance is "
        "``inferred`` or ``ambiguous``, acknowledge that the connection "
        "is derived. When entity-layer items and theme-layer items agree "
        "on a point, prefer that point. If the context is insufficient, "
        "say so plainly — do not invent."
    )


def render_bundle(items: list[ContextItem]) -> str:
    """Format the bundle as a single string the chat model can read."""
    lines = []
    for it in items:
        layer_label = {0: "note", 1: "entity", 2: "tag/signal", 3: "region"}.get(it.layer, "node")
        prov = f" via={it.edge_provenance}" if it.edge_provenance else ""
        lines.append(
            f"[{it.citation_id}] type={it.node_type} layer={layer_label}{prov}"
        )
        lines.append(f"  label: {it.label}")
        if it.summary:
            lines.append(f"  summary: {it.summary}")
        if it.source_note_ids:
            lines.append(f"  source_note_ids: {', '.join(it.source_note_ids[:8])}")
        if it.raw_excerpts:
            lines.append("  source excerpts:")
            for excerpt in it.raw_excerpts:
                for excerpt_line in excerpt.splitlines():
                    lines.append(f"    {excerpt_line}")
        lines.append("")
    return "\n".join(lines).strip()


_CITATION_MARKER = re.compile(r"\[(c\d+)\]")


def extract_used_citations(text: str, valid_ids: set[str]) -> list[str]:
    """Return the citation ids the answer actually referenced, deduped in
    first-appearance order. Ids not in ``valid_ids`` (hallucinated markers
    like ``[c22]`` on a 5-item bundle) are dropped."""
    used: list[str] = []
    seen: set[str] = set()
    for cid in _CITATION_MARKER.findall(text or ""):
        if cid in valid_ids and cid not in seen:
            seen.add(cid)
            used.append(cid)
    return used


# ── helpers ──────────────────────────────────────────────────────────


def _index_edges(edges: Iterable[GraphEdge]) -> dict[str, list[GraphEdge]]:
    by_node: dict[str, list[GraphEdge]] = defaultdict(list)
    for e in edges:
        by_node[e.from_].append(e)
        by_node[e.to].append(e)
    return by_node


def _seed_entities(graph: GraphView, mentions: list[str]) -> list[GraphNode]:
    if not mentions:
        return []
    lowered = [m.lower() for m in mentions]
    out: list[GraphNode] = []
    for node in graph.nodes:
        if node.type != "entity":
            continue
        label = (node.label or "").lower()
        if any(m == label or m in label or label in m for m in lowered):
            out.append(node)
    return out


def _seed_tags(
    graph: GraphView, query_embedding: list[float], *, k: int
) -> list[GraphNode]:
    scored: list[tuple[GraphNode, float]] = []
    for node in graph.nodes:
        if node.type != "tag":
            continue
        score = _semantic_score(query_embedding, node)
        if score > 0:
            scored.append((node, score))
    scored.sort(key=lambda kv: -kv[1])
    return [n for n, _ in scored[:k]]


def _seed_chunk_notes(
    nodes_by_id: dict[str, GraphNode],
    chunk_hits: dict[str, float] | None,
    *,
    k: int,
) -> list[GraphNode]:
    """Seed note nodes whose raw chunks matched the query directly
    (ask_chunks search), best match first."""
    if not chunk_hits:
        return []
    ranked = sorted(chunk_hits.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[GraphNode] = []
    for node_id, _score in ranked[:k]:
        node = nodes_by_id.get(node_id)
        if node is not None and node.type == "note":
            out.append(node)
    return out


def _seed_regions(
    graph: GraphView, query_embedding: list[float], *, k: int
) -> list[GraphNode]:
    """Cosine-seed region nodes (layer 3). Regions carry the richest compiled
    summaries in the artifact; without an explicit seed they were unreachable
    (nothing hops *up* to them and ``contains`` wasn't walked)."""
    scored: list[tuple[GraphNode, float]] = []
    for node in graph.nodes:
        if node.type != "region":
            continue
        score = _semantic_score(query_embedding, node)
        if score > 0:
            scored.append((node, score))
    scored.sort(key=lambda kv: -kv[1])
    return [n for n, _ in scored[:k]]


def _seed_signals(
    graph: GraphView, query_embedding: list[float], *, k: int
) -> list[GraphNode]:
    scored: list[tuple[GraphNode, float]] = []
    for node in graph.nodes:
        if node.type != "signal":
            continue
        score = _semantic_score(query_embedding, node)
        if score > 0:
            # Severity nudges attention facts upward without letting low-quality
            # matches outrank strong semantic hits entirely.
            severity = float(node.severity or 0) / 100.0
            scored.append((node, score + 0.12 * severity))
    scored.sort(key=lambda kv: -kv[1])
    return [n for n, _ in scored[:k]]


def _edge_passes(edge: GraphEdge) -> bool:
    if edge.weight < MIN_EDGE_WEIGHT:
        return False
    floor = EDGE_CONFIDENCE_FLOORS.get(edge.type, MIN_EDGE_CONFIDENCE)
    return edge.confidence >= floor


def _within_layer_hop(
    seed: GraphNode,
    nodes_by_id: dict[str, GraphNode],
    edges_by_node: dict[str, list[GraphEdge]],
    *,
    k: int,
) -> list[GraphNode]:
    out: list[GraphNode] = []
    seen: set[str] = {seed.id}
    for edge in edges_by_node.get(seed.id, []):
        if not _edge_passes(edge):
            continue
        other_id = edge.to if edge.from_ == seed.id else edge.from_
        other = nodes_by_id.get(other_id)
        if other is None or other.id in seen or other.layer != seed.layer:
            continue
        seen.add(other.id)
        out.append(other)
        if len(out) >= k:
            break
    return out


def _cross_layer_hop(
    seed: GraphNode,
    nodes_by_id: dict[str, GraphNode],
    edges_by_node: dict[str, list[GraphEdge]],
) -> list[GraphNode]:
    out: list[GraphNode] = []
    seen: set[str] = {seed.id}
    for edge in edges_by_node.get(seed.id, []):
        if not _edge_passes(edge):
            continue
        if edge.type not in (
            "mentions", "belongs_to_theme", "belongs-to", "has-signal",
            "contains",  # region ↔ tag (edges are indexed bidirectionally)
        ):
            continue
        other_id = edge.to if edge.from_ == seed.id else edge.from_
        other = nodes_by_id.get(other_id)
        if other is None or other.id in seen:
            continue
        seen.add(other.id)
        out.append(other)
    return out


def _note_semantic_score(
    note: GraphNode,
    query_embedding: list[float],
    nodes_by_id: dict[str, GraphNode],
    edges_by_node: dict[str, list[GraphEdge]],
) -> float:
    """Derive a note's relevance from its best-scoring connected node.

    Notes have no embedding, so they inherit the strongest (embedding-bearing)
    neighbor's semantic score, scaled by the connecting edge weight and a fixed
    discount. This lets relevant source notes reach the top-K and be cited
    instead of scoring a flat 0."""
    best = 0.0
    for edge in edges_by_node.get(note.id, []):
        other_id = edge.to if edge.from_ == note.id else edge.from_
        other = nodes_by_id.get(other_id)
        if other is None or not (other.embedding or other.context_embedding):
            continue
        score = _semantic_score(query_embedding, other) * float(edge.weight)
        if score > best:
            best = score
    return best * NOTE_SEM_DISCOUNT


def _semantic_score(query_embedding: list[float], node: GraphNode) -> float:
    if not query_embedding:
        return 0.0
    raw = node.embedding or []
    ctx = node.context_embedding or raw
    if not raw and not ctx:
        return 0.0
    blended = _blend_embeddings(ctx, raw)
    return _cosine(query_embedding, blended)


def _blend_embeddings(ctx: list[float], raw: list[float]) -> list[float]:
    if not ctx:
        return raw
    if not raw or len(ctx) != len(raw):
        return ctx
    return [CONTEXT_BLEND * ctx[i] + (1.0 - CONTEXT_BLEND) * raw[i] for i in range(len(raw))]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _build_bundle(
    scored_nodes: list[tuple[GraphNode, float]],
    edges_by_node: dict[str, list[GraphEdge]],
    seeds: list[GraphNode],
) -> list[ContextItem]:
    seed_ids = {s.id for s in seeds}
    items: list[ContextItem] = []
    for i, (node, score) in enumerate(scored_nodes, 1):
        provenance: str | None = None
        if node.id not in seed_ids:
            # Find the strongest seed-to-node edge for provenance display.
            best: GraphEdge | None = None
            for edge in edges_by_node.get(node.id, []):
                other = edge.to if edge.from_ == node.id else edge.from_
                if other in seed_ids:
                    if best is None or edge.confidence > best.confidence:
                        best = edge
            if best is not None:
                provenance = best.provenance
        items.append(
            ContextItem(
                citation_id=f"c{i}",
                node_id=node.id,
                node_type=node.type,
                layer=node.layer,
                label=node.label,
                summary=(node.summary or "")[:1200],
                edge_provenance=provenance,
                source_note_ids=list(getattr(node, "sourceNoteIds", []) or []),
                source_chunk_ids=list(getattr(node, "sourceChunkIds", []) or []),
                score=round(float(score), 4),
                home_region_id=getattr(node, "homeRegionId", None),
            )
        )
    return items


def _dedupe_keep_order(items: list[GraphNode]) -> list[GraphNode]:
    seen: set[str] = set()
    out: list[GraphNode] = []
    for n in items:
        if n.id in seen:
            continue
        seen.add(n.id)
        out.append(n)
    return out
