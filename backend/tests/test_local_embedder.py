"""On-device embeddings (src/terrain/utils/local_embedder.py) and the consent
flow around them (compile start refusal + /api/embeddings/local)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from src.terrain.utils import local_embedder as le
from src.terrain.utils.local_embedder import (
    EMBEDDING_MODEL_CHOICES,
    LOCAL_EMBEDDING_DIM,
    LOCAL_EMBEDDING_MODEL,
    LocalEmbeddingClient,
    is_local_embedding_model,
)


class _FakeFastembedModel:
    """Stands in for fastembed.TextEmbedding: deterministic 384-d vectors."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, documents, batch_size=256):
        docs = list(documents)
        self.calls.append(docs)
        for i, _ in enumerate(docs):
            v = np.zeros(LOCAL_EMBEDDING_DIM, dtype=np.float32)
            v[i % LOCAL_EMBEDDING_DIM] = 1.0
            yield v


def test_model_choices_include_local_and_openai():
    assert LOCAL_EMBEDDING_MODEL in EMBEDDING_MODEL_CHOICES
    assert "text-embedding-3-large" in EMBEDDING_MODEL_CHOICES
    assert is_local_embedding_model(LOCAL_EMBEDDING_MODEL)
    assert not is_local_embedding_model("text-embedding-3-small")


def test_local_client_embeds_in_batches_and_keeps_order(monkeypatch):
    fake = _FakeFastembedModel()
    monkeypatch.setattr(le, "_make_model", lambda *, local_files_only: fake)

    client = LocalEmbeddingClient()
    vectors = client.embed_batch(["a", "b", "c"])

    assert len(vectors) == 3
    assert all(len(v) == LOCAL_EMBEDDING_DIM for v in vectors)
    assert vectors[0][0] == 1.0 and vectors[1][1] == 1.0 and vectors[2][2] == 1.0
    assert fake.calls == [["a", "b", "c"]]
    assert client.embed("solo") == vectors[0]
    assert client.embed_batch([]) == []


def test_local_client_hash_is_distinct_from_openai():
    from src.terrain.utils.embedder import EmbeddingClient

    assert LocalEmbeddingClient().hash("x") != EmbeddingClient().hash("x")
    assert LocalEmbeddingClient().model == LOCAL_EMBEDDING_MODEL


def test_local_client_never_downloads_silently(monkeypatch):
    def boom(*, local_files_only):
        assert local_files_only is True  # a compile must not fetch the model
        raise FileNotFoundError("not cached")

    monkeypatch.setattr(le, "_make_model", boom)
    with pytest.raises(RuntimeError, match="not downloaded yet"):
        LocalEmbeddingClient().embed("hello")


def test_models_dir_follows_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    assert le.models_dir() == tmp_path / ".mnemify" / "models"


def test_status_reports_missing_then_ready(monkeypatch):
    monkeypatch.setattr(le, "is_model_downloaded", lambda: False)
    monkeypatch.setattr(le._download, "status", "idle")
    s = le.local_model_status()
    assert s == {
        **s,
        "model": LOCAL_EMBEDDING_MODEL,
        "downloaded": False,
        "status": "idle",
        "dim": LOCAL_EMBEDDING_DIM,
    }
    monkeypatch.setattr(le, "is_model_downloaded", lambda: True)
    assert le.local_model_status()["status"] == "ready"


def test_prepare_is_idempotent_when_downloaded(monkeypatch):
    monkeypatch.setattr(le, "is_model_downloaded", lambda: True)
    started = []
    monkeypatch.setattr(le.threading, "Thread", lambda **kw: started.append(kw))
    s = le.prepare_local_model()
    assert s["status"] == "ready" and started == []


# ── compile start: typed refusal instead of a silent embedding switch ──

def _start(**kw):
    from src.api import compile_orchestrator as orch

    return asyncio.run(orch.start_compile(**kw))


@pytest.fixture
def compile_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    (tmp_path / ".mnemify").mkdir()
    (tmp_path / ".mnemify" / "harvest-manifest.db").write_bytes(b"")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # .env sync must not resurrect a key from the developer's real home.
    monkeypatch.setattr("src.config.load_config", lambda *a, **k: None)
    from src.api import compile_orchestrator as orch

    orch.reset_state()
    return tmp_path


def test_claude_engine_without_openai_key_offers_local_embeddings(compile_env, monkeypatch):
    monkeypatch.setattr(le, "is_model_downloaded", lambda: False)
    res = _start(ai_mode="anthropic")
    assert res["ok"] is False
    assert res["code"] == "openai_key_missing"
    assert res["local_embeddings_eligible"] is True
    assert res["local_embeddings"]["downloaded"] is False
    assert "Settings" in res["reason"]
    # The engine this request runs with — persisted on consent so a per-run
    # Claude override of a saved OpenAI default doesn't leave the defaults
    # as "OpenAI engine + local embeddings" (which can't compile without a key).
    assert res["suggested_ai_mode"] == "anthropic"


def test_openai_engine_without_key_offers_claude_when_available(compile_env, monkeypatch):
    # compile_env sets ANTHROPIC_API_KEY; pretend no `claude` CLI on PATH.
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("src.terrain.agents.claude_cli._well_known_claude_locations", lambda: [])
    monkeypatch.setattr(le, "is_model_downloaded", lambda: False)
    res = _start(ai_mode="openai")
    assert res["ok"] is False
    assert res["code"] == "openai_key_missing"
    assert res["local_embeddings_eligible"] is True
    assert res["suggested_ai_mode"] == "anthropic"
    assert res["local_embeddings"]["downloaded"] is False

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    monkeypatch.setattr("sys.platform", "linux")
    assert _start(ai_mode="openai")["suggested_ai_mode"] == "claude"


def test_openai_engine_without_key_or_claude_is_not_eligible(compile_env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("src.terrain.agents.claude_cli._well_known_claude_locations", lambda: [])
    res = _start(ai_mode="openai")
    assert res["ok"] is False
    assert res["code"] == "openai_key_missing"
    assert res["local_embeddings_eligible"] is False
    assert res["suggested_ai_mode"] is None


def test_local_model_requested_but_not_downloaded_refuses(compile_env, monkeypatch):
    monkeypatch.setattr(le, "is_model_downloaded", lambda: False)
    res = _start(ai_mode="anthropic", embedding_model=LOCAL_EMBEDDING_MODEL)
    assert res["ok"] is False
    assert res["code"] == "local_model_missing"


def test_local_model_missing_flags_a_set_openai_key(compile_env, monkeypatch):
    # Key added after the consent path saved the on-device default: the
    # refusal must say the key is there so the dialog can offer OpenAI.
    monkeypatch.setattr(le, "is_model_downloaded", lambda: False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    res = _start(ai_mode="anthropic", embedding_model=LOCAL_EMBEDDING_MODEL)
    assert res["code"] == "local_model_missing"
    assert res["openai_key_set"] is True
    assert "OpenAI" in res["reason"]

    monkeypatch.delenv("OPENAI_API_KEY")
    assert _start(ai_mode="anthropic", embedding_model=LOCAL_EMBEDDING_MODEL)["openai_key_set"] is False


def test_per_run_embedding_pick_becomes_the_saved_default(compile_env, monkeypatch):
    # Saved default: on-device (as the consent path leaves it). The user picks
    # OpenAI in the compile dialog with a key set → compile starts with OpenAI
    # and the saved default follows, so Ask + schedules stay in the same space.
    from src.api import compile_orchestrator as orch
    from src.api.routes_settings import _compile_settings_block
    from src.api.yaml_writer import upsert_compile

    upsert_compile({**_compile_settings_block(), "embedding_model": LOCAL_EMBEDDING_MODEL})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    async def fake_run(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(orch, "_run_compile", fake_run)
    res = _start(ai_mode="anthropic", embedding_model="text-embedding-3-large")
    assert res == {"ok": True, "ai_mode": "anthropic"}
    assert captured["embedding_model"] == "text-embedding-3-large"
    assert _compile_settings_block()["embedding_model"] == "text-embedding-3-large"
    orch.reset_state()


def test_local_model_downloaded_starts_compile_without_openai_key(compile_env, monkeypatch):
    monkeypatch.setattr(le, "is_model_downloaded", lambda: True)
    from src.api import compile_orchestrator as orch

    captured = {}

    async def fake_run(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(orch, "_run_compile", fake_run)
    res = _start(ai_mode="anthropic", embedding_model=LOCAL_EMBEDDING_MODEL)
    assert res == {"ok": True, "ai_mode": "anthropic"}
    assert captured["embedding_model"] == LOCAL_EMBEDDING_MODEL
    orch.reset_state()


def test_compile_settings_accept_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    from src.api.routes_settings import CompileSettingsUpdate, COMPILE_DEFAULTS

    body = CompileSettingsUpdate(**{**COMPILE_DEFAULTS, "embedding_model": LOCAL_EMBEDDING_MODEL})
    assert body.embedding_model == LOCAL_EMBEDDING_MODEL


def test_compiler_picks_local_embedder_by_model_name(tmp_path, monkeypatch):
    from src.terrain.pipelines.compiler import TerrainCompiler
    from src.terrain.utils.embedder import LocalHashEmbeddingClient
    from src.terrain.agents.openai_clients import OpenAIEmbeddingClient

    c = TerrainCompiler(data_dir=tmp_path, ai_mode="claude", embedding_model=LOCAL_EMBEDDING_MODEL)
    assert isinstance(c.embedder, LocalEmbeddingClient)
    c.store.close()
    c = TerrainCompiler(data_dir=tmp_path, ai_mode="claude", embedding_model="text-embedding-3-small")
    assert isinstance(c.embedder, OpenAIEmbeddingClient) and c.embedder.model == "text-embedding-3-small"
    c.store.close()
    c = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    assert isinstance(c.embedder, LocalHashEmbeddingClient)
    c.store.close()


def test_store_reports_vector_model(tmp_path):
    from src.terrain.utils.store import TerrainStore

    store = TerrainStore(tmp_path / "terrain.db")
    try:
        assert store.graph_vector_model() is None
        store.replace_graph_node_vectors({"n1": [0.1] * 4, "n2": [0.2] * 4}, model=LOCAL_EMBEDDING_MODEL)
        assert store.graph_vector_model() == LOCAL_EMBEDDING_MODEL
    finally:
        store.close()
