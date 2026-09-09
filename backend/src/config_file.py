"""YAML configuration file loader for Mnemify Harvester.

Search order:
  1. Path passed via --config CLI flag (explicit)
  2. ./mnemify.yaml  (current working directory)
  3. ~/.mnemify/mnemify.yaml (user home)

Returns a plain dict; the caller merges with CLI flag overrides.
Returns an empty dict when no config file is found.

Supported schemas
-----------------

Multi-source (preferred)::

    sources:
      notion:
        enabled: true
        token_env: "NOTION_TOKEN"
        concurrency: 5
        write_back:
          enabled: false
          property: "Harvested At"

      obsidian:
        enabled: true
        vault_path: "/Users/you/obsidian-vault"
        watch_folders:
          - "00-inbox"
          - "daily"
        ignore_patterns:
          - "templates/*"

    # Global settings
    raw_root: .mnemify/raw
    converter_version: "0.1.0"

Legacy single-source (backward compatible — automatically wrapped)::

    source: notion
    concurrency: 5
    raw_root: .mnemify/raw
    converter_version: "0.1.0"
    write_back:
      enabled: false
      property: "Harvested At"

Additional source blocks may be nested under ``sources.<name>`` —
e.g. the Confluence source added in ATL-02 (Phase 1 Atlassian sprint)::

    sources:
      confluence:
        enabled: true
        base_url: "https://your-org.atlassian.net/wiki"
        email_env: "CONFLUENCE_EMAIL"
        token_env: "CONFLUENCE_API_TOKEN"
        space_keys: ["ENG", "PROD"]       # required; no "harvest everything"
        concurrency: 3

The ``sources.confluence`` block parses into
:class:`src.harvester.confluence.ConfluenceConfig` via the plugin factory
registered at import time.  The config file itself is schema-less (YAML
→ dict); the dataclass in the plugin package is the authoritative schema.

A sibling ``sources.jira`` block was added in ATL-03 (Phase 1 Atlassian
sprint)::

    sources:
      jira:
        enabled: true
        base_url: "https://your-org.atlassian.net"
        email_env: "JIRA_EMAIL"
        token_env: "JIRA_API_TOKEN"
        project_keys: ["CONN", "PLAT"]    # required; no "harvest everything"
        story_points_field: null          # null → auto-discover customfield
        concurrency: 3

The ``sources.jira`` block parses into
:class:`src.harvester.jira.JiraConfig` via the plugin factory registered
at import time.  As with Confluence, the config file is schema-less
(YAML → dict); the dataclass in the plugin package is the authoritative
schema.  ``story_points_field`` is optional: ``null`` (the default) asks
the plugin to auto-discover the custom field id at harvest time, while
an explicit ``"customfield_XXXXX"`` string is the escape hatch for sites
whose field layout the auto-discovery cannot resolve.

Unrecognised top-level keys are ignored — the loader is schema-less by
design; each plugin's dataclass (and ``src.terrain.compiler``) is the
authoritative schema for its slice of the config.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_PATHS: list[Path] = [
    Path("mnemify.yaml"),
    Path.home() / ".mnemify" / "mnemify.yaml",
]


def load_config_file(explicit_path: str | Path | None = None) -> dict:
    """Load and parse a mnemify YAML config file.

    Args:
        explicit_path: If provided, only this path is tried (no fallback).

    Returns:
        Parsed YAML as a plain dict, or empty dict if no file found.

    Raises:
        ValueError: If a file is found but contains invalid YAML.
        FileNotFoundError: If an explicit path is given but does not exist.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(
            "pyyaml is required for YAML config file support. "
            "Install it with: pip install pyyaml"
        ) from e

    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        return _parse(path, yaml)

    for candidate in _DEFAULT_SEARCH_PATHS:
        if candidate.exists():
            return _parse(candidate, yaml)

    logger.debug("No mnemify.yaml config file found; using defaults")
    return {}


def get_source_config(file_cfg: dict, source_type: str) -> dict:
    """Extract the source-specific sub-config from a loaded config dict.

    Handles both the multi-source ``sources:`` schema and the legacy
    flat schema (backward compatibility).

    Returns an empty dict when the source is not configured.
    """
    if "sources" in file_cfg:
        return file_cfg.get("sources", {}).get(source_type, {})

    # Legacy flat schema — only Notion was supported
    if source_type == "notion":
        # Re-expose the keys that were previously at the top level
        notion_cfg: dict = {}
        for key in ("concurrency", "write_back", "token_env"):
            if key in file_cfg:
                notion_cfg[key] = file_cfg[key]
        return notion_cfg

    return {}


def _parse(path: Path, yaml) -> dict:
    """Read and parse one YAML file, raising ValueError on bad content."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise OSError(f"Could not read config file {path}: {e}") from e

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must be a YAML mapping, got {type(data).__name__}")

    logger.info(f"Loaded config from {path}")
    return data
