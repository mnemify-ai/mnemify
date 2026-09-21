"""Effort plumbing + per-stage LLM usage ledger + resumable error classing."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from src.terrain.agents import anthropic_clients, claude_cli, claude_clients, openai_clients
from src.terrain.agents.usage import UsageLedger, effort_for, ledger
from src.terrain.pipelines.compiler import (
    RESUMABLE_ERROR_PREFIX,
    TerrainCompiler,
    compile_error_kind,
    describe_compile_error,
)
from src.terrain.utils.models import ChunkFeatures, EnrichedChunk, TerrainChunk
from src.terrain.utils.store import TerrainStore


def _ec(cid="c1"):
    chunk = TerrainChunk(
        id=cid, doc_id="d1", source_type="notion", source_id="d1",
        doc_title="Doc", content="hello", content_hash=f"h-{cid}",
    )
    return EnrichedChunk(chunk=chunk, features=ChunkFeatures(summary="s"), embedding=[0.1])


# ── ledger ─────────────────────────────────────────────────────────


def test_ledger_groups_by_stage_and_provider_shapes():
    lg = UsageLedger()
    lg.set_stage("extract")
    lg.record_openai(
        SimpleNamespace(
            input_tokens=100, output_tokens=20,
            input_tokens_details=SimpleNamespace(cached_tokens=40),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
        model="gpt-x",
    )
    lg.record_anthropic(
        {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 7,
         "cache_creation_input_tokens": 3},
        model="claude-sonnet-5",
    )
    lg.set_stage("notes")
    lg.record_claude_cli(
        {"model": "claude-opus-5", "duration_ms": 1200, "total_cost_usd": 0.02,
         "usage": {"input_tokens": 30, "output_tokens": 15}},
        model="opus",
    )
    snap = lg.snapshot()
    assert snap["stages"]["extract"]["calls"] == 2
    assert snap["stages"]["extract"]["input_tokens"] == 150
    assert snap["stages"]["extract"]["cached_input_tokens"] == 47
    assert snap["stages"]["extract"]["reasoning_tokens"] == 5
    assert sorted(snap["stages"]["extract"]["models"]) == ["anthropic:claude-sonnet-5", "openai:gpt-x"]
    assert snap["stages"]["notes"]["cost_usd"] == 0.02
    assert snap["total"]["calls"] == 3 and snap["total"]["input_tokens"] == 180
    assert "3 calls" in lg.summary_line()
    lg.reset()
    assert lg.snapshot() == {"stages": {}, "total": {k: 0 for k in snap["total"]}}


def test_effort_for_maps_known_levels_and_ignores_unknown():
    assert effort_for("openai", "low") == "low"
    assert effort_for("anthropic", "MEDIUM") == "medium"
    assert effort_for("claude_cli", "") is None
    assert effort_for("claude_cli", None) is None
    assert effort_for("openai", "bananas") is None


# ── transports ─────────────────────────────────────────────────────


class _StubMessages:
    def __init__(self):
        self.calls: list[dict] = []

    def parse(self, **params):
        self.calls.append(params)
        return SimpleNamespace(
            parsed_output=openai_clients.ClusterName(name="N", summary="S"),
            usage=SimpleNamespace(input_tokens=11, output_tokens=2,
                                  cache_read_input_tokens=0, cache_creation_input_tokens=0),
        )


def test_anthropic_shim_sends_effort_and_records_usage(monkeypatch):
    stub = SimpleNamespace(messages=_StubMessages())
    monkeypatch.setattr(anthropic_clients, "_anthropic_client", lambda: stub)
    ledger.reset()
    ledger.set_stage("name")
    store = TerrainStore(":memory:")
    try:
        namer = anthropic_clients.AnthropicClusterNamer(store, model="opus", effort="medium")
        namer.name_region([_ec()])
        # No effort → parameter omitted (provider default).
        namer2 = anthropic_clients.AnthropicClusterNamer(store, model="sonnet")
        namer2._call_region([_ec("c2")])
    finally:
        store.close()
    first, second = stub.messages.calls
    assert first["output_config"] == {"effort": "medium"}
    assert "output_config" not in second
    snap = ledger.snapshot()
    assert snap["stages"]["name"]["calls"] == 2
    assert snap["stages"]["name"]["input_tokens"] == 22


def test_claude_cli_passes_effort_flag_and_records_envelope(monkeypatch):
    seen: list[list[str]] = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        env = {"result": "ok", "model": "claude-sonnet-5", "duration_ms": 5,
               "usage": {"input_tokens": 9, "output_tokens": 1}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger.reset()
    ledger.set_stage("extract")
    assert claude_cli.claude_text("hi", model="sonnet", effort="low") == "ok"
    assert claude_cli.claude_text("hi", model="sonnet") == "ok"
    assert "--effort" in seen[0] and seen[0][seen[0].index("--effort") + 1] == "low"
    assert "--effort" not in seen[1]
    assert ledger.snapshot()["stages"]["extract"]["input_tokens"] == 18


def test_claude_shim_translates_reasoning_kwarg(monkeypatch):
    captured = {}

    def fake_claude_json(user, *, system, model, timeout, effort=None):
        captured["effort"] = effort
        return {"name": "N", "summary": "S"}

    monkeypatch.setattr(claude_clients, "claude_json", fake_claude_json)
    shim = claude_clients._ClaudeResponsesShim()
    shim.parse(model="opus", input=[{"role": "user", "content": "x"}],
               text_format=openai_clients.ClusterName, reasoning={"effort": "high"})
    assert captured["effort"] == "high"


def test_openai_mixin_llm_kwargs():
    ex = openai_clients.OpenAIFeatureExtractor(model="gpt-x", effort="low")
    assert ex._llm_kwargs() == {"reasoning": {"effort": "low"}}
    assert openai_clients.OpenAIFeatureExtractor(model="gpt-x")._llm_kwargs() == {}


def test_compiler_threads_effort_to_extractor_and_namer(tmp_path):
    store = TerrainStore(tmp_path / "t.db")
    try:
        c = TerrainCompiler(
            data_dir=tmp_path, store=store, ai_mode="claude",
            extract_effort="low", name_effort="medium",
        )
        assert c.extractor.effort == "low" and c.namer.effort == "medium"
        c2 = TerrainCompiler(data_dir=tmp_path, store=store, ai_mode="openai", extract_effort="")
        assert c2.extractor.effort is None and c2.namer.effort is None
    finally:
        store.close()


# ── resumable error classing ───────────────────────────────────────


def test_cli_failures_are_classified():
    assert claude_cli.classify_cli_failure("You've hit your usage limit") == "usage_limit"
    assert claude_cli.classify_cli_failure("Not logged in. Please run /login") == "auth"
    assert claude_cli.classify_cli_failure("some parse problem") is None
    e = claude_cli.ClaudeCLIUnavailableError("claude exited 1: usage limit", kind="usage_limit")
    assert compile_error_kind(e) == "usage_limit"
    assert describe_compile_error(e).startswith(RESUMABLE_ERROR_PREFIX)
    wrapped = RuntimeError("AI naming failed")
    wrapped.__cause__ = e
    assert compile_error_kind(wrapped) == "usage_limit"


def test_rate_limit_error_by_class_name_is_resumable():
    class RateLimitError(Exception):
        pass

    assert compile_error_kind(RateLimitError("429")) == "usage_limit"
    assert "resume" in describe_compile_error(RateLimitError("429")).lower()
    assert compile_error_kind(ValueError("x")) is None
    assert describe_compile_error(ValueError("bad")) == "bad"


def test_fail_run_keeps_counts(tmp_path):
    store = TerrainStore(tmp_path / "t.db")
    try:
        rid = store.start_run({"ai_mode": "local"})
        store.fail_run(rid, "Usage limit reached — x", counts={"llm_usage": {"total": {"calls": 3}}})
        row = store.recent_runs(1)[0]
        assert row["status"] == "failed"
        assert json.loads(row["counts"])["llm_usage"]["total"]["calls"] == 3
    finally:
        store.close()


# ── settings ───────────────────────────────────────────────────────


def test_compile_settings_accept_effort_levels():
    from src.api.routes_settings import COMPILE_DEFAULTS, CompileSettingsUpdate

    assert COMPILE_DEFAULTS["extract_effort"] == "low"
    assert COMPILE_DEFAULTS["name_effort"] == "medium"
    body = {
        "ai_mode": "claude", "openai_model": "gpt-x",
        "embedding_model": "text-embedding-3-large", "llm_concurrency": 4,
        "claude_call_logging": False, "workspace": "w", "owner_name": "o", "owner_role": "r",
    }
    assert CompileSettingsUpdate(**body).extract_effort == "low"
    assert CompileSettingsUpdate(**body, extract_effort="", name_effort="high").name_effort == "high"
    with pytest.raises(Exception):
        CompileSettingsUpdate(**body, extract_effort="max")
