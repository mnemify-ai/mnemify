"""Jira source plugin — models and public API.

Implemented through ATL-25.  The module exposes the public names (config
dataclass, client, extractors, plugin) and self-registers with the
plugin registry at import time.  Phase-1 task coverage:

- ``ATL-20`` — :class:`JiraClient` ``atlassian-python-api`` wrapper
  (``jql_search``, ``get_issue``, ``list_fields``, ``get_myself``,
  ``download_attachment``) — DONE.
- ``ATL-21`` — ADF → plain text via :func:`text_from_adf` — DONE.
- ``ATL-22`` — :func:`flatten_issue_fields` (issue JSON → metadata dict
  per plan §3.2 "RawDocument.metadata required keys") — DONE.
- ``ATL-23`` — :class:`IssueExtractor` JQL enumeration / full-issue fetch,
  plus the :func:`build_jql` helper — DONE.
- ``ATL-24`` — :class:`JiraHarvesterPlugin` SourcePlugin contract — DONE.
- ``ATL-25`` — factory env-var resolution (``JIRA_EMAIL`` /
  ``JIRA_API_TOKEN``) with remediation on missing credentials — DONE
  (this module).
- ``ATL-31`` — attachment download body (still a stub on the plugin;
  ``AttachmentRef`` population landed in ATL-24).
- ``ATL-40`` — :func:`discover_story_points_field` — DONE.
- ``ATL-41`` — plugin lazy story-points field cache — DONE (bundled
  into ATL-24).

Decisions that shape this module (from the 2026-04-19 design review):

- Storage format is the **raw Jira REST issue JSON** (ADF preserved).
- Enumeration is **JQL** (``project = KEY ORDER BY updated DESC``) — *not*
  agile boards / sprint walks.
- Separate auth env vars ``JIRA_EMAIL`` + ``JIRA_API_TOKEN`` (users can
  point both Confluence + Jira ``token_env`` at a shared variable).
- Story-points custom field is **auto-discovered** via
  ``/rest/api/3/field`` with a YAML override escape hatch — never
  hardcode ``customfield_10016``.
- Dependency is ``atlassian-python-api`` wrapped in ``asyncio.to_thread``.
- Default per-source ``concurrency: 3``.

Registers itself with the plugin registry at import time so the CLI can
instantiate it via ``create_plugin("jira", config)``.  ATL-04 wired
``src.harvester.jira`` into ``_ensure_plugins_registered`` so callers
do not need to import this module explicitly.
"""

from __future__ import annotations

from .models import JiraConfig, JiraIssue
from .client import JiraClient
from .adf import text_from_adf
from .fields import discover_story_points_field, flatten_issue_fields
from .issues import IssueExtractor
from .jql import build_jql
from .plugin import JiraHarvesterPlugin

__all__ = [
    # Models
    "JiraConfig",
    "JiraIssue",
    # Client + extractors
    "JiraClient",
    "IssueExtractor",
    "text_from_adf",
    "build_jql",
    "discover_story_points_field",
    "flatten_issue_fields",
    # Plugin
    "JiraHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_jira_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.jira`` sub-dict from mnemify.yaml (or
    a programmatic dict matching :class:`JiraConfig`).

    Returns ``(plugin, None)`` — ``atlassian-python-api`` is synchronous
    and has no ``aclose`` to pump; teardown lives in ``plugin.aclose()``.

    ATL-25 — resolves the Atlassian email + API token from the env vars
    named by :attr:`JiraConfig.email_env` / :attr:`JiraConfig.token_env`
    and raises :class:`EnvironmentError` with a remediation hint naming
    the offending env var when either is missing.  Mirrors the Notion
    factory contract (``src/harvester/notion/__init__.py``).
    """
    import os

    jira_cfg = JiraConfig(
        base_url=config["base_url"],
        email_env=config.get("email_env", "JIRA_EMAIL"),
        token_env=config.get("token_env", "JIRA_API_TOKEN"),
        project_keys=config.get("project_keys", []),
        concurrency=config.get("concurrency", 3),
        story_points_field=config.get("story_points_field", None),
    )

    email = config.get("email") or os.getenv(jira_cfg.email_env, "")
    token = config.get("token") or os.getenv(jira_cfg.token_env, "")
    if not email:
        raise EnvironmentError(
            f"Jira email not found. Set the {jira_cfg.email_env!r} environment "
            "variable or provide 'email' directly in the source config."
        )
    if not token:
        raise EnvironmentError(
            f"Jira API token not found. Set the {jira_cfg.token_env!r} environment "
            "variable or provide 'token' directly in the source config."
        )

    client = JiraClient(
        base_url=jira_cfg.base_url,
        email=email,
        token=token,
    )
    plugin = JiraHarvesterPlugin(jira_cfg, client=client)
    return plugin, None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("jira", _create_jira_plugin)
