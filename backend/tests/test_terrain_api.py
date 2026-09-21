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
    from src.terrain.agents import claude_cli
    monkeypatch.setattr(claude_cli, "_well_known_claude_locations", lambda: [])
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


def test_health_reports_claude_cli_from_path_probe(monkeypatch):
    """`claude_cli` on /api/health is a real PATH probe, never a platform
    guess — the CLI ships for Windows too, so the UI must not gate on OS."""
    import src.api as api_mod
    from src.api import create_app

    monkeypatch.setattr(api_mod, "find_claude_binary", lambda: "/x/claude")
    assert TestClient(create_app()).get("/api/health").json()["claude_cli"] is True

    monkeypatch.setattr(api_mod, "find_claude_binary", lambda: None)
    assert TestClient(create_app()).get("/api/health").json()["claude_cli"] is False


def test_claude_text_resolves_binary_via_which(monkeypatch):
    """The transport passes the resolved executable (not the bare name) to
    subprocess, so Windows' `claude.cmd` / `claude.exe` are found; a missing
    binary is a `missing_cli` failure before any subprocess call."""
    import subprocess

    from src.terrain.agents import claude_cli

    monkeypatch.setattr(claude_cli.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_cli, "_well_known_claude_locations", lambda: [])
    with pytest.raises(claude_cli.ClaudeCLIUnavailableError) as ei:
        claude_cli.claude_text("hi")
    assert ei.value.kind == "missing_cli"

    seen: dict = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok"}', stderr="")

    monkeypatch.setattr(claude_cli.shutil, "which", lambda _n: r"C:\Users\me\.local\bin\claude.exe")
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    assert claude_cli.claude_text("hi") == "ok"
    assert seen["cmd"][0] == r"C:\Users\me\.local\bin\claude.exe"


def test_claude_text_keeps_prompts_off_the_command_line(monkeypatch, tmp_path):
    """User prompt over stdin, system prompt via a file, UTF-8 both ways.
    argv is capped at 32K on Windows and re-parsed by cmd.exe behind an npm
    shim — chunks arrived empty ("I don't see a message from you yet")."""
    import subprocess

    from src.terrain.agents import claude_cli

    seen: dict = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok"}', stderr="")

    monkeypatch.setattr(claude_cli, "find_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(claude_cli.tempfile, "gettempdir", lambda: str(tmp_path))

    prompt = 'chunk with "quotes", 100% & ^carets — and 日本語'
    system = "You are a % strict \"JSON\" extractor"
    assert claude_cli.claude_text(prompt, system=system) == "ok"

    cmd, kw = seen["cmd"], seen["kw"]
    assert kw["input"] == prompt
    assert kw["encoding"] == "utf-8"
    assert "-p" in cmd and prompt not in cmd and system not in cmd
    sys_file = cmd[cmd.index("--system-prompt-file") + 1]
    assert open(sys_file, encoding="utf-8").read() == system
    # Same system prompt → same file, written once (hundreds of calls per compile).
    assert claude_cli._system_prompt_file(system) == sys_file
    assert claude_cli._system_prompt_file(system + "x") != sys_file


def test_find_claude_binary_falls_back_to_installer_locations(monkeypatch, tmp_path):
    """A server started from a desktop icon (minimal env) or before the CLI
    was installed has a stale PATH — the installers' known locations still count."""
    from src.terrain.agents import claude_cli

    monkeypatch.setattr(claude_cli.shutil, "which", lambda _n: None)
    monkeypatch.setattr(claude_cli, "_well_known_claude_locations", lambda: [tmp_path / "claude"])
    assert claude_cli.find_claude_binary() is None
    (tmp_path / "claude").write_text("#!/bin/sh\n")
    assert claude_cli.find_claude_binary() == str(tmp_path / "claude")


def test_npm_cmd_shim_is_unwrapped_to_node_cli_js(monkeypatch, tmp_path):
    """npm's Windows `claude.cmd` would go through cmd.exe, which re-parses the
    prompt as shell syntax — so the transport runs `node cli.js` directly."""
    from src.terrain.agents import claude_cli

    shim = tmp_path / "claude.cmd"
    shim.write_text(
        '@ECHO off\r\nSET dp0=%~dp0\r\n'
        'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
        '"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*\r\n'
    )
    cli_js = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    cli_js.parent.mkdir(parents=True)
    cli_js.write_text("// cli")

    monkeypatch.setattr(claude_cli.shutil, "which", lambda n: "/usr/bin/node" if n == "node" else None)
    assert claude_cli._claude_argv(str(shim)) == ["/usr/bin/node", str(cli_js)]

    # node.exe next to the shim (nvm-style layouts) wins over PATH.
    (tmp_path / "node.exe").write_text("")
    assert claude_cli._claude_argv(str(shim))[0] == str(tmp_path / "node.exe")

    # Unrecognised shim layout or no node: run the shim itself rather than fail.
    shim.write_text("@ECHO off\r\nsomething else\r\n")
    assert claude_cli._claude_argv(str(shim)) == [str(shim)]
    # A plain executable is passed through untouched.
    assert claude_cli._claude_argv(r"C:\Users\me\.local\bin\claude.exe") == [r"C:\Users\me\.local\bin\claude.exe"]


def test_start_compile_refuses_claude_mode_without_cli(tmp_path, monkeypatch):
    """Pre-flight: no `claude` binary → typed refusal before anything runs,
    not a mid-build failure. Catches stale tabs, schedules and API callers."""
    import asyncio

    from src import paths
    from src.api import compile_orchestrator as co
    from src.terrain.agents import claude_cli

    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "harvest-manifest.db").write_bytes(b"")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(claude_cli, "find_claude_binary", lambda: None)

    res = asyncio.run(co.start_compile(ai_mode="claude"))
    assert res["ok"] is False
    assert res["code"] == "claude_cli_missing"
    assert "install" in res["reason"].lower()
