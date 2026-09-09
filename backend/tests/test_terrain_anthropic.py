"""ai_mode="anthropic" (Messages API transport) + the fail-loud naming policy."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.terrain import TerrainCompiler
from src.terrain.agents import anthropic_clients
from src.terrain.agents.anthropic_clients import (
    AnthropicClusterNamer,
    AnthropicFeatureExtractor,
    resolve_model,
)
from src.terrain.agents.openai_clients import ClusterName
from src.terrain.preprocessing.extractor import FeatureExtractor
from src.terrain.utils.models import (
    ChunkFeatures,
    ClusterTreeNode,
    EnrichedChunk,
    SourceDocument,
    TerrainChunk,
)
from src.terrain.utils.namer import ClusterNamer
from src.terrain.utils.store import TerrainStore


def _enriched_chunk(cid: str, doc_id: str) -> EnrichedChunk:
    chunk = TerrainChunk(
        id=cid, doc_id=doc_id, source_type="notion", source_id=doc_id,
        doc_title=f"Doc {doc_id}", content=f"content {cid}", content_hash=f"h-{cid}",
    )
    features = ChunkFeatures(
        summary=f"summary {cid}", tags=[f"topic-{cid}"], entities=[f"ent-{cid}"],
        tag_type_hint="concept",
    )
    return EnrichedChunk(chunk=chunk, features=features, embedding=[0.1, 0.2, 0.3])


# ── mode wiring ─────────────────────────────────────────────────────


def test_anthropic_compiler_selects_anthropic_clients(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="anthropic")
    try:
        assert type(compiler.extractor) is AnthropicFeatureExtractor
        assert type(compiler.namer) is AnthropicClusterNamer
    finally:
        compiler.store.close()


def test_alias_resolution_maps_to_concrete_model_ids():
    assert resolve_model("opus", "sonnet") == "claude-opus-5"
    assert resolve_model("sonnet", "opus") == "claude-sonnet-5"
    assert resolve_model("haiku", "opus") == "claude-haiku-4-5"
    assert resolve_model(None, "opus") == "claude-opus-5"
    # A concrete id passes through untouched.
    assert resolve_model("claude-opus-4-8", "opus") == "claude-opus-4-8"


def test_anthropic_name_cache_is_namespaced():
    store = TerrainStore(":memory:")
    try:
        namer = AnthropicClusterNamer(store)
        fp = namer._fingerprint([_enriched_chunk("c1", "d1")], kind="region")
        assert fp.startswith("an_fp_region_")
    finally:
        store.close()


def test_anthropic_feature_cache_is_namespaced():
    extractor = AnthropicFeatureExtractor(model="sonnet")
    assert extractor.schema_version.startswith("anthropic-claude-sonnet-5:")


# ── shim transport ─────────────────────────────────────────────────


class _StubMessages:
    def __init__(self):
        self.parse_calls: list[dict] = []

    def parse(self, **params):
        self.parse_calls.append(params)
        return SimpleNamespace(
            parsed_output=ClusterName(name="Invoice Automation", summary="Groups invoices.")
        )


def test_shim_routes_openai_prompts_through_messages_parse(monkeypatch):
    stub = SimpleNamespace(messages=_StubMessages())
    monkeypatch.setattr(anthropic_clients, "_anthropic_client", lambda: stub)

    store = TerrainStore(":memory:")
    try:
        namer = AnthropicClusterNamer(store, model="opus")
        name, summary = namer.name_region([_enriched_chunk("c1", "d1")])
    finally:
        store.close()

    assert (name, summary) == ("Invoice Automation", "Groups invoices.")
    (call,) = stub.messages.parse_calls
    assert call["model"] == "claude-opus-5"  # alias resolved for the API
    assert call["output_format"] is ClusterName
    assert "Name a semantic region" in call["system"]  # OpenAI prompt reused
    assert call["messages"][0]["role"] == "user"


def test_anthropic_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(anthropic_clients, "_client", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        anthropic_clients._anthropic_client()


# ── fail-loud naming: no silent heuristic fallback ─────────────────


class _ExplodingNamer(ClusterNamer):
    """OpenAI-shaped namer (has ``_call_*`` → parallel path) whose LLM calls
    always fail — the compile must abort with an actionable error, never ship
    heuristic names."""

    def _call_theme(self, items, fallback: str = "General"):
        time.sleep(0.001)
        raise ConnectionError("provider down")

    def _call_region(self, items, fallback: str = "Loose Notes"):
        raise ConnectionError("provider down")

    def _call_tag(self, items, fallback: str = "General", *, region_name=None, region_terms=None):
        raise ConnectionError("provider down")


def test_naming_failure_aborts_build_with_actionable_error(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    compiler = TerrainCompiler(
        data_dir=tmp_path, store=store, ai_mode="local", namer=_ExplodingNamer(store)
    )
    documents = [
        SourceDocument(id="doc1", source_type="notion", source_id="doc1", title="Doc 1"),
    ]
    enriched = [_enriched_chunk("c1", "doc1")]
    root = ClusterTreeNode(id="R", chunk_ids=["c1"])

    try:
        with pytest.raises(RuntimeError, match="AI naming failed.*switch the AI engine to Local"):
            compiler._derive_tree(documents, enriched, [root], progress=lambda _ev: None)
    finally:
        store.close()


# ── heuristic extractor: no stopword entities ───────────────────────


def test_heuristic_entities_strip_sentence_start_stopwords():
    extractor = FeatureExtractor(products=())
    chunk = TerrainChunk(
        id="c1", doc_id="d1", source_type="notion", source_id="d1",
        doc_title="Doc", content_hash="h1",
        content=(
            "The Matterport scan arrived. This Kubernetes cluster is fine. "
            "The Matterport update shipped. This Kubernetes rollout works."
        ),
    )
    features = extractor.extract(chunk)
    assert "Matterport" in features.entities
    assert "Kubernetes" in features.entities
    assert all(
        not e.lower().startswith(("the ", "this ")) and e.lower() not in ("the", "this")
        for e in features.entities
    ), features.entities


def test_cache_model_tag_shares_namespace_between_alias_and_full_id():
    from src.terrain.agents.anthropic_clients import cache_model_tag, is_claude_model_ref

    assert cache_model_tag("sonnet", "opus") == "sonnet"
    assert cache_model_tag("claude-sonnet-5", "opus") == "sonnet"
    assert cache_model_tag(None, "opus") == "opus"
    # Unknown ids get their own namespace rather than colliding with an alias.
    assert cache_model_tag("claude-opus-4-7", "opus") == "claude-opus-4-7"

    assert is_claude_model_ref("opus")
    assert is_claude_model_ref("claude-fable-5-1")
    assert not is_claude_model_ref("gpt-5.6-terra")
    assert not is_claude_model_ref("")
    assert not is_claude_model_ref(None)
