"""Tests for the Obsidian vault scanner (VaultScanner).

These tests run against the fixture vault at tests/fixtures/obsidian-vault/
and use no network access.
"""

from __future__ import annotations

from pathlib import Path

from src.harvester.obsidian.models import ObsidianVaultConfig
from src.harvester.obsidian.scanner import VaultScanner

# ── Fixture vault path ─────────────────────────────────────────────

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


def make_scanner(
    watch_folders: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
) -> VaultScanner:
    cfg = ObsidianVaultConfig(
        vault_path=str(VAULT),
        watch_folders=watch_folders or [],
        ignore_patterns=ignore_patterns or [],
    )
    return VaultScanner(VAULT, cfg)


# ── 1. Full vault scan (no watch_folders, default ignore) ──────────

def test_full_scan_returns_expected_notes():
    scanner = make_scanner()
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())

    # Should be included
    assert "00-inbox/quick-note.md" in found
    assert "00-inbox/web-clip.md" in found
    assert "daily/2026-04-15.md" in found
    assert "meetings/q2-planning.md" in found
    assert "notes/project-mnemify.md" in found
    assert "notes/nested/deep-note.md" in found


def test_full_scan_excludes_obsidian_folder():
    scanner = make_scanner()
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert not any(p.startswith(".obsidian/") for p in found)


def test_full_scan_includes_templates_without_ignore():
    """By default (no extra patterns), templates/ IS included."""
    scanner = make_scanner()
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "templates/daily-template.md" in found


def test_full_scan_includes_wiki_without_ignore():
    """02-wiki/ is not in the default ignore list; only .obsidian is."""
    scanner = make_scanner()
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "02-wiki/compiled-output.md" in found


# ── 2. Ignore patterns ─────────────────────────────────────────────

def test_ignore_pattern_excludes_templates_folder():
    scanner = make_scanner(ignore_patterns=["templates/*"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "templates/daily-template.md" not in found


def test_ignore_pattern_excludes_wiki_folder():
    scanner = make_scanner(ignore_patterns=["02-wiki/*"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "02-wiki/compiled-output.md" not in found


def test_ignore_pattern_combined():
    scanner = make_scanner(ignore_patterns=["templates/*", "02-wiki/*"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "templates/daily-template.md" not in found
    assert "02-wiki/compiled-output.md" not in found
    # Others still present
    assert "00-inbox/quick-note.md" in found


def test_ignore_pattern_fnmatch_for_specific_file():
    scanner = make_scanner(ignore_patterns=["*/quick-note.md"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "00-inbox/quick-note.md" not in found
    assert "00-inbox/web-clip.md" in found


# ── 3. watch_folders scoping ───────────────────────────────────────

def test_watch_folders_limits_scan_to_specified_folders():
    scanner = make_scanner(watch_folders=["00-inbox", "daily"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())

    assert "00-inbox/quick-note.md" in found
    assert "00-inbox/web-clip.md" in found
    assert "daily/2026-04-15.md" in found

    # Outside watch_folders — should NOT appear
    assert "meetings/q2-planning.md" not in found
    assert "notes/project-mnemify.md" not in found


def test_watch_folders_nonexistent_folder_does_not_raise():
    """A missing watch_folder is silently skipped."""
    scanner = make_scanner(watch_folders=["does-not-exist", "00-inbox"])
    found = set(f.relative_to(VAULT).as_posix() for f in scanner.scan())
    assert "00-inbox/quick-note.md" in found


# ── 4. is_ignored logic ────────────────────────────────────────────

def test_is_ignored_directory_prefix():
    scanner = make_scanner()
    assert scanner._is_ignored(".obsidian/app.json")
    assert scanner._is_ignored(".obsidian/plugins/foo/main.js")


def test_is_ignored_directory_does_not_match_similar_prefix():
    """'.trash' pattern should not ignore files starting with 'trash' (no slash)."""
    scanner = make_scanner()
    assert not scanner._is_ignored("not-trash/file.md")


def test_is_ignored_fnmatch_pattern():
    scanner = make_scanner(ignore_patterns=["*.tmp"])
    assert scanner._is_ignored("notes/something.tmp")
    assert not scanner._is_ignored("notes/something.md")
