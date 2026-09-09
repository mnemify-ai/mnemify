"""GitHub plugin data models.

:class:`GitHubConfig` is the schema the YAML ``sources.github`` block
parses into. Mirrors :mod:`src.harvester.jira.models` in shape and
philosophy — the file is small because the bulk of GitHub-shaped data
lives in the raw JSON envelope rather than typed in-memory structures.

Auth-related decisions:

- Personal Access Token (fine-grained recommended; classic with
  ``repo`` + ``read:discussion`` works as a fallback). Token comes
  from the env var named by ``token_env`` (default ``GITHUB_TOKEN``).
- Fine-grained PATs gained GraphQL API support in April 2025, so
  Discussions (which are GraphQL-only) work on both token types now.

Scope decisions:

- Repos must be listed explicitly under ``repos:`` — no
  "harvest every repo I can see" mode in V1, mirroring how Jira
  requires ``project_keys`` and Confluence requires ``space_keys``.
- ``include_*`` flags toggle the four entity types (issues, PRs,
  discussions, READMEs). Wikis are deferred to V1.1 — they need a
  ``git clone`` of ``.wiki.git``, which breaks the HTTP-only plugin
  contract and deserves its own design pass.
- ``bot_authors_exclude`` defaults skip the three highest-volume
  noise sources (Dependabot, GitHub Actions, Renovate). The pattern
  ``*[bot]`` would catch more but produces false positives.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GitHubConfig:
    """Configuration for the GitHub harvester.

    Matches the ``sources.github`` block of ``mnemify.yaml`` 1:1.

    Attributes:
        repos: Explicit list of ``"owner/repo"`` strings to harvest.
            Required — no auto-discovery in V1.
        token_env: Name of the env var holding the PAT. Default
            ``GITHUB_TOKEN``.
        api_base: REST API root. Override for GitHub Enterprise Server
            (e.g. ``https://github.your-corp.com/api/v3``).
        graphql_endpoint: GraphQL endpoint. Override for GHES
            (e.g. ``https://github.your-corp.com/api/graphql``).
        include_issues: Harvest issues.
        include_prs: Harvest pull requests.
        include_discussions: Harvest discussions (GraphQL-only).
        include_readme: Harvest each repo's canonical README.
        bot_authors_exclude: Skip issues / PRs / discussions whose
            author login matches an entry in this list. Default skips
            the three biggest dependency-bots.
        concurrency: Per-source concurrency override; defaults to 3
            to stay well under GitHub's 5000/hour authenticated REST
            quota and avoid secondary-rate-limit triggers.
    """

    repos: list[str]
    token_env: str = "GITHUB_TOKEN"
    api_base: str = "https://api.github.com"
    graphql_endpoint: str = "https://api.github.com/graphql"
    include_issues: bool = True
    include_prs: bool = True
    include_discussions: bool = True
    include_readme: bool = True
    bot_authors_exclude: list[str] = field(default_factory=lambda: [
        "dependabot[bot]",
        "github-actions[bot]",
        "renovate[bot]",
    ])
    concurrency: int = 3
