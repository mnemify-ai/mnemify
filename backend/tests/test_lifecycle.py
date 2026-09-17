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
    assert cli._live_instance() is None


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
