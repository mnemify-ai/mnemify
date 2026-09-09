"""GitHub source plugin — implements :class:`SourcePlugin` for the orchestrator.

For each repo in ``GitHubConfig.repos``, harvest:

- Issues (``document_type="issue"``, ``source_id={repo}#{n}``)
- PRs (``document_type="pr"``, ``source_id={repo}#{n}`` — PRs share the
  issue numbering space; ``document_type`` disambiguates)
- Discussions (``document_type="discussion"``,
  ``source_id={repo}:discussion#{n}``)
- READMEs (``document_type="readme"``, ``source_id={repo}:README``)

Wikis are deferred — they need a ``git clone`` of ``.wiki.git`` which
breaks the HTTP-only plugin contract and deserves its own design.

``list_documents(since)`` honours the incremental-sync contract: the
issues+PRs endpoint accepts ``since=`` server-side; discussions are
walked ``UPDATED_AT_DESC`` and the loop breaks when items fall below
the cutoff; READMEs use repo-level ``updated_at`` as the freshness
signal (cheap; the orchestrator's content-hash gate suppresses
redundant writes when the file actually didn't change).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from .client import GitHubAPIError, GitHubAuthError, GitHubClient
from .fields import (
    flatten_discussion_fields,
    flatten_issue_fields,
    flatten_pr_fields,
    flatten_readme_fields,
)
from .gql import parse_iso8601
from .models import GitHubConfig
from .normalizer import github_to_markdown
from .repos import RepoExtractor

logger = logging.getLogger(__name__)


class GitHubHarvesterPlugin(SourcePlugin):
    """GitHub implementation of :class:`SourcePlugin`."""

    SOURCE_TYPE = "github"

    def __init__(self, config: GitHubConfig, *, client: GitHubClient | None = None) -> None:
        self.config = config
        self._client = client or GitHubClient(token="")
        self._repos_x = RepoExtractor(self._client)
        self._bot_set = {name.lower() for name in config.bot_authors_exclude}

    # ── SourcePlugin interface ────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        try:
            me = await self._client.get("/user")
        except GitHubAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"GitHub auth failed: {exc}. Check {self.config.token_env} in .env "
                    "(fine-grained or classic PAT)."
                ),
            )
        except GitHubAPIError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"GitHub API unreachable: {exc}",
            )
        login = (me or {}).get("login", "?") if isinstance(me, dict) else "?"
        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"GitHub OK: authenticated as @{login}, {len(self.config.repos)} repo(s) configured.",
            details={"login": login, "repo_count": len(self.config.repos)},
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        # FIXME(scope-aware-since): the orchestrator passes ``since=None`` to
        # avoid the scope-expansion bug source-wide ``since`` caused on
        # Notion/Confluence. GitHub honours ``since`` server-side
        # (issues/PRs/discussions), so this disables a real cost optimization.
        # When this plugin is wired into the UI, restore the optimization by
        # comparing the current ``repos`` against the per-run scope recorded
        # in the manifest and passing ``since`` only when scope is unchanged.
        results: list[DocRef] = []
        for repo in self.config.repos:
            try:
                results.extend(await self._list_for_repo(repo, since=since))
            except GitHubAuthError as exc:
                logger.warning("github: auth/permission error for %s — %s", repo, exc)
                continue
            except GitHubAPIError as exc:
                logger.warning("github: list failed for %s — %s", repo, exc)
                continue
        logger.debug("GitHubHarvesterPlugin.list_documents: %d docs across %d repos",
                     len(results), len(self.config.repos))
        return results

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        doc_type = doc_ref.metadata.get("document_type")
        repo = doc_ref.metadata.get("repo")
        number = doc_ref.metadata.get("number")
        if doc_type == "issue":
            envelope = await self._repos_x.get_full_issue(repo, number)
            metadata = flatten_issue_fields(
                issue=envelope["issue"],
                comments=envelope["comments"],
                repo=repo,
            )
        elif doc_type == "pr":
            envelope = await self._repos_x.get_full_pr(repo, number)
            metadata = flatten_pr_fields(
                pr=envelope["pr"],
                comments=envelope["comments"],
                reviews=envelope["reviews"],
                repo=repo,
            )
        elif doc_type == "discussion":
            envelope = await self._repos_x.get_full_discussion(repo, number)
            metadata = flatten_discussion_fields(
                discussion=envelope["discussion"],
                comments=envelope["discussion"].get("comments", []),
                repo=repo,
            )
        elif doc_type == "readme":
            readme_envelope = await self._repos_x.get_readme_doc(repo)
            if readme_envelope is None:
                raise GitHubAPIError(f"README disappeared for {repo} between list and fetch")
            envelope = readme_envelope
            metadata = flatten_readme_fields(
                readme=envelope["readme"],
                repo_meta=envelope["repo"],
                repo=repo,
            )
        else:
            raise ValueError(f"unknown github document_type: {doc_type!r}")

        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            format="json",
            metadata=metadata,
            attachments=[],  # V1: no first-class attachments
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        # GitHub issue/PR/discussion bodies inline images via markdown URLs
        # rather than first-class attachments; V1 doesn't emit AttachmentRefs.
        raise NotImplementedError(
            "GitHub plugin does not emit first-class attachments in V1"
        )

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        md = github_to_markdown(raw.content, raw.metadata)
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=md,
            frontmatter={},
            normalizer_version="0.1.0",
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Per-repo list dispatcher ──────────────────────────────────

    async def _list_for_repo(self, repo: str, *, since: datetime | None) -> list[DocRef]:
        out: list[DocRef] = []

        if self.config.include_issues or self.config.include_prs:
            async for item in self._repos_x.list_issues_and_prs(repo, since=since):
                author = ((item.get("user") or {}).get("login") or "").lower()
                if author and author in self._bot_set:
                    continue
                is_pr = "pull_request" in item
                if is_pr and not self.config.include_prs:
                    continue
                if not is_pr and not self.config.include_issues:
                    continue
                out.append(self._issue_or_pr_doc_ref(repo, item, is_pr=is_pr))

        if self.config.include_discussions:
            try:
                async for node in self._repos_x.list_discussions(repo, since=since):
                    author = ((node.get("author") or {}).get("login") or "").lower()
                    if author and author in self._bot_set:
                        continue
                    out.append(self._discussion_doc_ref(repo, node))
            except GitHubAuthError as exc:
                logger.warning(
                    "github: discussions unavailable for %s (PAT scope?) — %s. "
                    "Issues/PRs/README still harvested.",
                    repo, exc,
                )
            except GitHubAPIError as exc:
                logger.warning("github: discussions failed for %s — %s", repo, exc)

        if self.config.include_readme:
            doc_ref = await self._readme_doc_ref(repo)
            if doc_ref is not None:
                out.append(doc_ref)

        return out

    # ── DocRef builders ───────────────────────────────────────────

    def _issue_or_pr_doc_ref(self, repo: str, item: dict, *, is_pr: bool) -> DocRef:
        number = item.get("number")
        updated = _parse_rest_iso(item.get("updated_at"))
        kind = "pr" if is_pr else "issue"
        prefix = "PR" if is_pr else "Issue"
        return DocRef(
            source_id=f"{repo}#{number}",
            title=f"[{prefix} #{number}] {item.get('title') or '(untitled)'}",
            source_type=self.SOURCE_TYPE,
            source_url=item.get("html_url"),
            modified_at=updated,
            metadata={
                "document_type": kind,
                "repo": repo,
                "number": number,
                "state": item.get("state"),
                "author": (item.get("user") or {}).get("login"),
                "labels": [lbl.get("name") for lbl in (item.get("labels") or []) if lbl.get("name")],
                "is_pr": is_pr,
            },
        )

    def _discussion_doc_ref(self, repo: str, node: dict) -> DocRef:
        number = node.get("number")
        updated = parse_iso8601(node.get("updatedAt"))
        return DocRef(
            source_id=f"{repo}:discussion#{number}",
            title=f"[Discussion #{number}] {node.get('title') or '(untitled)'}",
            source_type=self.SOURCE_TYPE,
            source_url=node.get("url"),
            modified_at=updated,
            metadata={
                "document_type": "discussion",
                "repo": repo,
                "number": number,
                "category": (node.get("category") or {}).get("slug"),
                "author": (node.get("author") or {}).get("login"),
                "locked": bool(node.get("locked")),
            },
        )

    async def _readme_doc_ref(self, repo: str) -> DocRef | None:
        # Verify the README exists at list time so we never emit a DocRef
        # the fetch step would later 404 on. Costs one extra REST call per
        # repo per harvest; cheap given the per-repo budget of 5 calls total.
        try:
            envelope = await self._repos_x.get_readme_doc(repo)
        except GitHubAPIError as exc:
            logger.warning("github: readme/repo fetch failed for %s — %s", repo, exc)
            return None
        if envelope is None:
            return None
        repo_meta = envelope["repo"]
        readme = envelope["readme"]
        updated = _parse_rest_iso(repo_meta.get("updated_at"))
        return DocRef(
            source_id=f"{repo}:README",
            title=f"{repo} — README",
            source_type=self.SOURCE_TYPE,
            source_url=readme.get("html_url") or (
                f"https://github.com/{repo}/blob/{repo_meta.get('default_branch', 'main')}/README.md"
            ),
            modified_at=updated,
            metadata={
                "document_type": "readme",
                "repo": repo,
                "default_branch": repo_meta.get("default_branch"),
            },
        )


def _parse_rest_iso(value: str | None) -> datetime | None:
    """Parse GitHub REST API ISO 8601 (always trailing ``Z``).

    Returns ``None`` on parse failure — matching ``gql.parse_iso8601``.
    Returning ``now()`` here would make a corrupt ``updated_at`` look
    perpetually fresh and defeat the incremental harvest gate.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
