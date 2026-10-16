"""Folders that appear in an Obsidian vault after its scope was picked.

An explicit ``watch_folders`` list silently skips folders created later; the
Connections card surfaces them (``new_folders``) and "every folder picked" is
stored as the empty scope (= whole vault) so later folders come along.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.api import routes_connections as rc


def _note(vault: Path, rel: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# n\n", encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    _note(v, "Meetings/a.md")
    _note(v, "Projects/Atlas/b.md")
    _note(v, "Projects/Sage/c.md")
    _note(v, "Journal/d.md")
    (v / ".obsidian").mkdir()
    (v / "Empty").mkdir()  # no notes → never reported
    return v


def test_empty_scope_means_whole_vault(vault: Path):
    assert rc._obsidian_uncovered_folders(str(vault), []) == []


def test_reports_topmost_uncovered_folders(vault: Path):
    got = rc._obsidian_uncovered_folders(str(vault), ["Meetings"])
    assert got == ["Journal", "Projects"]


def test_parent_scope_covers_new_subfolders(vault: Path):
    _note(vault, "Projects/Pocket/e.md")  # created after the scope was picked
    assert rc._obsidian_uncovered_folders(str(vault), ["Projects", "Meetings", "Journal"]) == []


def test_partially_covered_parent_reports_sibling(vault: Path):
    got = rc._obsidian_uncovered_folders(
        str(vault), ["Projects/Atlas", "Meetings", "Journal"]
    )
    assert got == ["Projects/Sage"]


def test_ignored_and_hidden_folders_are_not_reported(vault: Path):
    _note(vault, "node_modules/t.md")
    _note(vault, ".trash/x.md")
    assert rc._obsidian_uncovered_folders(str(vault), ["Meetings", "Projects", "Journal"]) == []


def test_all_folders_collapse_to_whole_vault(vault: Path):
    assert rc._collapse_obsidian_scope(str(vault), ["Meetings", "Projects", "Journal"]) == []
    # Nested duplicates the picker also saves don't change the answer.
    assert rc._collapse_obsidian_scope(
        str(vault), ["Meetings", "Projects", "Projects/Atlas", "Projects/Sage", "Journal"]
    ) == []


def test_partial_scope_is_kept(vault: Path):
    assert rc._collapse_obsidian_scope(str(vault), ["Meetings"]) == ["Meetings"]


def test_missing_vault_leaves_scope_untouched(tmp_path: Path):
    scope = ["Meetings"]
    assert rc._collapse_obsidian_scope(str(tmp_path / "nope"), scope) == scope


def test_update_scope_stores_empty_when_everything_selected(vault: Path, monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(
        rc, "read_config",
        lambda: {"sources": {"obsidian": {"enabled": True, "vault_path": str(vault)}}},
    )
    monkeypatch.setattr(rc, "upsert_source", lambda name, block: saved.update({name: block}))
    out = asyncio.run(rc.update_scope("obsidian", rc.ScopeUpdate(scope=["Meetings", "Projects", "Journal"])))
    assert out["scope"] == []
    assert saved["obsidian"]["watch_folders"] == []


def test_save_obsidian_drops_watch_folders_when_everything_selected(vault: Path, monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(
        rc, "read_config",
        lambda: {"sources": {"obsidian": {"watch_folders": ["Meetings"]}}},
    )
    monkeypatch.setattr(rc, "upsert_source", lambda name, block: saved.update({name: block}))
    asyncio.run(rc.save_obsidian(rc.ObsidianSave(
        vault_path=str(vault), scope=["Meetings", "Projects", "Journal"])))
    assert "watch_folders" not in saved["obsidian"]
