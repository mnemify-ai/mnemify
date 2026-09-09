from __future__ import annotations

from src.terrain import TerrainCompiler
from src.terrain.agents.openai_clients import ClusterName, OpenAIClusterNamer, TagName
from src.terrain.utils.models import ChunkFeatures, EnrichedChunk, TerrainChunk
from src.terrain.utils.namer import ClusterNamer
from src.terrain.utils.store import TerrainStore


def enriched_chunk(
    chunk_id: str,
    *,
    summary: str = "Invoice extraction for ACME supplier documents",
    tags: list[str] | None = None,
) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id=chunk_id,
            doc_id=f"doc-{chunk_id}",
            source_type="notion",
            source_id=f"source-{chunk_id}",
            doc_title=f"Doc {chunk_id}",
            content=summary,
            content_hash=f"hash-{chunk_id}",
        ),
        features=ChunkFeatures(
            summary=summary,
            products=[],
            customers=["ACME"],
            entities=["SAP"],
            tags=tags or ["invoice extraction", "accounts payable"],
            theme="Document Intelligence",
            subtopic="Invoice Extraction",
        ),
        embedding=[1.0, 0.0],
    )


class _ParsedResponse:
    def __init__(self, parsed):
        self.output_parsed = parsed


class _Responses:
    def __init__(self):
        self.calls: list[dict] = []

    def parse(self, **params):
        self.calls.append(params)
        text_format = params["text_format"]
        if text_format is TagName:
            return _ParsedResponse(
                TagName(label="Invoice QA", blurb="invoice extraction quality signals")
            )
        return _ParsedResponse(
            ClusterName(
                name="Invoice Automation",
                summary="Groups invoice extraction and review work.",
            )
        )


class _OpenAIStub:
    def __init__(self):
        self.responses = _Responses()


def test_openai_namer_uses_responses_parse_for_region_names():
    store = TerrainStore(":memory:")
    try:
        namer = OpenAIClusterNamer(store, model="gpt-test")
        stub = _OpenAIStub()
        namer._client = lambda: stub  # type: ignore[method-assign]

        name, summary = namer.name_region([enriched_chunk("a")])
    finally:
        store.close()

    assert name == "Invoice Automation"
    assert summary == "Groups invoice extraction and review work."
    assert len(stub.responses.calls) == 1
    assert stub.responses.calls[0]["model"] == "gpt-test"
    assert stub.responses.calls[0]["text_format"] is ClusterName
    assert "Name a semantic region" in stub.responses.calls[0]["input"][0]["content"]


def test_openai_namer_uses_responses_parse_for_theme_and_tag_names():
    store = TerrainStore(":memory:")
    try:
        namer = OpenAIClusterNamer(store, model="gpt-test")
        stub = _OpenAIStub()
        namer._client = lambda: stub  # type: ignore[method-assign]

        theme, _theme_summary = namer.name_theme([enriched_chunk("a")])
        tag, tag_blurb = namer.name_tag(
            [enriched_chunk("b")],
            region_name="Document Intelligence",
            region_terms=["ACME", "SAP"],
        )
    finally:
        store.close()

    assert theme == "Invoice Automation"
    assert tag == "Invoice QA"
    assert tag_blurb == "invoice extraction quality signals"
    assert [call["text_format"] for call in stub.responses.calls] == [ClusterName, TagName]
    assert "Name a root knowledge theme" in stub.responses.calls[0]["input"][0]["content"]
    assert "Name a tag" in stub.responses.calls[1]["input"][0]["content"]


def test_openai_namer_caches_model_output_by_fingerprint():
    store = TerrainStore(":memory:")
    try:
        namer = OpenAIClusterNamer(store, model="gpt-test")
        stub = _OpenAIStub()
        namer._client = lambda: stub  # type: ignore[method-assign]
        items = [enriched_chunk("a")]

        first = namer.name_region(items)
        second = namer.name_region(items)
    finally:
        store.close()

    assert first == second
    assert len(stub.responses.calls) == 1


def test_openai_compiler_selects_openai_namer(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="openai")
    try:
        assert type(compiler.namer) is OpenAIClusterNamer
    finally:
        compiler.store.close()


def test_local_compiler_keeps_heuristic_namer(tmp_path):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    try:
        assert type(compiler.namer) is ClusterNamer
    finally:
        compiler.store.close()
