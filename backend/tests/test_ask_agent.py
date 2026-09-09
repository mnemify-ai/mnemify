"""Unit coverage for the agentic /api/ask path (ask_agent.py): citation
registry, raw tool handlers, and the session runner with the Claude Agent
SDK faked at the `_sdk_query` seam. No network, no CLI subprocess."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from src.api import ask_agent
from src.api.ask_agent import AgentContext, CitationRegistry
from src.api.ask_retrieval import ContextItem
from src.terrain.utils.models import GraphEdge, GraphNode, GraphView
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash


class _StubEmbedder:
    def __init__(self, vector):
        self._vector = vector

    def embed(self, text: str):
        if isinstance(self._vector, Exception):
            raise self._vector
        return self._vector


def _item(node_id: str, **kwargs) -> ContextItem:
    defaults = dict(
        citation_id="", node_type="tag", layer=2, label=node_id, summary="s"
    )
    defaults.update(kwargs)
    return ContextItem(node_id=node_id, **defaults)


def _graph() -> GraphView:
    doc_note_id = f"n-{short_hash('doc-a', 8)}"
    return GraphView(
        nodes=[
            GraphNode(id="r1", type="region", label="Payments", layer=3,
                      summary="Payment infrastructure region.",
                      embedding=[1.0, 0.0]),
            GraphNode(id="tag.a", type="tag", label="Alpha", layer=2,
                      summary="Alpha theme", embedding=[1.0, 0.0],
                      centrality=2.0, homeRegionId="r1"),
            GraphNode(id="tag.b", type="tag", label="Beta", layer=2,
                      summary="Beta theme", embedding=[0.9, 0.1],
                      centrality=1.0, homeRegionId="r1"),
            GraphNode(id=doc_note_id, type="note", label="ADR-024", layer=0,
                      summary="excerpt…", sourceChunkIds=["ch-1", "ch-2"]),
        ],
        edges=[
            GraphEdge(**{"from": "r1", "to": "tag.a", "type": "contains",
                         "weight": 1.0, "provenance": "extracted",
                         "confidence": 1.0}),
            GraphEdge(**{"from": doc_note_id, "to": "tag.a",
                         "type": "belongs-to", "weight": 1.0,
                         "provenance": "extracted", "confidence": 1.0}),
            # Below the weight floor — must be filtered out of explore_node.
            GraphEdge(**{"from": "tag.a", "to": "tag.b", "type": "co-occurs",
                         "weight": 0.1, "provenance": "inferred",
                         "confidence": 0.3}),
        ],
    )


def _ctx(tmp_path, vector=(1.0, 0.0), with_db=False) -> AgentContext:
    db_path = tmp_path / "terrain.db"
    if with_db:
        store = TerrainStore(db_path)
        from src.terrain.utils.models import TerrainChunk

        store.upsert_chunks([
            TerrainChunk(
                id="ch-1", doc_id="doc-a", source_type="notion",
                source_id="src-1", doc_title="ADR-024",
                heading_path=["Decision"],
                content="We moved ACH processing off Sidekiq.",
                content_hash="sha256:ch-1",
            ),
            TerrainChunk(
                id="ch-2", doc_id="doc-a", source_type="notion",
                source_id="src-1", doc_title="ADR-024",
                heading_path=["Context"],
                content="Batches ran through the shared queue.",
                content_hash="sha256:ch-2",
            ),
        ])
        store.close()
    vec = vector if isinstance(vector, Exception) else list(vector)
    return AgentContext(
        knowledge_map=SimpleNamespace(workspace="w", graph=_graph()),
        embedder=_StubEmbedder(vec),
        db_path=db_path,
    )


def _drain(ctx: AgentContext) -> list[tuple[str, dict]]:
    out = []
    while not ctx.queue.empty():
        item = ctx.queue.get_nowait()
        out.append((item["event"], item["data"]))
    return out


# ── CitationRegistry ─────────────────────────────────────────────────


def test_registry_assigns_stable_ids_and_dedupes():
    reg = CitationRegistry()
    a, b = _item("n1"), _item("n2")
    assert reg.register(a) == "c1"
    assert reg.register(b) == "c2"
    # Same node again (fresh item object) → same id, rewritten in place.
    a2 = _item("n1")
    assert reg.register(a2) == "c1"
    assert a2.citation_id == "c1"
    assert [c["citation_id"] for c in reg.snapshot()] == ["c1", "c2"]
    assert reg.valid_ids() == {"c1", "c2"}


def test_registry_adopts_later_excerpts():
    reg = CitationRegistry()
    reg.register(_item("n1"))
    richer = _item("n1", raw_excerpts=["[Doc] text"])
    reg.register(richer)
    # snapshot metadata comes from the first registration; excerpts adopted.
    assert reg._items["n1"].raw_excerpts == ["[Doc] text"]


# ── tool handlers ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terrain_overview_lists_regions_and_tags(tmp_path):
    ctx = _ctx(tmp_path)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["terrain_overview"]({})
    text = result["content"][0]["text"]
    assert "Payments" in text
    assert "Alpha" in text
    events = _drain(ctx)
    statuses = [d["status"] for e, d in events if e == "agent_step"]
    assert statuses == ["running", "done"]


@pytest.mark.asyncio
async def test_retrieve_context_registers_and_renders_registry_ids(tmp_path):
    ctx = _ctx(tmp_path)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["retrieve_context"]({"query": "Alpha things"})
    text = result["content"][0]["text"]
    assert "[c1]" in text
    events = _drain(ctx)
    citation_events = [d for e, d in events if e == "citations"]
    assert citation_events, "cumulative citations must be emitted"
    assert citation_events[-1]["citations"][0]["citation_id"] == "c1"

    # Second call: same nodes keep their ids — no c1 collision/reset.
    first_ids = {c["citation_id"] for c in citation_events[-1]["citations"]}
    await handlers["retrieve_context"]({"query": "Beta things"})
    events = _drain(ctx)
    final = [d for e, d in events if e == "citations"][-1]["citations"]
    final_ids = [c["citation_id"] for c in final]
    assert len(final_ids) == len(set(final_ids))
    assert first_ids <= set(final_ids)


@pytest.mark.asyncio
async def test_retrieve_context_dim_mismatch_returns_error_text(tmp_path):
    ctx = _ctx(tmp_path, vector=(1.0, 0.0, 0.0))  # 3-dim vs 2-dim graph
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["retrieve_context"]({"query": "Alpha"})
    assert result["content"][0]["text"].startswith("ERROR:")
    assert "dimension" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_retrieve_context_embed_failure_without_seeds(tmp_path):
    ctx = _ctx(tmp_path, vector=RuntimeError("boom"))
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["retrieve_context"]({"query": "hello there"})
    assert result["content"][0]["text"].startswith("ERROR:")


@pytest.mark.asyncio
async def test_explore_node_resolves_label_and_filters_edges(tmp_path):
    ctx = _ctx(tmp_path)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["explore_node"]({"node_ref": "alpha"})
    text = result["content"][0]["text"]
    assert text.startswith("[c1] Alpha")
    assert "Payments" in text  # contains edge passes
    assert "Beta" not in text  # weight-0.1 co-occurs edge filtered


@pytest.mark.asyncio
async def test_explore_node_unknown_ref_errors(tmp_path):
    ctx = _ctx(tmp_path)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["explore_node"]({"node_ref": "zzz-nothing"})
    assert result["content"][0]["text"].startswith("ERROR:")


@pytest.mark.asyncio
async def test_read_chunks_by_node_ref_registers_note(tmp_path):
    ctx = _ctx(tmp_path, with_db=True)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["read_chunks"]({"node_ref": "ADR-024"})
    text = result["content"][0]["text"]
    assert "ACH processing" in text
    assert "[c1]" in text  # parent note registered and prefixed
    events = _drain(ctx)
    assert any(e == "citations" for e, _ in events)


@pytest.mark.asyncio
async def test_read_chunks_without_ids_errors(tmp_path):
    ctx = _ctx(tmp_path, with_db=True)
    handlers = ask_agent.build_tool_handlers(ctx)
    result = await handlers["read_chunks"]({})
    assert result["content"][0]["text"].startswith("ERROR:")


# ── session runner (SDK faked at the _sdk_query seam) ────────────────


def _mk(cls, **over):
    """Construct an SDK dataclass supplying inert values for fields that
    have no default."""
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in over:
            kwargs[f.name] = over[f.name]
        elif (
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
        ):
            kwargs[f.name] = None
    return cls(**kwargs)


def _stream_event(text: str):
    from claude_agent_sdk import StreamEvent

    return _mk(
        StreamEvent,
        event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text},
        },
        parent_tool_use_id=None,
    )


def _run_session(monkeypatch, messages, registry_seed=None):
    async def _fake_query(*, prompt, options):
        for m in messages:
            yield m

    monkeypatch.setattr(ask_agent, "_sdk_query", _fake_query)

    async def collect():
        out = []
        gen = ask_agent.run_agent_session(
            query_text="q",
            history=[],
            provider="claude",
            model="sonnet",
            key=None,
            knowledge_map=SimpleNamespace(workspace="w", graph=_graph()),
            embedder=_StubEmbedder([1.0, 0.0]),
        )
        async for ev in gen:
            out.append((ev["event"], json.loads(ev["data"])))
        return out

    return collect


@pytest.mark.asyncio
async def test_runner_streams_deltas_and_terminal_sequence(monkeypatch):
    from claude_agent_sdk import ResultMessage

    msgs = [
        _stream_event("Hello "),
        _stream_event("[c1]."),
        _mk(ResultMessage, subtype="success", is_error=False),
    ]
    events = await _run_session(monkeypatch, msgs)()
    names = [n for n, _ in events]
    assert names == ["delta", "delta", "citations_used", "done"]
    deltas = "".join(d["text"] for n, d in events if n == "delta")
    assert deltas == "Hello [c1]."
    used = dict(events)["citations_used"]
    # Registry is empty (no tools ran) → the [c1] marker is hallucinated.
    assert used == {"used": [], "fallback": False}


@pytest.mark.asyncio
async def test_runner_falls_back_to_message_level_text(monkeypatch):
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    msgs = [
        _mk(AssistantMessage, content=[TextBlock(text="Whole answer.")],
            model="m"),
        _mk(ResultMessage, subtype="success", is_error=False),
    ]
    events = await _run_session(monkeypatch, msgs)()
    names = [n for n, _ in events]
    assert names == ["delta", "citations_used", "done"]
    assert dict(events)["delta"]["text"] == "Whole answer."


@pytest.mark.asyncio
async def test_runner_thread_mode_bridges_events(monkeypatch):
    """When the host loop can't spawn subprocesses (Windows selector loop,
    e.g. uvicorn --reload), the session runs on a dedicated loop in a
    worker thread and events must still arrive in order."""
    from claude_agent_sdk import ResultMessage

    monkeypatch.setattr(ask_agent, "_loop_supports_subprocess", lambda: False)
    msgs = [
        _stream_event("Bridged "),
        _stream_event("answer."),
        _mk(ResultMessage, subtype="success", is_error=False),
    ]
    events = await _run_session(monkeypatch, msgs)()
    names = [n for n, _ in events]
    assert names == ["delta", "delta", "citations_used", "done"]
    deltas = "".join(d["text"] for n, d in events if n == "delta")
    assert deltas == "Bridged answer."


@pytest.mark.asyncio
async def test_runner_cli_missing_yields_actionable_error(monkeypatch):
    from claude_agent_sdk import CLINotFoundError

    async def _fake_query(*, prompt, options):
        raise CLINotFoundError("claude not found")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(ask_agent, "_sdk_query", _fake_query)

    out = []
    gen = ask_agent.run_agent_session(
        query_text="q", history=[], provider="claude", model="sonnet",
        key=None,
        knowledge_map=SimpleNamespace(workspace="w", graph=_graph()),
        embedder=_StubEmbedder([1.0, 0.0]),
    )
    async for ev in gen:
        out.append((ev["event"], json.loads(ev["data"])))
    assert [n for n, _ in out] == ["error"]
    assert "Claude Code CLI" in out[0][1]["message"]


def test_render_prompt_includes_capped_history():
    prompt = ask_agent._render_prompt(
        "now?", [{"role": "user", "content": "earlier"},
                 {"role": "assistant", "content": "answer"}]
    )
    assert "<conversation_history>" in prompt
    assert "user: earlier" in prompt
    assert prompt.rstrip().endswith("Current question: now?")
    # History over the cap drops oldest turns first.
    long_history = [
        {"role": "user", "content": f"turn {i} " + "x" * 500}
        for i in range(40)
    ]
    capped = ask_agent._render_prompt("q", long_history)
    assert "turn 0" not in capped
    assert "turn 39" in capped


# ── pulse ids (agent steps → map highlight) ──────────────────────────


def test_pulse_ids_maps_nodes_to_their_regions():
    """Region items pulse themselves; everything else pulses its home
    region, which is the only thing the map draws a medallion for."""
    items = [
        _item("node_region", node_type="region", home_region_id=None),
        _item("node_note", node_type="note", home_region_id="node_home"),
        _item("node_tag", node_type="tag", home_region_id="node_home"),  # dupe
    ]
    assert ask_agent._pulse_ids(items) == ["node_region", "node_home"]


def test_pulse_ids_skips_homeless_nodes_and_caps():
    assert ask_agent._pulse_ids([_item("node_x", node_type="note")]) == []
    many = [
        _item(f"node_{i}", node_type="note", home_region_id=f"r{i}")
        for i in range(ask_agent.PULSE_ID_CAP + 5)
    ]
    assert len(ask_agent._pulse_ids(many)) == ask_agent.PULSE_ID_CAP


def test_node_pulse_ids_prefers_self_for_regions():
    region = GraphNode(
        id="node_r", type="region", layer=3, label="R", homeRegionId=None
    )
    note = GraphNode(
        id="node_n", type="note", layer=0, label="N", homeRegionId="node_r"
    )
    orphan = GraphNode(id="node_o", type="note", layer=0, label="O")
    assert ask_agent._node_pulse_ids(region) == ["node_r"]
    assert ask_agent._node_pulse_ids(note) == ["node_r"]
    assert ask_agent._node_pulse_ids(orphan) == []


def test_step_end_always_emits_node_ids():
    """Shape stability: the client never has to guard for a missing key."""
    events: list[dict] = []
    ctx = SimpleNamespace(emit=lambda event, payload: events.append(payload))
    ask_agent._step_end(ctx, "s1", "explore_node", "Exploring: X")
    assert events[0]["node_ids"] == []
    ask_agent._step_end(
        ctx, "s2", "retrieve_context", "Searching", node_ids=["node_r"]
    )
    assert events[1]["node_ids"] == ["node_r"]
