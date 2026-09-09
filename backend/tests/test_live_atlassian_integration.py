"""Live opt-in Atlassian integration tests (ATL-60).

Unlike :mod:`tests.test_integration_confluence` and
:mod:`tests.test_integration_jira` — which replay fixture snapshots — these
tests hit a *real* Atlassian Cloud sandbox and are therefore **skipped by
default**.  They are a smoke gate for catching regressions against the
live REST surface that fixture tests cannot catch (auth drift, schema
additions, rate-limit behaviour, transport hiccups).

Opt-in contract
---------------

The tests only execute when **all** of the following env vars are set; any
unset var results in a clean skip with a specific reason (never an error):

- ``RUN_ATLASSIAN_INTEGRATION=1``          — top-level opt-in gate.
- Confluence: ``CONFLUENCE_EMAIL``, ``CONFLUENCE_API_TOKEN``,
  ``CONFLUENCE_TEST_BASE_URL``, ``CONFLUENCE_TEST_SPACE_KEY``.
- Jira: ``JIRA_EMAIL``, ``JIRA_API_TOKEN``, ``JIRA_TEST_BASE_URL``,
  ``JIRA_TEST_PROJECT_KEY``.

The ``*_TEST_*`` vars are a belt-and-braces guardrail: even with
credentials *and* the opt-in flag, the tests refuse to run without an
explicitly configured sandbox target, so they can never accidentally
point at a production site.

Assertion style
---------------

Assertions are strictly *structural* — we check types, required keys, and
non-emptiness per the §3.1 / §3.2 plan contracts.  We never assert on
sandbox-specific content (titles, IDs, counts) so the suite stays stable
across sandbox resets.

These tests run fast: one ``test_connection`` + one ``list_documents``
page + one ``fetch_document`` on the first DocRef per source.  Anything
more is better covered by the offline fixture tests.
"""

from __future__ import annotations

import os

import pytest

from src.harvester import DocRef, HealthStatus, RawDocument
from src.harvester.confluence.models import ConfluenceConfig
from src.harvester.confluence.plugin import ConfluenceHarvesterPlugin
from src.harvester.jira import JiraConfig, JiraHarvesterPlugin
from src.harvester.jira.client import JiraClient


# ── Module-level opt-in gate ─────────────────────────────────────

_OPT_IN_VAR = "RUN_ATLASSIAN_INTEGRATION"

pytestmark = pytest.mark.skipif(
    not os.environ.get(_OPT_IN_VAR),
    reason=(
        f"Live Atlassian integration opt-in — set {_OPT_IN_VAR}=1 "
        "(plus source-specific credential + sandbox env vars) to run."
    ),
)


# ── Credential / sandbox helpers ─────────────────────────────────


def _require_env(*names: str) -> dict[str, str]:
    """Return env var values, or ``pytest.skip`` naming what's missing.

    A single helper keeps every skip message in the same voice:
    "skipped: missing X, Y" — clear and greppable in CI output.
    """
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(
            "Live Atlassian integration requires env vars: "
            + ", ".join(missing)
            + " (set alongside RUN_ATLASSIAN_INTEGRATION=1)."
        )
    return {name: os.environ[name] for name in names}


# ── Confluence ───────────────────────────────────────────────────


@pytest.fixture
def confluence_plugin() -> ConfluenceHarvesterPlugin:
    """Build a real :class:`ConfluenceHarvesterPlugin` from env vars.

    Skips cleanly (not errors) if any required env var is unset.  The
    plugin's client talks to the live site — tests using this fixture
    will make network calls.
    """
    env = _require_env(
        "CONFLUENCE_EMAIL",
        "CONFLUENCE_API_TOKEN",
        "CONFLUENCE_TEST_BASE_URL",
        "CONFLUENCE_TEST_SPACE_KEY",
    )
    cfg = ConfluenceConfig(
        base_url=env["CONFLUENCE_TEST_BASE_URL"],
        space_keys=[env["CONFLUENCE_TEST_SPACE_KEY"]],
    )
    return ConfluenceHarvesterPlugin(
        cfg,
        email=env["CONFLUENCE_EMAIL"],
        token=env["CONFLUENCE_API_TOKEN"],
    )


async def test_confluence_connection_live(confluence_plugin):
    """The live Confluence credentials authenticate cleanly."""
    try:
        health = await confluence_plugin.test_connection()
        assert isinstance(health, HealthStatus)
        assert health.source_type == "confluence"
        assert health.healthy, f"Confluence health check failed: {health.message}"
    finally:
        await confluence_plugin.aclose()


async def test_confluence_list_and_fetch_live(confluence_plugin):
    """``list_documents`` yields at least one DocRef; ``fetch_document`` returns a well-shaped RawDocument.

    Assertions are deliberately structural (types + required §3.1 keys)
    so sandbox content churn never breaks the test.
    """
    try:
        refs = await confluence_plugin.list_documents()
        assert isinstance(refs, list)
        assert len(refs) >= 1, (
            "Sandbox space must contain at least one page; "
            "seed the configured CONFLUENCE_TEST_SPACE_KEY before running."
        )
        first = refs[0]
        assert isinstance(first, DocRef)
        assert first.source_type == "confluence"
        assert first.source_id
        assert isinstance(first.title, str)

        raw = await confluence_plugin.fetch_document(first)
        assert isinstance(raw, RawDocument)
        assert raw.source_id == first.source_id
        assert isinstance(raw.content, bytes)
        assert raw.format == "html"
        # §3.1 — metadata keys populated by fetch_document.
        assert isinstance(raw.metadata, dict)
        for key in (
            "document_type",
            "space_key",
            "version_number",
            "author_id",
            "author_name",
            "created_at",
            "updated_at",
            "ancestors",
            "labels",
            "attachment_count",
        ):
            assert key in raw.metadata, f"RawDocument.metadata missing §3.1 key: {key!r}"
        assert raw.metadata["document_type"] == "page"
    finally:
        await confluence_plugin.aclose()


# ── Jira ─────────────────────────────────────────────────────────


@pytest.fixture
def jira_plugin() -> JiraHarvesterPlugin:
    """Build a real :class:`JiraHarvesterPlugin` from env vars.

    Skips cleanly if any required env var is unset.  A credentialed
    :class:`JiraClient` is constructed here (rather than going through the
    ``__init__.py`` factory) because the factory resolves env var *names*
    from the config object; the integration test works with the values
    directly and bypasses that indirection.
    """
    env = _require_env(
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "JIRA_TEST_BASE_URL",
        "JIRA_TEST_PROJECT_KEY",
    )
    cfg = JiraConfig(
        base_url=env["JIRA_TEST_BASE_URL"],
        project_keys=[env["JIRA_TEST_PROJECT_KEY"]],
        story_points_field=None,  # exercise the live auto-discovery path
    )
    client = JiraClient(
        base_url=env["JIRA_TEST_BASE_URL"],
        email=env["JIRA_EMAIL"],
        token=env["JIRA_API_TOKEN"],
    )
    return JiraHarvesterPlugin(cfg, client=client)


async def test_jira_connection_live(jira_plugin):
    """The live Jira credentials authenticate cleanly."""
    try:
        health = await jira_plugin.test_connection()
        assert isinstance(health, HealthStatus)
        assert health.source_type == "jira"
        assert health.healthy, f"Jira health check failed: {health.message}"
    finally:
        await jira_plugin.aclose()


async def test_jira_list_and_fetch_live(jira_plugin):
    """``list_documents`` yields ≥1 DocRef; ``fetch_document`` returns a well-shaped RawDocument.

    Keeps assertions structural per §3.2 — no sandbox-content claims.
    """
    try:
        refs = await jira_plugin.list_documents()
        assert isinstance(refs, list)
        assert len(refs) >= 1, (
            "Sandbox project must contain at least one issue; "
            "seed the configured JIRA_TEST_PROJECT_KEY before running."
        )
        first = refs[0]
        assert isinstance(first, DocRef)
        assert first.source_type == "jira"
        assert first.source_id  # e.g. "ABC-123"
        assert "-" in first.source_id, (
            f"Unexpected Jira source_id shape: {first.source_id!r}"
        )

        raw = await jira_plugin.fetch_document(first)
        assert isinstance(raw, RawDocument)
        assert raw.source_id == first.source_id
        assert isinstance(raw.content, bytes)
        assert raw.format == "json"
        # §3.2 — flattened metadata keys populated by fetch_document.
        assert isinstance(raw.metadata, dict)
        for key in (
            "document_type",
            "project_key",
            "issue_type",
            "status",
            "summary",
            "updated",
        ):
            assert key in raw.metadata, f"RawDocument.metadata missing §3.2 key: {key!r}"
        assert raw.metadata["document_type"] == "issue"
    finally:
        await jira_plugin.aclose()
