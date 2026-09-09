"""Failure-mode tests for the GitHub plugin."""

from __future__ import annotations

from unittest.mock import AsyncMock


from src.harvester.github import GitHubConfig, GitHubHarvesterPlugin
from src.harvester.github.client import GitHubAPIError, GitHubAuthError, GitHubClient


def _make_plugin(**overrides) -> tuple[GitHubHarvesterPlugin, AsyncMock]:
    cfg = GitHubConfig(repos=["o/r"], **overrides)
    mock_client = AsyncMock(spec=GitHubClient)
    plugin = GitHubHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


async def test_repo_with_no_readme_emits_no_readme_docref():
    plugin, _ = _make_plugin()

    async def empty(*args, **kwargs):
        return
        yield {}  # pragma: no cover - makes this an async generator

    plugin._repos_x.list_issues_and_prs = empty
    plugin._repos_x.list_discussions = empty
    plugin._repos_x.get_readme_doc = AsyncMock(return_value=None)
    refs = await plugin.list_documents()
    assert all(r.metadata.get("document_type") != "readme" for r in refs)


async def test_discussion_auth_error_warns_but_continues_with_other_types(caplog):
    plugin, _ = _make_plugin()

    async def issues_pager(repo, since=None):
        yield {"number": 1, "title": "x", "state": "open",
               "user": {"login": "alice"},
               "updated_at": "2026-05-13T10:00:00Z", "labels": []}

    async def discussion_pager(repo, since=None):
        # GraphQL auth failure (e.g. PAT lacks Discussions read)
        raise GitHubAuthError("Resource not accessible by personal access token")
        yield {}  # pragma: no cover

    plugin._repos_x.list_issues_and_prs = issues_pager
    plugin._repos_x.list_discussions = discussion_pager
    plugin._repos_x.get_readme_doc = AsyncMock(return_value=None)

    caplog.set_level("WARNING")
    refs = await plugin.list_documents()
    assert any(r.metadata["document_type"] == "issue" for r in refs)
    # No discussion refs.
    assert all(r.metadata["document_type"] != "discussion" for r in refs)
    # Friendly hint logged.
    assert any("PAT scope" in rec.message or "discussions" in rec.message.lower()
               for rec in caplog.records)


async def test_repo_404_skipped_continues_other_repos(caplog):
    cfg = GitHubConfig(repos=["o/missing", "o/exists"])
    mock_client = AsyncMock(spec=GitHubClient)
    plugin = GitHubHarvesterPlugin(cfg, client=mock_client)

    call_state = {"repo": None}

    async def issues_pager(repo, since=None):
        call_state["repo"] = repo
        if repo == "o/missing":
            raise GitHubAPIError("Not Found", status_code=404)
        yield {"number": 1, "title": "x", "state": "open",
               "user": {"login": "alice"},
               "updated_at": "2026-05-13T10:00:00Z", "labels": []}

    async def empty_disc(repo, since=None):
        return
        yield {}  # pragma: no cover - makes this an async generator

    plugin._repos_x.list_issues_and_prs = issues_pager
    plugin._repos_x.list_discussions = empty_disc
    plugin._repos_x.get_readme_doc = AsyncMock(return_value=None)

    caplog.set_level("WARNING")
    refs = await plugin.list_documents()
    # The good repo's issue is present.
    assert any(r.metadata["repo"] == "o/exists" for r in refs)
    assert all(r.metadata["repo"] != "o/missing" for r in refs)


async def test_test_connection_handles_unreachable_api():
    plugin, mock = _make_plugin()
    mock.get.side_effect = GitHubAPIError("Connection refused")
    status = await plugin.test_connection()
    assert not status.healthy
    assert "unreachable" in status.message.lower()


async def test_typed_error_lineage():
    """Auth + RateLimit errors must remain catchable as the base GitHubAPIError."""
    from src.harvester.github.client import GitHubRateLimitError
    assert isinstance(GitHubAuthError("x"), GitHubAPIError)
    assert isinstance(GitHubRateLimitError("y"), GitHubAPIError)
