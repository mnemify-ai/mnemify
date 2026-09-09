"""Unit coverage for the /api/ask retrieval + provider helpers.

These exercise the pure paths the broader suite never reaches: JSON parsing
of query-understanding output, the LLM/regex mention merge, note score
inheritance (so source notes can be cited), and the product cache-key suffix.
No network and no optional deps required.
"""

from __future__ import annotations

from src.api import ask_providers
from src.terrain.agents import claude_cli
from src.terrain.agents.openai_clients import OpenAIChunkFeatures
from src.api.ask_retrieval import (
    MIN_BUNDLE_ITEMS,
    _note_semantic_score,
    _resolve_mentions,
    extract_used_citations,
    retrieve,
)
from src.terrain.preprocessing.extractor import (
    SCHEMA_VERSION,
    products_schema_suffix,
)
from src.terrain.utils.models import GraphEdge, GraphNode, GraphView


# ── ask_providers._parse_json_object ────────────────────────────────


def test_parse_json_plain():
    assert ask_providers._parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    text = '```json\n{"nodeTypes": ["tag"], "mentions": []}\n```'
    assert ask_providers._parse_json_object(text) == {"nodeTypes": ["tag"], "mentions": []}


def test_parse_json_embedded_in_prose():
    text = 'Sure! Here you go: {"topicIntent": "ocr accuracy"} hope that helps'
    assert ask_providers._parse_json_object(text) == {"topicIntent": "ocr accuracy"}


def test_parse_json_garbage_returns_none():
    assert ask_providers._parse_json_object("not json at all") is None
    assert ask_providers._parse_json_object("") is None
    assert ask_providers._parse_json_object(None) is None


# ── ask_retrieval._resolve_mentions ─────────────────────────────────


def test_resolve_mentions_no_understanding_uses_regex():
    # "Project Phoenix" is a capitalized multi-word phrase the regex catches.
    out = _resolve_mentions("How is Project Phoenix doing?", None)
    assert any("Phoenix" in m for m in out)


def test_resolve_mentions_llm_priority_with_regex_backfill():
    understanding = {"mentions": ["Phoenix"], "nodeTypes": [], "topicIntent": ""}
    out = _resolve_mentions("How is Stripe billing for Phoenix?", understanding)
    # LLM mention comes first; regex-only catches (e.g. "Stripe") are appended.
    assert out[0] == "Phoenix"
    assert any(m.lower() == "stripe" for m in out)


def test_resolve_mentions_empty_llm_falls_back_to_regex():
    understanding = {"mentions": [], "nodeTypes": ["tag"], "topicIntent": "billing"}
    out = _resolve_mentions("How does Stripe work?", understanding)
    assert any(m.lower() == "stripe" for m in out)


# ── ask_retrieval._note_semantic_score ──────────────────────────────


def test_note_inherits_best_neighbor_score():
    note = GraphNode(id="n-1", type="note", label="Note A", layer=0)
    tag = GraphNode(id="tag.x", type="tag", label="OCR", layer=2, embedding=[1.0, 0.0])
    nodes_by_id = {"n-1": note, "tag.x": tag}
    edge = GraphEdge(**{"from": "n-1", "to": "tag.x", "type": "belongs-to",
                        "weight": 1.0, "provenance": "extracted", "confidence": 1.0})
    edges_by_node = {"n-1": [edge], "tag.x": [edge]}
    score = _note_semantic_score(note, [1.0, 0.0], nodes_by_id, edges_by_node)
    # tag cosine == 1.0, edge weight 1.0, discounted by NOTE_SEM_DISCOUNT (0.85).
    assert abs(score - 0.85) < 1e-6


def test_note_with_no_embedding_neighbors_scores_zero():
    note = GraphNode(id="n-1", type="note", label="Note A", layer=0)
    other = GraphNode(id="n-2", type="note", label="Note B", layer=0)  # no embedding
    nodes_by_id = {"n-1": note, "n-2": other}
    edge = GraphEdge(**{"from": "n-1", "to": "n-2", "type": "belongs-to",
                        "weight": 1.0, "provenance": "extracted", "confidence": 1.0})
    edges_by_node = {"n-1": [edge], "n-2": [edge]}
    assert _note_semantic_score(note, [1.0, 0.0], nodes_by_id, edges_by_node) == 0.0


# ── ask_retrieval.retrieve (small hand-built graph) ──────────────────


def _tiny_graph() -> GraphView:
    tag = GraphNode(id="tag.ocr", type="tag", label="OCR", layer=2, embedding=[1.0, 0.0])
    note = GraphNode(id="n-1", type="note", label="OCR design doc", layer=0,
                     summary="Notes about OCR accuracy.", centrality=1.0)
    entity = GraphNode(id="ent.phoenix", type="entity", entityType="project",
                       label="Phoenix", layer=1, embedding=[0.0, 1.0])
    edges = [
        GraphEdge(**{"from": "n-1", "to": "tag.ocr", "type": "belongs-to",
                     "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
        GraphEdge(**{"from": "ent.phoenix", "to": "tag.ocr", "type": "belongs_to_theme",
                     "weight": 0.8, "provenance": "inferred", "confidence": 0.9}),
    ]
    return GraphView(nodes=[tag, note, entity], edges=edges)


def test_retrieve_surfaces_citable_note():
    """A note connected to a relevant tag must reach the bundle and get a
    citation id — previously it scored 0 and could never be cited."""
    result = retrieve("ocr", [1.0, 0.0], _tiny_graph())
    note_items = [it for it in result.items if it.node_type == "note"]
    assert note_items, "note should be retrievable/citable"
    assert note_items[0].citation_id.startswith("c")


def test_retrieve_seeds_entity_from_understanding_mention():
    understanding = {"mentions": ["Phoenix"], "nodeTypes": ["entity"], "topicIntent": "phoenix"}
    result = retrieve("tell me about it", [0.0, 1.0], _tiny_graph(),
                      understanding=understanding)
    assert "ent.phoenix" in result.seed_node_ids


def test_retrieve_seeds_attention_signal_and_keeps_sources():
    signal = GraphNode(
        id="signal.risk.1",
        type="signal",
        label="Risk: contract renewal",
        summary="risk renewal blocker contract",
        layer=2,
        embedding=[1.0, 0.0],
        signalKind="risk",
        severity=90,
        sourceNoteIds=["n-1"],
        sourceChunkIds=["c-1"],
    )
    note = GraphNode(id="n-1", type="note", label="Renewal note", layer=0)
    edge = GraphEdge(**{"from": "n-1", "to": "signal.risk.1", "type": "has-signal",
                        "weight": 1.0, "provenance": "extracted", "confidence": 1.0})
    graph = GraphView(nodes=[signal, note], edges=[edge])

    result = retrieve("what is burning", [1.0, 0.0], graph)

    assert "signal.risk.1" in result.seed_node_ids
    signal_items = [it for it in result.items if it.node_type == "signal"]
    assert signal_items
    assert signal_items[0].source_note_ids == ["n-1"]


# ── ask_retrieval.extract_used_citations ─────────────────────────────


def test_extract_used_citations_dedupes_in_order():
    text = "Per [c3] and [c1], the API is stable [c3]."
    assert extract_used_citations(text, {"c1", "c2", "c3"}) == ["c3", "c1"]


def test_extract_used_citations_drops_hallucinated_ids():
    assert extract_used_citations("see [c22]", {"c1", "c2"}) == []


def test_extract_used_citations_empty_text():
    assert extract_used_citations("", {"c1"}) == []
    assert extract_used_citations(None, {"c1"}) == []


# ── region reachability ──────────────────────────────────────────────


def test_retrieve_seeds_region_by_cosine():
    region = GraphNode(id="region.arch", type="region", label="Architecture",
                       layer=3, embedding=[1.0, 0.0],
                       summary="Compiled region note about architecture.")
    tag = GraphNode(id="tag.misc", type="tag", label="Misc", layer=2,
                    embedding=[0.0, 1.0])
    graph = GraphView(nodes=[region, tag], edges=[])
    result = retrieve("architecture overview", [1.0, 0.0], graph)
    assert "region.arch" in result.seed_node_ids
    assert any(it.node_type == "region" for it in result.items)


def test_retrieve_reaches_region_via_contains_hop():
    """A region with no usable embedding must still be reachable from a tag
    seed through its ``contains`` edge (previously filtered out)."""
    tag = GraphNode(id="tag.ocr", type="tag", label="OCR", layer=2,
                    embedding=[1.0, 0.0])
    region = GraphNode(id="region.docs", type="region", label="Docs", layer=3,
                       summary="Compiled region note.")
    edge = GraphEdge(**{"from": "region.docs", "to": "tag.ocr", "type": "contains",
                        "weight": 1.0, "provenance": "extracted", "confidence": 1.0})
    graph = GraphView(nodes=[tag, region], edges=[edge])
    result = retrieve("ocr", [1.0, 0.0], graph)
    assert any(it.node_id == "region.docs" for it in result.items)


# ── rerank: scores, floor, renormalization, cap, nodeTypes boost ─────


def test_retrieve_items_carry_descending_scores():
    result = retrieve("ocr", [1.0, 0.0], _tiny_graph())
    scores = [it.score for it in result.items]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 0


def test_retrieve_weights_renormalized_without_affinity():
    """With user_affinity absent, the three live weights renormalize to 1 —
    a perfect semantic match on an isolated node scores 0.55/0.80."""
    tag = GraphNode(id="tag.only", type="tag", label="Only", layer=2,
                    embedding=[1.0, 0.0], centrality=0.0)
    graph = GraphView(nodes=[tag], edges=[])
    result = retrieve("only", [1.0, 0.0], graph)
    assert abs(result.items[0].score - 0.55 / 0.80) < 1e-3


def test_retrieve_score_floor_drops_weak_tail():
    strong = [
        GraphNode(id=f"tag.s{i}", type="tag", label=f"Strong {i}", layer=2,
                  embedding=[1.0, 0.01 * i])
        for i in range(4)
    ]
    # Weak tags still seed (cosine > 0) but land under MIN_ITEM_SCORE.
    weak = GraphNode(id="tag.weak", type="tag", label="Weak", layer=2,
                     embedding=[0.01, 1.0])
    graph = GraphView(nodes=strong + [weak], edges=[])
    result = retrieve("strong", [1.0, 0.0], graph)
    ids = [it.node_id for it in result.items]
    assert "tag.weak" not in ids
    assert len(ids) == 4


def test_retrieve_keeps_minimum_bundle_when_all_weak():
    weak = [
        GraphNode(id=f"tag.w{i}", type="tag", label=f"Weak {i}", layer=2,
                  embedding=[0.01, 1.0 + 0.01 * i])
        for i in range(5)
    ]
    graph = GraphView(nodes=weak, edges=[])
    result = retrieve("unrelated", [1.0, 0.0], graph)
    assert len(result.items) == MIN_BUNDLE_ITEMS


def test_retrieve_candidate_cap_keeps_late_strong_node():
    """When the candidate pool overflows CANDIDATE_CAP, non-seed slots are
    filled by semantic score — a strong node walked late must survive
    (previously insertion-order truncation dropped it)."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    # 11 layer-2 seeds (5 tags by cosine + 6 signals), each with 5 weak
    # within-layer neighbors → 66 candidates, well over the cap of 40.
    seeds = []
    for i in range(5):
        seeds.append(GraphNode(id=f"tag.seed{i}", type="tag", label=f"Seed {i}",
                               layer=2, embedding=[0.9, 0.1]))
    for i in range(6):
        seeds.append(GraphNode(id=f"signal.seed{i}", type="signal",
                               label=f"Signal {i}", layer=2,
                               embedding=[0.8, 0.2], signalKind="risk"))
    nodes.extend(seeds)
    neighbor_count = 0
    for seed in seeds:
        for j in range(5):
            neighbor_count += 1
            nid = f"tag.n{neighbor_count}"
            # The very last neighbor walked is the strong one.
            emb = [1.0, 0.0] if (seed.id == "tag.seed4" and j == 4) else [0.05, 1.0]
            if emb == [1.0, 0.0]:
                nid = "tag.late.strong"
            nodes.append(GraphNode(id=nid, type="tag", label=nid, layer=2,
                                   embedding=emb))
            edges.append(GraphEdge(**{
                "from": seed.id, "to": nid, "type": "linked-to",
                "weight": 1.0, "provenance": "extracted", "confidence": 1.0,
            }))
    graph = GraphView(nodes=nodes, edges=edges)
    result = retrieve("query", [1.0, 0.0], graph)
    assert any(it.node_id == "tag.late.strong" for it in result.items)


def test_retrieve_node_type_boost_flips_near_tie():
    tag = GraphNode(id="tag.a", type="tag", label="Billing", layer=2,
                    embedding=[1.0, 0.0], centrality=0.0)
    entity = GraphNode(id="ent.stripe", type="entity", entityType="product",
                       label="Stripe", layer=1, embedding=[0.99, 0.1],
                       centrality=0.0)
    graph = GraphView(nodes=[tag, entity], edges=[])
    hint = {"mentions": ["Stripe"], "nodeTypes": ["entity"], "topicIntent": ""}
    boosted = retrieve("stripe billing", [1.0, 0.0], graph, understanding=hint)
    assert boosted.items[0].node_type == "entity"
    plain = retrieve("stripe billing", [1.0, 0.0], graph,
                     understanding={"mentions": ["Stripe"], "nodeTypes": [], "topicIntent": ""})
    assert plain.items[0].node_type == "tag"


# ── chunk-hit note seeding + lateral edge floors ─────────────────────


def _sibling_notes_graph() -> GraphView:
    """One tag with two sibling notes — inherited scoring can't tell them
    apart; a chunk hit must."""
    tag = GraphNode(id="tag.ocr", type="tag", label="OCR", layer=2,
                    embedding=[1.0, 0.0])
    note_a = GraphNode(id="n-aaaa", type="note", label="Right note", layer=0)
    note_b = GraphNode(id="n-bbbb", type="note", label="Sibling note", layer=0)
    edges = [
        GraphEdge(**{"from": n.id, "to": "tag.ocr", "type": "belongs-to",
                     "weight": 1.0, "provenance": "extracted", "confidence": 1.0})
        for n in (note_a, note_b)
    ]
    return GraphView(nodes=[tag, note_a, note_b], edges=edges)


def test_chunk_hit_seeds_note_and_breaks_sibling_tie():
    result = retrieve("ocr detail", [1.0, 0.0], _sibling_notes_graph(),
                      chunk_hits={"n-aaaa": 0.95})
    assert "n-aaaa" in result.seed_node_ids
    notes = [it for it in result.items if it.node_type == "note"]
    assert notes[0].node_id == "n-aaaa"
    assert notes[0].score > notes[1].score


def test_chunk_hits_for_unknown_nodes_are_ignored():
    result = retrieve("ocr", [1.0, 0.0], _sibling_notes_graph(),
                      chunk_hits={"n-gone": 0.9})
    assert "n-gone" not in result.seed_node_ids


def test_linked_to_edges_are_now_walkable():
    """`linked-to` is emitted at confidence 0.5 — below the old uniform 0.6
    gate. The per-type floor must let it through."""
    seed_tag = GraphNode(id="tag.a", type="tag", label="Billing", layer=2,
                         embedding=[1.0, 0.0])
    linked = GraphNode(id="tag.b", type="tag", label="Invoices", layer=2,
                       embedding=[0.2, 0.9])
    edge = GraphEdge(**{"from": "tag.a", "to": "tag.b", "type": "linked-to",
                        "weight": 0.5, "provenance": "inferred", "confidence": 0.5})
    graph = GraphView(nodes=[seed_tag, linked], edges=[edge])
    result = retrieve("billing", [1.0, 0.0], graph)
    assert any(it.node_id == "tag.b" for it in result.items)


def test_low_confidence_extracted_edges_still_gated():
    seed_tag = GraphNode(id="tag.a", type="tag", label="Billing", layer=2,
                         embedding=[1.0, 0.0])
    weak = GraphNode(id="tag.c", type="tag", label="Noise", layer=2)
    edge = GraphEdge(**{"from": "tag.a", "to": "tag.c", "type": "co-occurs",
                        "weight": 0.4, "provenance": "inferred", "confidence": 0.4})
    graph = GraphView(nodes=[seed_tag, weak], edges=[edge])
    result = retrieve("billing", [1.0, 0.0], graph)
    assert not any(it.node_id == "tag.c" for it in result.items)


# ── extractor.products_schema_suffix ─────────────────────────────────


def test_products_suffix_empty_is_blank():
    assert products_schema_suffix(()) == ""
    assert products_schema_suffix(None) == ""
    assert products_schema_suffix(["", "  "]) == ""


def test_products_suffix_stable_across_order_and_case():
    a = products_schema_suffix(["Stripe", "OCR"])
    b = products_schema_suffix(["ocr", "stripe"])
    assert a == b and a.startswith(":")


# ── claude_cli pure helpers (no subprocess) ─────────────────────────


def test_claude_extract_json_object():
    assert claude_cli.extract_json_object('{"a": 1}') == {"a": 1}
    assert claude_cli.extract_json_object('```json\n{"b": 2}\n```') == {"b": 2}
    assert claude_cli.extract_json_object("prose then {\"c\": 3} tail") == {"c": 3}
    assert claude_cli.extract_json_object("no json") is None
    assert claude_cli.extract_json_object("") is None


def test_claude_schema_hint_enumerates_literals():
    hint = claude_cli.schema_hint(OpenAIChunkFeatures)
    # The Literal tag_type_hint must spell out its allowed values so the model
    # doesn't return an out-of-enum string.
    assert "tag_type_hint" in hint
    assert "one of:" in hint
    assert "product" in hint and "person" in hint
    # List fields are described as arrays, scalars by name.
    assert "array of" in hint


def test_products_suffix_distinguishes_sets():
    assert products_schema_suffix(["Stripe"]) != products_schema_suffix(["OCR"])
    # And combines cleanly onto the schema version.
    assert (SCHEMA_VERSION + products_schema_suffix(["Stripe"])).startswith(SCHEMA_VERSION + ":")
