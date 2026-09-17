"""Tests for ``mnemify migrate-home``.

The command moves a legacy ``backend/`` state layout into the platform
app-data home. Both ends are monkeypatched (``paths._BACKEND_DIR`` and
``paths._platform_default``) so the test never goes near a real checkout —
running this against a dev machine would move the developer's actual data.
"""

from __future__ import annotations

import pytest

from src import paths
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
