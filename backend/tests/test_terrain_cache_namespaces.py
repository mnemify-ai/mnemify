"""Feature, name and compiled-note caches are keyed by AI backend + model.

Without this a Local-mode compile followed by an OpenAI-mode compile is a
100 % cache hit: the "AI" map is the heuristic one until ``fresh=True``.
"""
from __future__ import annotations

from src.terrain.pipelines.compiler import TerrainCompiler
from src.terrain.preprocessing.extractor import FeatureExtractor
from src.terrain.utils.embedder import LocalHashEmbeddingClient
from src.terrain.utils.namer import ClusterNamer
from src.terrain.utils.store import TerrainStore


def test_local_and_openai_feature_schema_versions_differ():
    from src.terrain.agents.openai_clients import OpenAIFeatureExtractor

    local = FeatureExtractor().schema_version
    oa1 = OpenAIFeatureExtractor(model="gpt-a").schema_version
    oa2 = OpenAIFeatureExtractor(model="gpt-b").schema_version
    assert len({local, oa1, oa2}) == 3
    assert local.startswith("local:") and oa1.startswith("openai-gpt-a:")


def test_name_fingerprint_depends_on_the_namer_model(tmp_path):
    from src.terrain.agents.openai_clients import OpenAIClusterNamer
    from tests.test_terrain_region_merger import enriched_chunk

    store = TerrainStore(tmp_path / "t.db")
    try:
        items = [enriched_chunk("c1", [1.0, 0.0], "alpha beta")]
        fp_local = ClusterNamer(store)._fingerprint(items, kind="region")
        fp_a = OpenAIClusterNamer(store, model="gpt-a")._fingerprint(items, kind="region")
        fp_b = OpenAIClusterNamer(store, model="gpt-b")._fingerprint(items, kind="region")
        assert len({fp_local, fp_a, fp_b}) == 3
        assert fp_a.startswith("fp_region_")  # prefix contract unchanged
    finally:
        store.close()


def test_compiled_note_version_carries_mode_and_model(tmp_path):
    store = TerrainStore(tmp_path / "t.db")
    try:
        local = TerrainCompiler(
            tmp_path, store=store, ai_mode="local",
            extractor=FeatureExtractor(), embedder=LocalHashEmbeddingClient(),
            namer=ClusterNamer(store),
        )._compile_prompt_version
        # An injected namer with a ``model`` attribute stands in for OpenAI.
        class _Namer(ClusterNamer):
            model = "gpt-x"
        openai = TerrainCompiler(
            tmp_path, store=store, ai_mode="openai",
            extractor=FeatureExtractor(), embedder=LocalHashEmbeddingClient(),
            namer=_Namer(store),
        )._compile_prompt_version
        assert local != openai
        assert local.endswith("|local|local") and openai.endswith("|openai|gpt-x")
    finally:
        store.close()
