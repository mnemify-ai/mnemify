"""Route-level tests for POST /api/ask — SSE event ordering, the
citations_used event, and the embedder-mismatch guard. Providers and the
embedder are monkeypatched; no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient

from src.terrain.utils.models import GraphNode, GraphView  # noqa: E402


class _StubEmbedder:
    def __init__(self, vector):
        self._vector = vector

    def embed(self, text: str):
        if isinstance(self._vector, Exception):
            raise self._vector
        return self._vector


def _graph() -> GraphView:
    return GraphView(
        nodes=[
            GraphNode(id="tag.a", type="tag", label="Alpha", layer=2,
                      embedding=[1.0, 0.0]),
            GraphNode(id="tag.b", type="tag", label="Beta", layer=2,
                      embedding=[0.9, 0.1]),
        ],
        edges=[],
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from src.api import create_app, routes_ask

    monkeypatch.chdir(tmp_path)
    terrain = tmp_path / "terrain.json"
    terrain.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes_ask, "_TERRAIN_PATH", terrain)
    monkeypatch.setattr(
        routes_ask, "_load_knowledge_map", lambda: SimpleNamespace(graph=_graph())
    )

    async def _no_understanding(*args, **kwargs):
        return None

    monkeypatch.setattr(
        routes_ask.ask_providers, "understand_query", _no_understanding
    )
    return TestClient(create_app()), routes_ask


def _patch_answer(monkeypatch, routes_ask, answer: str):
    async def _stream(*args, **kwargs):
        yield answer

    monkeypatch.setattr(routes_ask.ask_providers, "stream_chat", _stream)


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    current_event, current_data = None, ""
    for line in text.splitlines() + [""]:
        if line == "":
            if current_event and current_data:
                events.append((current_event, json.loads(current_data)))
            current_event, current_data = None, ""
        elif line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            current_data += line[5:].strip()
    return events


def _ask(client, query="alpha things", provider="openai"):
    # "openai" is the provider that still runs the legacy one-shot pipeline
    # these tests cover; "anthropic"/"claude" dispatch to the agentic path
    # (see the agentic tests at the bottom).
    return client.post(
        "/api/ask",
        json={"query": query, "provider": provider, "model": "m", "history": []},
        headers={"Authorization": "Bearer test-key"},
    )


def test_citations_used_reflects_answer_markers(client, monkeypatch):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder([1.0, 0.0]))
    _patch_answer(monkeypatch, routes_ask, "Alpha is key [c1]; see also [c2]. [c99]")

    resp = _ask(tc)
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    names = [name for name, _ in events]
    assert names[:2] == ["retrieval_debug", "citations"]
    assert names[-2:] == ["citations_used", "done"]

    used_payload = dict(events)["citations_used"]
    assert used_payload["used"] == ["c1", "c2"]  # c99 hallucinated → dropped
    assert used_payload["fallback"] is False

    citations = dict(events)["citations"]["citations"]
    assert all("score" in c for c in citations)


def test_citations_used_falls_back_when_model_cites_nothing(client, monkeypatch):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder([1.0, 0.0]))
    _patch_answer(monkeypatch, routes_ask, "An answer with no markers at all.")

    resp = _ask(tc)
    events = dict(_sse_events(resp.text))
    assert events["citations_used"]["fallback"] is True
    assert 0 < len(events["citations_used"]["used"]) <= 5


def test_dim_mismatch_returns_503_before_sse(client, monkeypatch):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder([1.0, 0.0, 0.0]))  # 3-dim vs 2-dim graph

    resp = _ask(tc)
    assert resp.status_code == 503
    assert "dimension" in resp.json()["detail"]


def test_embed_failure_with_no_seeds_returns_503(client, monkeypatch):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder(RuntimeError("boom")))

    resp = _ask(tc, query="hello there")  # no capitalized mentions → no seeds
    assert resp.status_code == 503
    assert "embedding failed" in resp.json()["detail"]


# ── agentic dispatch (providers "anthropic" / "claude") ──────────────


def _patch_agent_session(monkeypatch, events):
    """Replace the agentic runner with a canned SSE sequence; records the
    kwargs it was invoked with."""
    from src.api import ask_agent

    calls = {}

    async def _fake_session(**kwargs):
        calls.update(kwargs)
        for name, payload in events:
            yield {"event": name, "data": json.dumps(payload)}

    monkeypatch.setattr(ask_agent, "run_agent_session", _fake_session)
    return calls


_AGENT_EVENTS = [
    ("agent_step", {"id": "s1", "tool": "terrain_overview",
                    "label": "Surveying the terrain", "status": "done",
                    "detail": None}),
    ("citations", {"citations": []}),
    ("delta", {"text": "Answer."}),
    ("citations_used", {"used": [], "fallback": False}),
    ("done", {}),
]


def test_claude_provider_needs_no_key_and_streams_agentic_events(
    client, monkeypatch
):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder([1.0, 0.0]))
    calls = _patch_agent_session(monkeypatch, _AGENT_EVENTS)

    resp = tc.post(
        "/api/ask",
        json={"query": "alpha", "provider": "claude", "model": "sonnet",
              "history": []},
    )  # no Authorization header at all
    assert resp.status_code == 200
    names = [name for name, _ in _sse_events(resp.text)]
    assert names == [
        "agent_step", "citations", "delta", "citations_used", "done",
    ]
    assert calls["provider"] == "claude"
    assert calls["key"] is None


def test_anthropic_provider_dispatches_agentic_with_key(client, monkeypatch):
    tc, routes_ask = client
    monkeypatch.setattr(routes_ask, "_embedder_for_query",
                        lambda: _StubEmbedder([1.0, 0.0]))
    calls = _patch_agent_session(monkeypatch, _AGENT_EVENTS)

    resp = _ask(tc, provider="anthropic")
    assert resp.status_code == 200
    assert calls["provider"] == "anthropic"
    assert calls["key"] == "test-key"


def test_anthropic_without_key_still_401(client, monkeypatch):
    tc, _routes_ask = client
    resp = tc.post(
        "/api/ask",
        json={"query": "alpha", "provider": "anthropic", "model": "m",
              "history": []},
    )
    assert resp.status_code == 401
