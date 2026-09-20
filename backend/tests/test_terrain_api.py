from __future__ import annotations

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_terrain_route_returns_empty_shape_when_not_built(tmp_path, monkeypatch):
    from src.api import create_app

    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())

    response = client.get("/api/terrain")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 2
    assert data["schemaName"] == "cortex.brain-map"
    assert data["stats"]["regions"] == 0
    assert data["stats"]["tagsTotal"] == 0
    assert data["tree"] == []
    assert data["edges"]["regionEdges"] == []
    assert data["edges"]["tagEdges"] == []


def test_terrain_route_streams_compiled_file(tmp_path, monkeypatch):
    import json

    from src.api import create_app

    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / ".mnemify"
    data_dir.mkdir()
    payload = {"version": 2, "schemaName": "cortex.brain-map", "tree": []}
    (data_dir / "terrain.json").write_text(json.dumps(payload), encoding="utf-8")
    client = TestClient(create_app())

    response = client.get("/api/terrain")

    assert response.status_code == 200
    assert response.json() == payload
    # Compiles rewrite the file; browsers must never cache it.
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_compile_start_defaults_to_openai_and_refuses_missing_key(tmp_path, monkeypatch):
    from src.api import compile_orchestrator

    # MNEMIFY_HOME is tmp_path (autouse fixture), so the orchestrator looks
    # for the manifest under tmp_path/.mnemify — there is no module-level
    # DATA_DIR to patch any more.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # No Claude path on this "machine" either, so the refusal offers nothing.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    data_dir = tmp_path / ".mnemify"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "harvest-manifest.db").write_text("", encoding="utf-8")

    result = await compile_orchestrator.start_compile()

    assert result["ok"] is False
    assert "OPENAI_API_KEY not set" in result["reason"]
    # Typed refusal the UI turns into a consent dialog. The OpenAI engine needs
    # the key for the LLM itself, so the on-device embedder is no way out here.
    assert result["code"] == "openai_key_missing"
    assert result["local_embeddings_eligible"] is False
    assert "Settings" in result["reason"]


@pytest.fixture
def compile_orch():
    """Fresh compile state around a test — `CompileState.counts` is a mutable
    class attribute, so without this it bleeds between tests."""
    from src.api import compile_orchestrator

    compile_orchestrator.reset_state()
    yield compile_orchestrator
    compile_orchestrator.reset_state()


class _FakeRate:
    """Stands in for `_Rate` so the test doesn't have to burn the warm-up
    (6 ticks + a 0.2 s span) with sleeps."""

    def __init__(self, *values):
        self._values = list(values)

    def tick(self):
        return self._values.pop(0) if self._values else None


def test_enrich_progress_persists_rate_into_snapshot_counts(compile_orch):
    # Pollers of /api/terrain/current only see `state.counts` — the SSE-only
    # rate_per_sec left the TopBar pill with no way to compute a compile ETA.
    rate = _FakeRate(2.5)
    compile_orch._on_progress(
        {"stage": "enrich", "phase": "extract", "done": 40, "total": 800}, rate
    )

    counts = compile_orch.snapshot()["counts"]
    assert counts["rate_per_sec"] == 2.5
    assert counts["enrich_phase"] == "extract"
    assert counts["enrich_done"] == 40
    assert counts["enrich_total"] == 800


def test_enrich_progress_keeps_last_rate_while_warming_up(compile_orch):
    # `_Rate.tick()` returns None through warm-up, and the done=0 phase marker
    # is forced to None — neither may blank an ETA the UI is already showing.
    rate = _FakeRate(2.5, None)
    compile_orch._on_progress({"stage": "enrich", "phase": "extract", "done": 40, "total": 800}, rate)
    compile_orch._on_progress({"stage": "enrich", "phase": "extract", "done": 41, "total": 800}, rate)
    compile_orch._on_progress({"stage": "enrich", "phase": "embed", "done": 0, "total": 800}, rate)

    counts = compile_orch.snapshot()["counts"]
    assert counts["rate_per_sec"] == 2.5
    assert counts["enrich_phase"] == "embed"


def test_non_progress_frames_do_not_touch_the_rate(compile_orch):
    rate = _FakeRate(2.5, 9.9)
    compile_orch._on_progress({"stage": "enrich", "phase": "extract", "done": 40, "total": 800}, rate)
    compile_orch._on_progress({"type": "log", "stage": "enrich", "msg": "Tagged: foo"}, rate)

    assert compile_orch.snapshot()["counts"]["rate_per_sec"] == 2.5
