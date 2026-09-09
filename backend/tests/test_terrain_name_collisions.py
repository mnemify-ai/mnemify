"""Sibling region names must be unique (post-naming collision pass) and
region-merger verdicts must be persisted for audit."""
from __future__ import annotations

from src.terrain import TerrainCompiler
from src.terrain.agents.openai_clients import ClusterName, OpenAIClusterNamer
from src.terrain.utils.models import ChunkFeatures, ClusterTreeNode, EnrichedChunk, TerrainChunk
from src.terrain.utils.region_merger import RegionMerger
from src.terrain.utils.store import TerrainStore


def _chunk(chunk_id: str, *, tags: list[str], embedding=(1.0, 0.0)) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id=chunk_id, doc_id=f"doc-{chunk_id}", source_type="confluence",
            source_id=f"src-{chunk_id}", doc_title=f"Doc {chunk_id}",
            content=" ".join(tags), content_hash=f"hash-{chunk_id}",
        ),
        features=ChunkFeatures(summary=" ".join(tags), tags=tags, entities=[tags[0].title()]),
        embedding=list(embedding),
    )


class _ScriptedResponses:
    """Returns the same generic name until the prompt carries avoid-names."""

    def __init__(self):
        self.calls: list[dict] = []

    def parse(self, **params):
        self.calls.append(params)
        user = params["input"][1]["content"]
        if "Names already used by sibling regions" in user:
            name = "Prompt Engineering" if "prompt" in user else "VLM Document Evaluation"
        else:
            name = "Document Intelligence"

        class R:  # noqa: D401 — minimal stand-in for the SDK response
            output_parsed = ClusterName(name=name, summary=f"about {name.lower()}")

        return R()


class _Stub:
    def __init__(self):
        self.responses = _ScriptedResponses()


def test_prompt_carries_avoid_names_and_fingerprint_changes():
    store = TerrainStore(":memory:")
    try:
        namer = OpenAIClusterNamer(store, model="gpt-test")
        stub = _Stub()
        namer._client = lambda: stub  # type: ignore[method-assign]
        items = [_chunk("a", tags=["ocr", "drawing"])]
        fp_plain = namer._fingerprint(items, kind="theme")
        fp_avoid = namer._fingerprint(items, kind="theme", extra=["avoid:Document Intelligence"])
        assert fp_plain != fp_avoid

        first, _ = namer.name_theme(items)
        second, _ = namer.name_theme(items, avoid_names=["Document Intelligence"])
    finally:
        store.close()
    assert first == "Document Intelligence"
    assert second != first
    prompt = stub.responses.calls[1]["input"][1]["content"]
    assert "Names already used by sibling regions" in prompt
    assert "Document Intelligence" in prompt
    # The tag-lens branch is untouched: plain calls carry no avoid block.
    assert "Names already used" not in stub.responses.calls[0]["input"][1]["content"]


def test_collision_pass_renames_smaller_sibling_once(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="openai")
    try:
        stub = _Stub()
        compiler.namer._client = lambda: stub  # type: ignore[method-assign]
        big = [_chunk(f"b{i}", tags=["ocr", "drawing"]) for i in range(5)]
        small = [_chunk(f"s{i}", tags=["prompt", "chunking"]) for i in range(2)]
        jobs = [
            {"key": "big", "items": big, "kind": "theme"},
            {"key": "small", "items": small, "kind": "theme"},
        ]
        results = compiler._name_jobs(jobs, cancel=None, on_resolve=lambda *_: None)
        assert results["big"][0] == results["small"][0] == "Document Intelligence"
        calls_before = len(stub.responses.calls)

        fixed, n = compiler._resolve_name_collisions(
            results, {j["key"]: j for j in jobs},
            groups=[(["big", "small"], [])],
            size_of=lambda key: {"big": 5, "small": 2}[key],
            cancel=None, progress=lambda _ev: None,
        )
    finally:
        compiler.store.close()
    assert n == 1
    assert fixed["big"][0] == "Document Intelligence"      # largest keeps the name
    assert fixed["small"][0] == "Prompt Engineering"
    assert len(stub.responses.calls) == calls_before + 1    # exactly one rename call


def test_collision_pass_respects_reserved_parent_name_and_falls_back(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    try:
        items = [_chunk("c", tags=["schema", "validation"])]
        results = {"region:c": ("Document Intelligence", "s")}
        fixed, n = compiler._resolve_name_collisions(
            results, {"region:c": {"key": "region:c", "items": items, "kind": "region"}},
            groups=[(["region:c"], ["Document Intelligence"])],   # parent owns the name
            size_of=lambda _k: 1, cancel=None, progress=lambda _ev: None,
        )
    finally:
        compiler.store.close()
    assert n >= 1
    assert fixed["region:c"][0].strip()
    assert fixed["region:c"][0].casefold() != "document intelligence"


def test_collision_pass_deterministic_suffix_when_namer_keeps_colliding(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    try:
        # Force the namer to return the contested label no matter what.
        compiler.namer.name_region = (  # type: ignore[method-assign]
            lambda items, fallback="Loose Notes", **_kw: ("Document Intelligence", "s")
        )
        items = [_chunk("c", tags=["schema", "validation"])]
        results = {"region:c": ("Document Intelligence", "s")}
        fixed, n = compiler._resolve_name_collisions(
            results, {"region:c": {"key": "region:c", "items": items, "kind": "region"}},
            groups=[(["region:c"], ["Document Intelligence"])],
            size_of=lambda _k: 1, cancel=None, progress=lambda _ev: None,
        )
    finally:
        compiler.store.close()
    assert n >= 1
    assert fixed["region:c"][0].startswith("Document Intelligence (")
    assert fixed["region:c"][0].casefold() != "document intelligence"


class _Judge:
    model = "fake"

    def judge_region_pair(self, *_a):
        return '{"decision": "keep_separate", "parent": null, "reason": "different pipelines"}'


def test_merger_reports_and_store_persists_verdicts():
    a = [_chunk(f"a{i}", tags=["ocr", "pdf"], embedding=(1.0, 0.0)) for i in range(3)]
    b = [_chunk(f"b{i}", tags=["ocr", "layout"], embedding=(0.9, 0.1)) for i in range(3)]
    roots = [
        ClusterTreeNode(id="ra", name="", chunk_ids=[c.chunk.id for c in a], children=[]),
        ClusterTreeNode(id="rb", name="", chunk_ids=[c.chunk.id for c in b], children=[]),
    ]
    seen = []
    RegionMerger(_Judge()).merge(roots, a + b, on_verdict=seen.append)
    assert len(seen) == 1
    v = seen[0]
    assert v.decision == "keep_separate" and v.similarity > 0.9
    assert v.a_label and v.b_label

    store = TerrainStore(":memory:")
    try:
        store.save_merger_verdicts("run1", [{
            "a_id": v.a_id, "b_id": v.b_id, "similarity": v.similarity,
            "decision": v.decision, "parent": v.parent, "reason": v.reason,
            "a_label": v.a_label, "b_label": v.b_label,
        }])
        rows = store.get_merger_verdicts("run1")
    finally:
        store.close()
    assert rows and rows[0]["decision"] == "keep_separate"
    assert rows[0]["reason"] == "different pipelines"
