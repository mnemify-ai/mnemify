"""The shutdown handle (``src.api.lifecycle``) and the CLI's process-lifecycle
helpers: pid/port files, single-instance detection, port fallback."""

from __future__ import annotations

import os
import socket

import pytest

from src import paths
from src.api import lifecycle


@pytest.fixture(autouse=True)
def _clean_lifecycle():
    lifecycle.clear_server()
    yield
    lifecycle.clear_server()


class _FakeServer:
    def __init__(self) -> None:
        self.should_exit = False


# ─── lifecycle ──────────────────────────────────────────────────────

def test_request_shutdown_sets_should_exit():
    server = _FakeServer()
    lifecycle.set_server(server)
    assert lifecycle.has_server() is True
    assert lifecycle.request_shutdown("test") is True
    assert server.should_exit is True


def test_request_shutdown_is_a_noop_without_a_server(caplog):
    # --reload and every TestClient run register no Server; asking to quit must
    # log and return False rather than raise into a request handler.
    assert lifecycle.has_server() is False
    assert lifecycle.request_shutdown("test") is False


def test_clear_server_forgets_the_reference():
    lifecycle.set_server(_FakeServer())
    lifecycle.clear_server()
    assert lifecycle.has_server() is False


# ─── CLI: pid/port files ────────────────────────────────────────────

def test_claim_runtime_files_writes_pid_and_port(tmp_path):
    from src import cli

    release = cli._claim_runtime_files(8795)
    assert paths.server_pid_file().read_text().strip() == str(os.getpid())
    assert paths.server_port_file().read_text().strip() == "8795"
    assert cli._read_runtime_files() == (os.getpid(), 8795)

    release()
    assert not paths.server_pid_file().exists()
    assert not paths.server_port_file().exists()


def test_release_never_deletes_another_process_files(tmp_path):
    """A second ``mnemify up`` that bows out must not clean up the live one."""
    from src import cli

    release = cli._claim_runtime_files(8795)
    # Another process takes over the files after we claimed them.
    paths.server_pid_file().write_text("999999\n")
    release()
    assert paths.server_pid_file().exists()
    assert paths.server_port_file().exists()


def test_read_runtime_files_tolerates_garbage(tmp_path):
    from src import cli

    paths.ensure_home()
    paths.server_pid_file().write_text("not-a-pid")
    paths.server_port_file().write_text("")
    assert cli._read_runtime_files() == (None, None)


def test_pid_alive_is_true_for_self_and_false_for_a_free_pid():
    from src import cli

    assert cli._pid_alive(os.getpid()) is True
    assert cli._pid_alive(0) is False
    assert cli._pid_alive(-1) is False


# ─── CLI: single instance ───────────────────────────────────────────

def test_live_instance_is_none_without_files(tmp_path):
    from src import cli

    assert cli._live_instance() is None


def test_live_instance_is_none_when_the_pid_is_dead(tmp_path, monkeypatch):
    from src import cli

    paths.ensure_home()
    paths.server_pid_file().write_text("999999\n")
    paths.server_port_file().write_text("8795\n")
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)
    called = []
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: called.append(1) or {"ok": True})
    assert cli._live_instance() is None
    # A dead pid short-circuits: we never bother the (possibly foreign) port.
    assert called == []


def test_live_instance_is_none_when_health_does_not_answer(tmp_path, monkeypatch):
    from src import cli

    paths.ensure_home()
    paths.server_pid_file().write_text(f"{os.getpid()}\n")
    paths.server_port_file().write_text("8795\n")
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: None)
    assert cli._live_instance(wait=0) is None


# ─── CLI: the startup window (alive pid, health not yet answering) ──

def _write_runtime_files(pid: int | None = None, port: int = 8795) -> None:
    paths.ensure_home()
    paths.server_pid_file().write_text(f"{os.getpid() if pid is None else pid}\n")
    paths.server_port_file().write_text(f"{port}\n")


class _FakeClock:
    """A monotonic clock that only advances when ``sleep`` is called."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_inspect_instance_reports_starting_when_pid_is_alive_but_health_is_silent(
    tmp_path, monkeypatch
):
    from src import cli

    _write_runtime_files()
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    probes = []
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: probes.append(1) or None)
    clock = _FakeClock()

    inst = cli._inspect_instance(wait=5.0, sleep=clock.sleep, clock=clock)

    assert inst is not None
    assert inst.status == "starting"
    assert inst.running is False
    assert inst.pid == os.getpid()
    assert inst.port == 8795
    assert inst.health is None
    # It kept probing for the whole window rather than giving up at once.
    assert len(probes) > 1
    assert clock.now - 1000.0 >= 5.0
    # Files are untouched — it is not our job to decide they are stale.
    assert paths.server_pid_file().exists()
    assert paths.server_port_file().exists()


def test_inspect_instance_retries_until_health_answers(tmp_path, monkeypatch):
    from src import cli

    _write_runtime_files()
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    answers = iter([None, None, {"ok": True, "version": "9"}])
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: next(answers))
    clock = _FakeClock()

    inst = cli._inspect_instance(wait=5.0, sleep=clock.sleep, clock=clock)

    assert inst is not None and inst.running
    assert inst.port == 8795
    assert inst.health == {"ok": True, "version": "9"}
    assert len(clock.slept) == 2  # slept only between the failed probes
    # …and the tuple-shaped wrapper agrees.
    answers = iter([None, {"ok": True}])
    assert cli._live_instance(wait=5.0, sleep=clock.sleep, clock=clock) == (8795, {"ok": True})


def test_inspect_instance_is_none_when_the_pid_dies_during_the_wait(tmp_path, monkeypatch):
    from src import cli

    _write_runtime_files()
    alive = iter([True, False])  # alive at first read, gone after the first sleep
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: next(alive, False))
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: None)
    clock = _FakeClock()

    assert cli._inspect_instance(wait=5.0, sleep=clock.sleep, clock=clock) is None
    assert len(clock.slept) == 1


def test_inspect_instance_does_not_sleep_when_health_answers_first_time(tmp_path, monkeypatch):
    from src import cli

    _write_runtime_files()
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: {"ok": True})
    clock = _FakeClock()
    inst = cli._inspect_instance(wait=5.0, sleep=clock.sleep, clock=clock)
    assert inst is not None and inst.running
    assert clock.slept == []


def test_inspect_instance_is_none_without_files_or_with_a_dead_pid(tmp_path, monkeypatch):
    from src import cli

    assert cli._inspect_instance(wait=0) is None
    _write_runtime_files(pid=999999)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: {"ok": True})
    assert cli._inspect_instance(wait=0) is None


def _up_args(cli, port=8795):
    return cli._build_parser().parse_args(["up", "--port", str(port), "--no-browser"])


def test_up_bows_out_without_touching_files_when_an_instance_is_starting(
    tmp_path, monkeypatch, capsys
):
    from src import cli

    _write_runtime_files(pid=4242)
    monkeypatch.setattr(
        cli, "_inspect_instance", lambda *a, **k: cli.InstanceState("starting", 4242, 8795)
    )
    monkeypatch.setattr(cli, "_bind_first_free_port", lambda *a, **k: pytest.fail("bound a port"))
    monkeypatch.setattr(cli, "_open_browser", lambda url: pytest.fail("opened a browser"))

    with pytest.raises(SystemExit) as exc:
        cli._cmd_up(_up_args(cli))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "already starting" in out
    assert "4242" in out
    assert paths.server_pid_file().read_text().strip() == "4242"
    assert paths.server_port_file().read_text().strip() == "8795"


def test_up_reports_a_running_instance_and_exits_zero(tmp_path, monkeypatch, capsys):
    from src import cli

    _write_runtime_files(pid=4242, port=8801)
    monkeypatch.setattr(
        cli,
        "_inspect_instance",
        lambda *a, **k: cli.InstanceState("running", 4242, 8801, {"ok": True}),
    )
    monkeypatch.setattr(cli, "_bind_first_free_port", lambda *a, **k: pytest.fail("bound a port"))

    with pytest.raises(SystemExit) as exc:
        cli._cmd_up(_up_args(cli))

    assert exc.value.code == 0
    assert "already running at http://127.0.0.1:8801" in capsys.readouterr().out
    assert paths.server_pid_file().exists()


def test_stop_terminates_a_starting_instance_and_clears_its_files(tmp_path, monkeypatch, capsys):
    from src import cli

    _write_runtime_files(pid=4242)
    monkeypatch.setattr(
        cli, "_inspect_instance", lambda *a, **k: cli.InstanceState("starting", 4242, 8795)
    )
    killed = []
    monkeypatch.setattr(cli, "_terminate_pid", lambda pid, **k: killed.append(pid) or True)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: pytest.fail("no API to talk to yet")
    )

    cli._cmd_stop(cli._build_parser().parse_args(["stop"]))

    assert killed == [4242]
    assert "stopped" in capsys.readouterr().out
    assert not paths.server_pid_file().exists()
    assert not paths.server_port_file().exists()


def test_stop_keeps_the_files_when_a_starting_instance_will_not_die(
    tmp_path, monkeypatch, capsys
):
    from src import cli

    _write_runtime_files(pid=4242)
    monkeypatch.setattr(
        cli, "_inspect_instance", lambda *a, **k: cli.InstanceState("starting", 4242, 8795)
    )
    monkeypatch.setattr(cli, "_terminate_pid", lambda pid, **k: False)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_stop(cli._build_parser().parse_args(["stop"]))

    assert exc.value.code == 1
    assert "Could not stop pid 4242" in capsys.readouterr().out
    assert paths.server_pid_file().read_text().strip() == "4242"


def test_stop_clears_files_only_when_nothing_is_alive(tmp_path, monkeypatch, capsys):
    from src import cli

    _write_runtime_files(pid=999999)
    monkeypatch.setattr(cli, "_inspect_instance", lambda *a, **k: None)

    cli._cmd_stop(cli._build_parser().parse_args(["stop"]))

    assert "not running" in capsys.readouterr().out
    assert not paths.server_pid_file().exists()


def test_terminate_pid_waits_for_the_process_to_exit(monkeypatch):
    from src import cli

    signals = []
    monkeypatch.setattr("os.kill", lambda pid, sig: signals.append((pid, sig)))
    alive = iter([True, True, False])
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: next(alive, False))
    clock = _FakeClock()
    assert cli._terminate_pid(4242, wait=3.0, sleep=clock.sleep, clock=clock) is True
    assert len(signals) == 1 and signals[0][0] == 4242
    assert len(clock.slept) == 2


def test_terminate_pid_gives_up_after_the_wait(monkeypatch):
    from src import cli

    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    clock = _FakeClock()
    assert cli._terminate_pid(4242, wait=1.0, sleep=clock.sleep, clock=clock) is False
    assert clock.now - 1000.0 >= 1.0


def test_live_instance_returns_port_and_health(tmp_path, monkeypatch):
    from src import cli

    paths.ensure_home()
    paths.server_pid_file().write_text(f"{os.getpid()}\n")
    paths.server_port_file().write_text("8795\n")
    monkeypatch.setattr(cli, "_probe_health", lambda *a, **k: {"ok": True, "version": "1.0.0"})
    assert cli._live_instance() == (8795, {"ok": True, "version": "1.0.0"})


def test_clear_runtime_files_is_idempotent(tmp_path):
    from src import cli

    cli._clear_runtime_files()
    paths.ensure_home()
    paths.server_pid_file().write_text("1\n")
    cli._clear_runtime_files()
    assert not paths.server_pid_file().exists()


# ─── CLI: port fallback ─────────────────────────────────────────────

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_first_free_port_takes_the_requested_port():
    from src import cli

    wanted = _free_port()
    sock, port = cli._bind_first_free_port("127.0.0.1", wanted)
    try:
        assert port == wanted
        assert sock.getsockname()[1] == wanted
    finally:
        sock.close()


def test_bind_first_free_port_moves_past_an_occupied_one():
    from src import cli

    base = _free_port()
    occupier = socket.socket()
    occupier.bind(("127.0.0.1", base))
    occupier.listen(1)
    try:
        sock, port = cli._bind_first_free_port("127.0.0.1", base)
        try:
            # Not the requested port, and inside the fallback window.
            assert port != base
            assert base < port < base + cli.PORT_FALLBACK_TRIES
        finally:
            sock.close()
    finally:
        occupier.close()


def test_bind_first_free_port_raises_when_the_whole_window_is_taken():
    from src import cli

    base = _free_port()
    held = []
    try:
        for offset in range(3):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", base + offset))
                s.listen(1)
                held.append(s)
            except OSError:
                s.close()
        if len(held) < 3:
            pytest.skip("could not occupy three consecutive ports on this machine")
        with pytest.raises(RuntimeError, match="no free port"):
            cli._bind_first_free_port("127.0.0.1", base, tries=3)
    finally:
        for s in held:
            s.close()


def test_loopback_maps_wildcard_hosts():
    from src import cli

    assert cli._loopback("0.0.0.0") == "127.0.0.1"
    assert cli._loopback("::") == "127.0.0.1"
    assert cli._loopback("127.0.0.1") == "127.0.0.1"
    assert cli._loopback("localhost") == "localhost"
