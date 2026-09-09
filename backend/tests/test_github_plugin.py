"""Tests for src.harvester.github.plugin.GitHubHarvesterPlugin."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.harvester import (
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from src.harvester.github import (
    GitHubConfig,
    GitHubHarvesterPlugin,
)
from src.harvester.github.client import GitHubAuthError, GitHubClient
from src.harvester.registry import create_plugin, registered_source_types


def _make_plugin(**overrides) -> tuple[GitHubHarvesterPlugin, AsyncMock]:
    cfg = GitHubConfig(repos=["o/r"], **overrides)
    mock_client = AsyncMock(spec=GitHubClient)
    plugin = GitHubHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


# ── Scaffold ──────────────────────────────────────────────────────


def test_plugin_is_a_sourceplugin():
    plugin, _ = _make_plugin()
    assert isinstance(plugin, SourcePlugin)


def test_factory_registered():
    assert "github" in registered_source_types()


def test_factory_raises_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="GitHub token not found"):
        create_plugin("github", {"repos": ["o/r"]})


def test_factory_raises_without_repos(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    with pytest.raises(EnvironmentError, match="repos is required"):
        create_plugin("github", {})


# ── test_connection ───────────────────────────────────────────────


async def test_test_connection_healthy_uses_login():
    plugin, mock = _make_plugin()
    mock.get.return_value = {"login": "alice"}
    status = await plugin.test_connection()
    assert isinstance(status, HealthStatus) and status.healthy
    assert "@alice" in status.message


async def test_test_connection_auth_error_remediation():
    plugin, mock = _make_plugin()
    mock.get.side_effect = GitHubAuthError("Bad credentials", status_code=401)
    status = await plugin.test_connection()
    assert not status.healthy
    assert "GITHUB_TOKEN" in status.message


# ── list_documents flag matrix ────────────────────────────────────


async def _setup_basic_list_returns(mock):
    """One issue, one PR, one discussion, one README."""
    async def issues_pager(repo, since=None):
        for item in [
            {"number": 1, "title": "Issue A", "state": "open",
             "user": {"login": "alice"}, "updated_at": "2026-05-13T10:00:00Z",
             "labels": []},
            {"number": 2, "title": "PR A", "state": "open",
             "user": {"login": "bob"}, "updated_at": "2026-05-13T11:00:00Z",
             "labels": [], "pull_request": {"url": "..."}},
        ]:
            yield item

    async def discussion_pager(repo, since=None):
        for node in [
            {"number": 1, "title": "Q?", "category": {"slug": "q-a"},
             "author": {"login": "carol"}, "updatedAt": "2026-05-13T12:00:00Z"},
        ]:
            yield node

    mock.list_issues_and_prs = issues_pager
    mock.list_discussions = discussion_pager
    mock.get_readme_doc = AsyncMock(return_value={
        "readme": {"path": "README.md", "html_url": "https://github.com/o/r/blob/main/README.md"},
        "repo": {"default_branch": "main", "updated_at": "2026-05-13T14:00:00Z"},
    })


async def test_list_documents_emits_all_four_types_by_default():
    plugin, _mock = _make_plugin()
    await _setup_basic_list_returns(plugin._repos_x)
    refs = await plugin.list_documents()
    by_type = {r.metadata["document_type"] for r in refs}
    assert by_type == {"issue", "pr", "discussion", "readme"}


async def test_include_prs_false_filters_out_pr():
    plugin, _ = _make_plugin(include_prs=False)
    await _setup_basic_list_returns(plugin._repos_x)
    refs = await plugin.list_documents()
    assert all(r.metadata["document_type"] != "pr" for r in refs)
    # Issue still present.
    assert any(r.metadata["document_type"] == "issue" for r in refs)


async def test_include_discussions_false_skips_graphql():
    plugin, _ = _make_plugin(include_discussions=False)
    await _setup_basic_list_returns(plugin._repos_x)
    refs = await plugin.list_documents()
    assert all(r.metadata["document_type"] != "discussion" for r in refs)


async def test_include_readme_false_skips_readme():
    plugin, _ = _make_plugin(include_readme=False)
    await _setup_basic_list_returns(plugin._repos_x)
    refs = await plugin.list_documents()
    assert all(r.metadata["document_type"] != "readme" for r in refs)


async def test_bot_authors_excluded_from_issues():
    plugin, _ = _make_plugin()

    async def issues_pager(repo, since=None):
        for item in [
            {"number": 1, "title": "auto", "state": "open",
             "user": {"login": "Dependabot[bot]"},   # case-insensitive match
             "updated_at": "2026-05-13T10:00:00Z", "labels": []},
            {"number": 2, "title": "human", "state": "open",
             "user": {"login": "alice"},
             "updated_at": "2026-05-13T11:00:00Z", "labels": []},
        ]:
            yield item

    async def empty(repo, since=None):
        return
        yield {}  # pragma: no cover - makes this an async generator

    plugin._repos_x.list_issues_and_prs = issues_pager
    plugin._repos_x.list_discussions = empty
    plugin._repos_x.get_readme_doc = AsyncMock(return_value=None)
    refs = await plugin.list_documents()
    assert all("Dependabot" not in (r.metadata.get("author") or "") for r in refs)


# ── fetch_document ────────────────────────────────────────────────


async def test_fetch_document_issue_dispatch():
    plugin, _ = _make_plugin()
    plugin._repos_x.get_full_issue = AsyncMock(return_value={
        "issue": {"number": 42, "title": "x", "state": "open",
                  "user": {"login": "alice"}, "body": "b",
                  "created_at": "...", "updated_at": "...", "html_url": "..."},
        "comments": [],
    })
    doc_ref = DocRef(
        source_id="o/r#42", title="x", source_type="github",
        modified_at=datetime.now(tz=timezone.utc),
        metadata={"document_type": "issue", "repo": "o/r", "number": 42},
    )
    raw = await plugin.fetch_document(doc_ref)
    assert isinstance(raw, RawDocument)
    assert raw.format == "json"
    assert raw.metadata["document_type"] == "issue"
    plugin._repos_x.get_full_issue.assert_awaited_once_with("o/r", 42)


async def test_fetch_attachment_raises_not_implemented():
    plugin, _ = _make_plugin()
    from src.harvester import AttachmentRef
    att = AttachmentRef(source_id="x", filename="x.png", url="...")
    with pytest.raises(NotImplementedError):
        await plugin.fetch_attachment(att)


# ── normalize ────────────────────────────────────────────────────


def test_normalize_dispatches_on_document_type():
    plugin, _ = _make_plugin()
    envelope = {"issue": {"number": 1, "title": "T", "state": "open",
                          "user": {"login": "alice"}, "body": "hi"},
                "comments": []}
    raw = RawDocument(
        source_id="o/r#1", title="x",
        content=json.dumps(envelope).encode(),
        format="json",
        metadata={"document_type": "issue", "repo": "o/r"},
    )
    out = plugin.normalize(raw)
    assert isinstance(out, NormalizedDocument)
    assert "[Issue #1]" in out.markdown
    assert out.frontmatter == {}
