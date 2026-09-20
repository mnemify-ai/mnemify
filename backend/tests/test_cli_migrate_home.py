"""Tests for ``mnemify migrate-home``.

The command moves a legacy ``backend/`` state layout into the platform
app-data home. Both ends are monkeypatched (``paths._BACKEND_DIR`` and
``paths._platform_default``) so the test never goes near a real checkout —
running this against a dev machine would move the developer's actual data.
"""

from __future__ import annotations

import pytest

from src import cli, paths
from src.cli import _build_parser, _cmd_migrate_home


def _fake_layout(tmp_path, monkeypatch, *, markers=(".mnemify", "mnemify.yaml", ".env")):
    backend = tmp_path / "backend"
    backend.mkdir()
    for name in markers:
        if name == ".mnemify":
            (backend / name).mkdir()
            (backend / name / "terrain.json").write_text("{}", encoding="utf-8")
        else:
            (backend / name).write_text("KEY=value\n", encoding="utf-8")
    dest = tmp_path / "app-data"
    monkeypatch.setattr(paths, "_BACKEND_DIR", backend)
    monkeypatch.setattr(paths, "_platform_default", lambda: dest)
    return backend, dest


def _args(yes: bool):
    return _build_parser().parse_args(["migrate-home"] + (["--yes"] if yes else []))


def test_migrate_moves_all_three_markers(tmp_path, monkeypatch, capsys):
    backend, dest = _fake_layout(tmp_path, monkeypatch)

    _cmd_migrate_home(_args(yes=True))

    assert (dest / ".mnemify" / "terrain.json").read_text(encoding="utf-8") == "{}"
    assert (dest / "mnemify.yaml").is_file()
    assert (dest / ".env").is_file()
    assert not (backend / ".mnemify").exists()
    assert not (backend / "mnemify.yaml").exists()
    assert not (backend / ".env").exists()
    assert "moved .mnemify" in capsys.readouterr().out


def test_migrate_moves_only_what_exists(tmp_path, monkeypatch):
    _backend, dest = _fake_layout(tmp_path, monkeypatch, markers=("mnemify.yaml",))
    _cmd_migrate_home(_args(yes=True))
    assert (dest / "mnemify.yaml").is_file()
    assert not (dest / ".env").exists()


def test_migrate_is_a_noop_when_there_is_nothing_to_move(tmp_path, monkeypatch, capsys):
    _backend, dest = _fake_layout(tmp_path, monkeypatch, markers=())
    _cmd_migrate_home(_args(yes=True))
    assert "Nothing to migrate" in capsys.readouterr().out
    assert not dest.exists()


def test_migrate_refuses_to_merge_into_an_occupied_home(tmp_path, monkeypatch, capsys):
    backend, dest = _fake_layout(tmp_path, monkeypatch)
    dest.mkdir()
    (dest / ".env").write_text("OTHER=1\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_migrate_home(_args(yes=True))

    assert exc.value.code == 1
    assert "Refusing to migrate" in capsys.readouterr().out
    # Nothing moved — the legacy layout is intact.
    assert (backend / ".mnemify").is_dir()
    assert (dest / ".env").read_text(encoding="utf-8") == "OTHER=1\n"


def test_migrate_without_yes_aborts_on_a_no_answer(tmp_path, monkeypatch, capsys):
    backend, dest = _fake_layout(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")

    _cmd_migrate_home(_args(yes=False))

    assert "Aborted" in capsys.readouterr().out
    assert (backend / ".mnemify").is_dir()
    assert not dest.exists()


def test_migrate_without_yes_proceeds_on_a_y_answer(tmp_path, monkeypatch):
    backend, dest = _fake_layout(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_a: "y")

    _cmd_migrate_home(_args(yes=False))

    assert (dest / ".mnemify").is_dir()
    assert not (backend / ".mnemify").exists()


# ─── a live server blocks the move ───────────────────────────────────

@pytest.mark.parametrize("status", ["running", "starting"])
def test_migrate_refuses_while_a_server_is_up_or_starting(tmp_path, monkeypatch, capsys, status):
    backend, dest = _fake_layout(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "_inspect_instance", lambda *a, **k: cli.InstanceState(status, 4242, 8795)
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_migrate_home(_args(yes=True))

    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "mnemify stop" in out
    assert status in out
    assert (backend / ".mnemify").is_dir()
    assert not dest.exists()


def test_migrate_proceeds_when_only_stale_runtime_files_exist(tmp_path, monkeypatch):
    backend, dest = _fake_layout(tmp_path, monkeypatch)
    paths.ensure_home()
    paths.server_pid_file().write_text("999999\n")
    paths.server_port_file().write_text("8795\n")
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)

    _cmd_migrate_home(_args(yes=True))

    assert (dest / ".mnemify").is_dir()
    assert not (backend / ".mnemify").exists()


# ─── pre-flight + rollback ───────────────────────────────────────────

def test_migrate_rolls_back_when_a_later_move_fails(tmp_path, monkeypatch, capsys):
    import shutil

    backend, dest = _fake_layout(tmp_path, monkeypatch)
    real_move = shutil.move
    calls = []

    def flaky_move(src, dst):
        calls.append(src)
        if src.endswith("mnemify.yaml"):
            raise PermissionError("locked")
        return real_move(src, dst)

    monkeypatch.setattr(shutil, "move", flaky_move)

    with pytest.raises(SystemExit) as exc:
        _cmd_migrate_home(_args(yes=True))

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "could not move mnemify.yaml" in out
    assert "moved .mnemify back" in out
    assert "aborted" in out.lower()
    # Everything is back where it started; nothing is stranded at the destination.
    assert (backend / ".mnemify" / "terrain.json").is_file()
    assert (backend / "mnemify.yaml").is_file()
    assert (backend / ".env").is_file()
    assert not (dest / ".mnemify").exists()
    assert not (dest / "mnemify.yaml").exists()
    assert not (dest / ".env").exists()
    # The failed item was never retried and the ones after it never attempted.
    assert not any(c.endswith(".env") for c in calls)


def test_migrate_rechecks_the_layout_after_the_prompt(tmp_path, monkeypatch, capsys):
    backend, dest = _fake_layout(tmp_path, monkeypatch)

    def answer(*_a):
        # While the prompt sat open, something appeared at the destination.
        dest.mkdir()
        (dest / "mnemify.yaml").write_text("x", encoding="utf-8")
        return "y"

    monkeypatch.setattr("builtins.input", answer)

    with pytest.raises(SystemExit) as exc:
        _cmd_migrate_home(_args(yes=False))

    assert exc.value.code == 1
    assert "layout changed" in capsys.readouterr().out
    assert (backend / ".mnemify").is_dir()
    assert (backend / "mnemify.yaml").is_file()
    assert (dest / "mnemify.yaml").read_text(encoding="utf-8") == "x"


def test_migrate_rechecks_that_sources_still_exist(tmp_path, monkeypatch, capsys):
    import shutil

    backend, dest = _fake_layout(tmp_path, monkeypatch)

    def answer(*_a):
        shutil.rmtree(backend / ".mnemify")
        return "y"

    monkeypatch.setattr("builtins.input", answer)

    with pytest.raises(SystemExit) as exc:
        _cmd_migrate_home(_args(yes=False))

    assert exc.value.code == 1
    assert ".mnemify is gone" in capsys.readouterr().out
    assert (backend / "mnemify.yaml").is_file()
    assert not dest.exists()
