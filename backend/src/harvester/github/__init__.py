"""GitHub source plugin — public API and registry self-registration.

Mirrors the Jira plugin shape. The factory reads ``sources.github``
from ``mnemify.yaml`` and constructs a :class:`GitHubHarvesterPlugin`
with a pre-configured :class:`GitHubClient`. The PAT comes from the
env var named by ``token_env`` (default ``GITHUB_TOKEN``).

Output-format contract: pure-body markdown (Confluence/Gmail pattern).
All structured metadata flows through ``RawDocument.metadata`` to the
manifest's ``documents.metadata`` JSON column.
"""

from __future__ import annotations

import os

from .client import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubClient,
    GitHubRateLimitError,
)
from .models import GitHubConfig
from .normalizer import github_to_markdown
from .plugin import GitHubHarvesterPlugin
from .repos import RepoExtractor

__all__ = [
    "GitHubConfig",
    "GitHubClient",
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "RepoExtractor",
    "GitHubHarvesterPlugin",
    "github_to_markdown",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_github_plugin(config: dict) -> tuple[GitHubHarvesterPlugin, None]:
    """Factory used by the plugin registry.

    ``config`` is the ``sources.github`` sub-dict from mnemify.yaml.
    Returns ``(plugin, None)`` — matching the Jira/Gmail convention.
    Client teardown lives in :meth:`GitHubHarvesterPlugin.aclose`.
    """
    repos = list(config.get("repos") or [])
    if not repos:
        raise EnvironmentError(
            "sources.github.repos is required and must be a non-empty list "
            "(e.g. [\"your-org/your-repo\"]). See example_mnemify.yaml."
        )

    cfg = GitHubConfig(
        repos=repos,
        token_env=config.get("token_env", "GITHUB_TOKEN"),
        api_base=config.get("api_base", "https://api.github.com"),
        graphql_endpoint=config.get("graphql_endpoint", "https://api.github.com/graphql"),
        include_issues=bool(config.get("include_issues", True)),
        include_prs=bool(config.get("include_prs", True)),
        include_discussions=bool(config.get("include_discussions", True)),
        include_readme=bool(config.get("include_readme", True)),
        bot_authors_exclude=list(config.get("bot_authors_exclude") or [
            "dependabot[bot]", "github-actions[bot]", "renovate[bot]",
        ]),
        concurrency=int(config.get("concurrency", 3)),
    )

    token = os.environ.get(cfg.token_env, "").strip()
    if not token:
        raise EnvironmentError(
            f"GitHub token not found: env var {cfg.token_env!r} is unset or empty. "
            f"Set it to a fine-grained PAT (Contents, Metadata, Issues, Pull requests, "
            f"Discussions: read) or a classic PAT with `repo` + `read:discussion`."
        )

    client = GitHubClient(
        token=token,
        api_base=cfg.api_base,
        graphql_endpoint=cfg.graphql_endpoint,
    )
    plugin = GitHubHarvesterPlugin(cfg, client=client)
    return plugin, None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("github", _create_github_plugin)
