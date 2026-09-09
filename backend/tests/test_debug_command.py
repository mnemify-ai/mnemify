"""Tests for the CLI debug command — source dispatch and Obsidian integration.

Verifies that:
- `debug --source obsidian` runs through the full ABC surface (connection,
  list, fetch, fetch_attachment) against the fixture vault.
- `debug --source unknown_source` reports a clear error.
- The debug argparser now accepts --source and --config flags.
- The refactored command no longer hardcodes Notion internals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cli import _build_parser, _cmd_debug

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


# ── Parser shape ──────────────────────────────────────────────────────────────

def test_debug_parser_accepts_source_flag():
    parser = _build_parser()
    args = parser.parse_args(["debug", "--source", "obsidian"])
    assert args.source == "obsidian"


def test_debug_parser_defaults_source_to_notion():
    parser = _build_parser()
    args = parser.parse_args(["debug"])
    assert args.source == "notion"


def test_debug_parser_accepts_config_flag(tmp_path):
    cfg = tmp_path / "mnemify.yaml"
    cfg.write_text("sources:\n  obsidian:\n    vault_path: /tmp\n")
    parser = _build_parser()
    args = parser.parse_args(["debug", "--config", str(cfg)])
    assert args.config == str(cfg)


# ── Obsidian debug run — fixture vault ───────────────────────────────────────

async def test_debug_obsidian_runs_full_flow(tmp_path, capsys):
    """End-to-end: debug --source obsidian against the fixture vault.

    Builds a minimal YAML config pointing at the fixture vault, injects it
    via --config, and runs _cmd_debug.  Verifies the key output lines appear.
    """
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(
        f"sources:\n  obsidian:\n    vault_path: {VAULT}\n",
        encoding="utf-8",
    )

    parser = _build_parser()
    args = parser.parse_args(
        ["debug", "--source", "obsidian", "--config", str(cfg_file)]
    )

    await _cmd_debug(args)

    captured = capsys.readouterr().out
    assert "Source: obsidian" in captured
    assert "1. Testing connection..." in captured
    assert "OK —" in captured
    assert "2. Listing documents" in captured
    assert "Total:" in captured
    assert "3. Fetching sample document:" in captured
    assert "Format      : md" in captured


async def test_debug_obsidian_writes_output_files(tmp_path):
    """debug command should write the raw sample and the normalized markdown."""
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(
        f"sources:\n  obsidian:\n    vault_path: {VAULT}\n",
        encoding="utf-8",
    )

    parser = _build_parser()
    args = parser.parse_args(
        ["debug", "--source", "obsidian", "--config", str(cfg_file)]
    )

    # Redirect DATA_DIR to tmp_path so we don't pollute the real .mnemify/
    import src.cli as cli_module
    original_data_dir = cli_module.DATA_DIR
    cli_module.DATA_DIR = tmp_path
    try:
        await _cmd_debug(args)
    finally:
        cli_module.DATA_DIR = original_data_dir

    # For Obsidian the raw format is "md" so debug_sample.md is the raw
    # bytes file. The normalized markdown also writes to debug_sample.md
    # (overwriting); assert it exists. The legacy debug_sample.txt is gone.
    assert (tmp_path / "debug_sample.md").exists(), "Expected debug_sample.md to be written"


async def test_debug_obsidian_reports_attachments(tmp_path, capsys):
    """When the sample doc has attachments, they should be listed."""
    # Use a config that includes meetings/q2-planning.md which has diagram.png
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(
        f"sources:\n  obsidian:\n    vault_path: {VAULT}\n    watch_folders:\n      - meetings\n",
        encoding="utf-8",
    )

    parser = _build_parser()
    args = parser.parse_args(
        ["debug", "--source", "obsidian", "--config", str(cfg_file)]
    )

    import src.cli as cli_module
    original_data_dir = cli_module.DATA_DIR
    cli_module.DATA_DIR = tmp_path
    try:
        await _cmd_debug(args)
    finally:
        cli_module.DATA_DIR = original_data_dir

    captured = capsys.readouterr().out
    # The q2-planning.md note embeds diagram.png, so we should see attachment output
    assert "4." in captured  # attachment step should appear


# ── Unknown source ────────────────────────────────────────────────────────────

async def test_debug_unknown_source_raises_value_error(tmp_path, capsys):
    """debug --source unknown_xyz should propagate ValueError from registry."""
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text("sources: {}\n", encoding="utf-8")

    parser = _build_parser()
    args = parser.parse_args(
        ["debug", "--source", "unknown_xyz", "--config", str(cfg_file)]
    )

    with pytest.raises(ValueError, match="Unknown source type"):
        await _cmd_debug(args)


# ── Notion path: no longer hardcodes Notion internals ────────────────────────

def test_debug_cmd_does_not_import_notion_client_directly():
    """The refactored _cmd_debug must not import NotionClient or NotionHarvesterPlugin
    directly.  All source access now goes through the plugin registry."""
    import inspect
    import src.cli as cli_module

    source = inspect.getsource(cli_module._cmd_debug)
    assert "NotionClient" not in source, (
        "_cmd_debug should not directly import NotionClient — use registry"
    )
    assert "NotionHarvesterPlugin" not in source, (
        "_cmd_debug should not directly import NotionHarvesterPlugin — use registry"
    )


def test_debug_cmd_does_not_call_notion_specific_attachments_download_all():
    """The old code called plugin.attachments.download_all() — a Notion-only method.
    The refactored version must use plugin.fetch_attachment() instead."""
    import inspect
    import src.cli as cli_module

    source = inspect.getsource(cli_module._cmd_debug)
    assert "download_all" not in source, (
        "_cmd_debug should not call .download_all() — use fetch_attachment() via ABC"
    )
