"""/api/connections/* — the surface the wizard calls."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config_file import load_config_file
from src.harvester.manifest import HarvestManifest
from src.sources import is_enabled

from .credential_store import (
    delete_secrets,
    has_secret,
    refresh,
    save_secret,
    write_secrets,
)
from .yaml_writer import disable_source, read_config, upsert_source

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────

from src import paths  # data dir resolved at call time — see src/paths.py

# Exceptions that mean "the outbound call to a provider failed" rather than
# "Mnemify has a bug" — network blips, timeouts, DNS, TLS, and the
# UnicodeEncodeError httpx raises when a pasted token has a stray non-ASCII
# character (smart quotes, zero-width spaces). These must surface to the
# wizard as a readable reason, never as a bare HTTP 500.
_OUTBOUND_ERRORS = (httpx.HTTPError, ValueError, UnicodeError, OSError)


def _outbound_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "Connection to the provider timed out — check your network and retry."
    if isinstance(exc, httpx.TransportError):
        return f"Couldn't reach the provider: {exc.__class__.__name__}."
    if isinstance(exc, UnicodeError):
        return "Token contains an unexpected character — re-copy it (watch for smart quotes / hidden whitespace)."
    return f"Request to the provider failed: {exc.__class__.__name__}."


def _doc_count(source: str) -> int:
    db = paths.data_dir() / "harvest-manifest.db"
    if not db.exists():
        return 0
    try:
        manifest = HarvestManifest(db)
        return len(manifest.get_documents(source_type=source))
    except Exception:  # noqa: BLE001
        return 0


def _last_harvest_at(source: str) -> str | None:
    db = paths.data_dir() / "harvest-manifest.db"
    if not db.exists():
        return None
    try:
        manifest = HarvestManifest(db)
        dt = manifest.get_last_harvest_time(source)
        return dt.isoformat() if dt else None
    except Exception:  # noqa: BLE001
        return None


def _pending_scope_count(source: str, scope: list[str]) -> int:
    """Count scope ids added since the last successful harvest run.

    Compares the current YAML scope against ``last_scope_snapshot`` recorded
    at the end of the last completed non-scoped run (see
    ``manifest.set_last_scope_snapshot`` + ``api/orchestrator._run_one``).
    Only *additions* count — removing items doesn't need a re-harvest.

    Returns ``len(scope)`` when there's no recorded snapshot yet (fresh
    connection that hasn't been harvested), so a new install still nudges
    the user to run the first harvest.

    A stable scope-diff replaces the earlier approach of counting scope ids
    whose ``origin_scope_id`` was missing from the manifest. That count was
    unreliable: it drifted while a harvest was in flight, stayed non-zero
    after harvests of empty spaces (no docs to stamp), and falsely flagged
    legacy rows whose ``origin_scope_id`` column was NULL.
    """
    cleaned = [s for s in scope if s]
    if not cleaned:
        return 0
    db = paths.data_dir() / "harvest-manifest.db"
    if not db.exists():
        return len(cleaned)
    try:
        manifest = HarvestManifest(db)
        snapshot = manifest.get_last_scope_snapshot(source)
    except Exception:  # noqa: BLE001
        return 0
    if snapshot is None:
        # First time harvesting this source — everything in scope is pending.
        return len(cleaned)
    snapshot_set = {s for s in snapshot if s}
    return len({s for s in cleaned} - snapshot_set)


# ─── /api/connections ───────────────────────────────────────────────

@router.get("/connections")
async def list_connections() -> list[dict[str, Any]]:
    refresh()  # pick up creds that were saved since server startup
    cfg = read_config()
    sources = cfg.get("sources", {}) or {}
    out: list[dict[str, Any]] = []
    for name, block in sources.items():
        if not is_enabled(name):
            # A connector this build doesn't ship (see src/sources.py). A
            # stale `sources.jira:` block left in someone's mnemify.yaml must
            # not put a card back in the UI.
            continue
        enabled = block.get("enabled", False)
        # Status derivation: "enabled + credentials present" → connected.
        creds_ok = True
        if name == "notion":
            creds_ok = has_secret(block.get("token_env", "NOTION_TOKEN"))
        elif name == "confluence":
            creds_ok = has_secret(
                block.get("email_env", "CONFLUENCE_EMAIL"),
            ) and has_secret(block.get("token_env", "CONFLUENCE_API_TOKEN"))
        elif name == "jira":
            creds_ok = has_secret(
                block.get("email_env", "JIRA_EMAIL"),
            ) and has_secret(block.get("token_env", "JIRA_API_TOKEN"))

        status = "connected" if (enabled and creds_ok) else "not_connected"

        summary_bits: list[str] = []
        if name == "confluence":
            spaces = block.get("space_keys", []) or []
            if spaces:
                summary_bits.append(f"{len(spaces)} space{'s' if len(spaces) != 1 else ''}")
            pages = block.get("page_ids", []) or []
            if pages:
                summary_bits.append(f"{len(pages)} page{'s' if len(pages) != 1 else ''}")
        if block.get("base_url"):
            host = str(block["base_url"]).replace("https://", "").replace("http://", "").split("/")[0]
            workspace = host
        else:
            workspace = None

        scope_key = _SCOPE_KEY.get(name, "scope")
        scope_list = list(block.get(scope_key, []) or [])
        if name == "confluence":
            # Page-subtree scope lives in a second key; the dialog prefill
            # and the pending-scope diff both need the full picture.
            scope_list += [str(p) for p in (block.get("page_ids") or [])]
        roots_out: list[dict[str, Any]] | None = None
        if name == "localfiles":
            from src.harvester.localfiles.models import LocalFilesConfig
            lf = LocalFilesConfig.from_yaml(block)
            # Flat ``<root>::<entry>`` ids — what Manage Scope edits and what
            # the pending-scope diff compares against the last snapshot.
            scope_list = lf.scope_ids()
            roots_out = [
                {
                    "path": r.key,
                    "name": Path(r.key).name or r.key,
                    "watch_folders": list(r.watch_folders),
                    "exists": Path(r.key).is_dir(),
                }
                for r in lf.roots
            ]
            n = len(roots_out)
            if n:
                summary_bits.append(f"{n} folder{'s' if n != 1 else ''}")
        out.append({
            "source": name,
            "status": status,
            "workspace_name": workspace,
            "last_harvest_at": _last_harvest_at(name),
            "doc_count": _doc_count(name),
            "scope_summary": " · ".join(summary_bits) if summary_bits else None,
            # Raw config the manage-scope dialog pre-fills from.
            "scope": scope_list,
            # How many configured scope ids haven't produced any harvested
            # docs yet. Drives the "scope changed — Harvest to pull them in"
            # nudge on the Connections card after Manage Scope edits.
            "pending_scope_count": _pending_scope_count(name, scope_list),
            # Local files only: the linked folders, for the card's list and
            # the Manage Scope root picker.
            **({"roots": roots_out} if roots_out is not None else {}),
        })
    return out


# Which yaml key holds the "what to harvest" list, per source.
_SCOPE_KEY = {
    "notion": "scope",
    "confluence": "space_keys",
    "obsidian": "watch_folders",
    "localfiles": "roots",  # flat ``<root>::<entry>`` ids in and out — see update_scope
    "jira": "project_keys",
}


class ScopeUpdate(BaseModel):
    scope: list[str] = []


# Confluence space keys are alphabetic / "~" personal-space; all-digit ids
# are page ids (valid scope since page-subtree support landed). Anything
# else (UUIDs, empty strings) is malformed and would break listing.
_CONFLUENCE_SPACE_KEY_RE = re.compile(r"^[~A-Za-z][A-Za-z0-9_-]*$")
_CONFLUENCE_PAGE_ID_RE = re.compile(r"^\d+$")


def _sanitize_scope(source: str, scope: list[str]) -> tuple[list[str], list[str]]:
    """Drop scope ids that don't match the source's id format.

    Returns ``(kept, rejected)``. Today we sanitize Confluence only —
    valid entries are space keys (whole-space harvest) or numeric page
    ids (page + descendant subtree harvest); anything else is rejected
    so the YAML stays clean even if the FE picker regresses.
    """
    if source == "confluence":
        kept: list[str] = []
        rejected: list[str] = []
        for s in scope:
            if isinstance(s, str) and (
                _CONFLUENCE_SPACE_KEY_RE.match(s) or _CONFLUENCE_PAGE_ID_RE.match(s)
            ):
                kept.append(s)
            else:
                rejected.append(s)
        return kept, rejected
    if source == "localfiles":
        # Flat ids must name a root; the picker's "N files here" rows are
        # virtual (`files:<folder>`) and mean nothing to the scanner.
        from src.harvester.localfiles.models import split_scope_id
        kept: list[str] = []
        rejected: list[str] = []
        for s in scope:
            parts = split_scope_id(s) if isinstance(s, str) else None
            if parts and not parts[1].startswith("files:"):
                kept.append(s)
            else:
                rejected.append(s)
        return kept, rejected
    return list(scope), []


def _drop_virtual_scope(scope: list[str]) -> list[str]:
    return [s for s in scope if isinstance(s, str) and s and not s.startswith("files:")]


def _localfiles_block(block: dict, roots: list) -> dict[str, Any]:
    """The ``sources.localfiles`` YAML block for ``roots`` (LocalRoot list),
    preserving unrelated keys and dropping the legacy single-root keys."""
    out: dict[str, Any] = {
        k: v for k, v in (block or {}).items()
        if k not in ("root_path", "watch_folders", "ignore_patterns", "roots", "enabled")
    }
    out["enabled"] = bool(roots)
    out.setdefault("concurrency", 10)
    out["roots"] = [
        {
            "path": r.path,
            **({"watch_folders": list(r.watch_folders)} if r.watch_folders else {}),
            **({"ignore_patterns": list(r.ignore_patterns)} if r.ignore_patterns else {}),
        }
        for r in roots
    ]
    return out


def _split_confluence_scope(scope: list[str]) -> tuple[list[str], list[str]]:
    """Split a mixed Confluence scope list into ``(space_keys, page_ids)``."""
    space_keys = [s for s in scope if not _CONFLUENCE_PAGE_ID_RE.match(str(s))]
    page_ids = [str(s) for s in scope if _CONFLUENCE_PAGE_ID_RE.match(str(s))]
    return space_keys, page_ids


@router.post("/connections/{source}/scope")
async def update_scope(source: str, body: ScopeUpdate):
    """Re-pick which pages/spaces/folders a connected source harvests, without
    re-entering credentials. Only the scope key changes — token_env / base_url
    / concurrency / enabled are all preserved."""
    key = _SCOPE_KEY.get(source)
    if key is None:
        raise HTTPException(400, f"unknown source {source!r}")
    block = read_config().get("sources", {}).get(source) or {}
    if not block:
        raise HTTPException(404, f"{source} is not configured")
    kept, rejected = _sanitize_scope(source, body.scope)
    new_block = dict(block)
    if source == "localfiles":
        # Rebuild the roots list from the flat ids: a root absent from the
        # list is unlinked, a root named only by ``<root>::`` is whole.
        from src.harvester.localfiles.models import LocalFilesConfig, roots_from_scope_ids
        existing = LocalFilesConfig.from_yaml(block).roots
        new_block = _localfiles_block(block, roots_from_scope_ids(kept, existing))
        upsert_source("localfiles", new_block)
        return {"ok": True, "scope": kept, "rejected": rejected}
    if source == "confluence":
        # Mixed scope: space keys harvest whole spaces, numeric page ids
        # harvest that page + its descendants. Persist them under separate
        # YAML keys so the plugin doesn't have to re-classify.
        space_keys, page_ids = _split_confluence_scope(kept)
        new_block["space_keys"] = space_keys
        new_block["page_ids"] = page_ids
    else:
        new_block[key] = kept
    upsert_source(source, new_block)
    return {"ok": True, "scope": kept, "rejected": rejected}


@router.post("/connections/{source}/recover-deleted")
async def recover_deleted_for_source(source: str):
    """Reactivate every doc marked ``deleted_at_source`` for this source.

    Use when an over-eager ``mark_deleted`` pass (pre-safety-guard, or a
    flaky API listing) nuked good documents. The raw files are still on
    disk; this just flips the manifest status back so the docs reappear
    in the UI. Re-harvesting on top is safe — ``upsert`` is idempotent
    and will update content if the source has new versions.
    """
    if source not in _SCOPE_KEY:
        raise HTTPException(400, f"unknown source {source!r}")
    m = HarvestManifest(paths.data_dir() / "harvest-manifest.db")
    restored = m.recover_deleted(source)
    return {"ok": True, "source": source, "restored": restored}


# ─── validate ───────────────────────────────────────────────────────

class NotionValidate(BaseModel):
    token: str


@router.post("/connections/notion/validate")
async def validate_notion(body: NotionValidate):
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(400, "token required")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.notion.com/v1/users/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28",
                },
            )
        if resp.status_code != 200:
            return {"ok": False, "reason": f"Notion responded {resp.status_code}"}
        payload = resp.json()
        name = (
            (payload.get("bot") or {}).get("workspace_name")
            or payload.get("name")
            or "Notion"
        )
        # Count integration-accessible pages/databases via a cheap search call.
        async with httpx.AsyncClient(timeout=10.0) as client:
            r2 = await client.post(
                "https://api.notion.com/v1/search",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"page_size": 1},
            )
        visible = 0
        if r2.status_code == 200:
            visible = len(r2.json().get("results", []))
    except _OUTBOUND_ERRORS as exc:
        logger.warning("notion validate failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": _outbound_reason(exc)}
    return {"ok": True, "workspace_name": name, "visible_count": visible}


class ConfluenceValidate(BaseModel):
    base_url: str
    email: str
    token: str


def _confluence_auth_reason(status: int, base_url: str) -> str:
    """Turn an Atlassian status code into something the user can act on.

    A bare "Atlassian responded 403" sends people hunting for a bad token,
    which is precisely what a 403 rules out: Basic auth was accepted and the
    *authorization* failed. The three codes below are the ones that actually
    show up in the wizard, and they mean very different things.
    """
    if status == 401:
        return (
            "Atlassian rejected the email or token (401). The email must be the "
            "account that created the token, and the token must not have been revoked."
        )
    if status == 403:
        return (
            "Signed in, but this account can't read Confluence on that site (403). "
            "Either the account has no Confluence access there, or the API token is "
            "scoped to other Atlassian products (a Jira-only token does this). "
            f"Check you can open {base_url}/spaces in a browser while signed in as "
            "this account, and create the token without product restrictions."
        )
    if status == 404:
        return (
            f"No Confluence REST API at {base_url} (404). Cloud sites need the "
            "/wiki suffix — e.g. https://yourco.atlassian.net/wiki."
        )
    if status == 429:
        return "Atlassian is rate-limiting this site (429). Wait a minute and retry."
    return f"Atlassian responded {status}."


@router.post("/connections/confluence/validate")
async def validate_confluence(body: ConfluenceValidate):
    base_url = (body.base_url or "").strip().rstrip("/")
    email = (body.email or "").strip()
    token = (body.token or "").strip()
    if not (base_url and email and token):
        raise HTTPException(400, "base_url, email, token all required")

    try:
        async with httpx.AsyncClient(timeout=10.0, auth=(email, token)) as client:
            r = await client.get(f"{base_url}/rest/api/space?limit=1")
        if r.status_code != 200:
            logger.warning(
                "confluence validate: %s returned %s", base_url, r.status_code
            )
            return {"ok": False, "reason": _confluence_auth_reason(r.status_code, base_url)}
        size = r.json().get("size", 0)
    except _OUTBOUND_ERRORS as exc:
        logger.warning("confluence validate failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": _outbound_reason(exc)}
    host = base_url.replace("https://", "").replace("http://", "").split("/")[0]
    return {"ok": True, "workspace_name": host, "visible_count": size}


# ─── discover ──────────────────────────────────────────────────────

class NotionDiscover(BaseModel):
    token: str | None = None


@router.post("/connections/notion/discover")
async def discover_notion(body: NotionDiscover | None = None):
    # Prefer the token the caller just pasted (and validated) over whatever
    # is in .env. Fixes the "stuck at 0 pages" bug where a freshly-pasted
    # token would pass validate but discover would silently fall back to the
    # stale server-startup env var.
    token = (body.token or "").strip() if body else ""
    if not token:
        # Reload .env in case the user just saved (older servers may have
        # cached os.environ from startup).
        refresh()
        cfg = load_config_file()
        src = cfg.get("sources", {}).get("notion", {})
        token_env = src.get("token_env", "NOTION_TOKEN")
        token = os.environ.get(token_env, "").strip()
    if not token:
        return {"items": []}

    # Page through Notion's /search until the integration has no more
    # accessible objects. Notion caps a single call at 100 results.
    results: list[dict] = []
    cursor: str | None = None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for _ in range(10):  # hard cap — up to 1000 items
                payload: dict = {"page_size": 100}
                if cursor:
                    payload["start_cursor"] = cursor
                r = await client.post(
                    "https://api.notion.com/v1/search",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if r.status_code != 200:
                    return {"items": [], "error": f"Notion responded {r.status_code}"}
                data = r.json()
                results.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
    except _OUTBOUND_ERRORS as exc:
        logger.warning("notion discover failed: %s", exc, exc_info=True)
        return {"items": [], "error": _outbound_reason(exc)}

    # Frontend now renders these as an expandable tree, so we return every
    # accessible object with its parent_id intact. Items whose parent isn't
    # also in the result set are presented as top-level by the tree builder.
    ids = {o.get("id") for o in results if o.get("id")}

    def _parent_id_of(o: dict) -> str | None:
        parent = o.get("parent", {}) or {}
        ptype = parent.get("type")
        if ptype in ("workspace", None):
            return None
        parent_id = (
            parent.get("page_id")
            or parent.get("database_id")
            or parent.get("block_id")
        )
        # Treat as top-level if the parent isn't in the returned set
        # (e.g. user shared a mid-tree page but not its parent).
        if parent_id not in ids:
            return None
        return parent_id

    def _title_of(o: dict) -> str:
        if o.get("object") == "database":
            arr = o.get("title") or []
            return "".join(p.get("plain_text", "") for p in arr) or "Untitled database"
        props = o.get("properties", {}) or {}
        for v in props.values():
            if v.get("type") == "title" and v.get("title"):
                return "".join(p.get("plain_text", "") for p in v["title"])
        return "Untitled page"

    items: list[dict] = [
        {
            "id": o.get("id"),
            "title": _title_of(o),
            "kind": "database" if o.get("object") == "database" else "page",
            "parent_id": _parent_id_of(o),
            "count": 0,
        }
        for o in results
    ]

    # Sort: databases first, then pages — within each, by title. The tree
    # builder respects this order when emitting siblings.
    items.sort(key=lambda x: (0 if x["kind"] == "database" else 1, x["title"].lower()))
    return {"items": items, "total_accessible": len(results)}


class ConfluenceDiscover(BaseModel):
    base_url: str | None = None
    email: str | None = None
    token: str | None = None


@router.post("/connections/confluence/discover")
async def discover_confluence(body: ConfluenceDiscover | None = None):
    base = (body.base_url or "").strip().rstrip("/") if body else ""
    email = (body.email or "").strip() if body else ""
    token = (body.token or "").strip() if body else ""
    if base or email or token:
        # The wizard path: the caller supplies the whole triple it just
        # validated. Never mix a caller-chosen ``base_url`` with the *saved*
        # email/token — that would send the user's stored credentials, as
        # HTTP Basic auth, to whatever host the request named.
        if not (base and email and token):
            raise HTTPException(400, "base_url, email and token must be given together")
    else:
        # The re-scan path: everything from the saved connection.
        refresh()
        cfg = load_config_file()
        src = cfg.get("sources", {}).get("confluence", {})
        base = (src.get("base_url") or "").rstrip("/")
        email = os.environ.get(src.get("email_env", "CONFLUENCE_EMAIL"), "").strip()
        token = os.environ.get(src.get("token_env", "CONFLUENCE_API_TOKEN"), "").strip()
    if not (base and email and token):
        return {"items": []}

    spaces: list[dict] = []
    start = 0
    page_size = 250  # Atlassian caps per-page at 250; loop for the rest.
    hard_cap = 5000  # safety valve
    try:
        async with httpx.AsyncClient(timeout=25.0, auth=(email, token)) as client:
            # 1) Fetch every global (team/org) space. Personal spaces (key
            #    prefix `~`, one per user) are intentionally excluded from
            #    this call — fetching them would surface every teammate's
            #    personal space and clutter the picker. We pull just *the
            #    current user's* personal space below.
            while len(spaces) < hard_cap:
                r = await client.get(
                    f"{base}/rest/api/space",
                    params={"start": start, "limit": page_size, "type": "global"},
                )
                if r.status_code != 200:
                    if spaces:
                        break  # return what we got so far
                    return {
                        "items": [],
                        "error": f"Atlassian responded {r.status_code}",
                    }
                body = r.json()
                results = body.get("results", []) or []
                spaces.extend(results)
                # Atlassian uses either `size` < `limit` or `_links.next` absence.
                returned = len(results)
                if returned < page_size:
                    break
                start += returned

            # 2) Best-effort: look up the authenticated user and append
            #    *their* personal space (~accountId) if it exists. Failure
            #    here is non-fatal — globals are the primary picker.
            try:
                user_r = await client.get(f"{base}/rest/api/user/current")
                if user_r.status_code == 200:
                    account_id = (user_r.json() or {}).get("accountId")
                    if account_id:
                        personal_key = f"~{account_id}"
                        space_r = await client.get(
                            f"{base}/rest/api/space/{personal_key}"
                        )
                        if space_r.status_code == 200:
                            personal = space_r.json()
                            if personal and personal.get("key"):
                                spaces.append(personal)
            except _OUTBOUND_ERRORS:
                logger.debug(
                    "confluence discover: skipped personal-space lookup",
                    exc_info=True,
                )
    except _OUTBOUND_ERRORS as exc:
        logger.warning("confluence discover failed: %s", exc, exc_info=True)
        if not spaces:
            return {"items": [], "error": _outbound_reason(exc)}

    # Sort: globals first (alphabetical), the user's personal space last so
    # it sits visually distinct at the end of the picker.
    def _sort_key(s: dict) -> tuple:
        is_personal = (s.get("type") == "personal") or (
            (s.get("key") or "").startswith("~")
        )
        name = (s.get("name") or s.get("key") or "").lower()
        return (1 if is_personal else 0, name)

    spaces.sort(key=_sort_key)

    # Per-space page fetch — pull up to PAGE_LIMIT pages per space so the
    # tree picker can show sub-pages, not just top-level spaces. Each page
    # carries an ``ancestors`` array; the immediate parent is the last
    # ancestor (or the space key itself for top-level pages). Failures here
    # are non-fatal: if a particular space's page fetch fails, we keep the
    # space itself and skip its pages.
    PAGES_PER_SPACE = 200
    pages: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=25.0, auth=(email, token)) as client:
            for sp in spaces:
                space_key = sp.get("key")
                if not space_key:
                    continue
                try:
                    page_r = await client.get(
                        f"{base}/rest/api/content",
                        params={
                            "spaceKey": space_key,
                            "type": "page",
                            "limit": PAGES_PER_SPACE,
                            "expand": "ancestors",
                            "status": "current",
                        },
                    )
                    if page_r.status_code != 200:
                        continue
                    for p in (page_r.json() or {}).get("results", []) or []:
                        ancestors = p.get("ancestors") or []
                        parent_id = (
                            ancestors[-1].get("id")
                            if ancestors
                            else space_key
                        )
                        pages.append({
                            "id": p.get("id"),
                            "title": p.get("title") or "Untitled page",
                            "kind": "page",
                            "parent_id": parent_id,
                            "space_key": space_key,
                            "count": 0,
                        })
                except _OUTBOUND_ERRORS:
                    logger.debug(
                        "confluence discover: pages fetch failed for space %s",
                        space_key, exc_info=True,
                    )
                    continue
    except _OUTBOUND_ERRORS:
        logger.warning("confluence discover: page fetch loop failed", exc_info=True)

    space_items = [
        {
            "id": s.get("key"),
            "title": s.get("name") or s.get("key"),
            "kind": "personal_space"
            if (s.get("type") == "personal" or (s.get("key") or "").startswith("~"))
            else "space",
            "parent_id": None,
            "count": 0,
        }
        for s in spaces
    ]

    return {
        "items": space_items + pages,
        "total_accessible": len(spaces) + len(pages),
    }


# ─── save / delete ─────────────────────────────────────────────────

class NotionSave(BaseModel):
    token: str
    scope: list[str] = []


@router.post("/connections/notion/save")
async def save_notion(body: NotionSave):
    save_secret("NOTION_TOKEN", body.token.strip())
    os.environ["NOTION_TOKEN"] = body.token.strip()
    block = read_config().get("sources", {}).get("notion", {}) or {}
    block = {
        "enabled": True,
        "token_env": "NOTION_TOKEN",
        "concurrency": block.get("concurrency", 5),
    }
    if body.scope:
        block["scope"] = body.scope
    upsert_source("notion", block)
    return {"ok": True}


class ConfluenceSave(BaseModel):
    base_url: str
    email: str
    token: str
    scope: list[str] = []


@router.post("/connections/confluence/save")
async def save_confluence(body: ConfluenceSave):
    write_secrets({
        "CONFLUENCE_EMAIL": body.email.strip(),
        "CONFLUENCE_API_TOKEN": body.token.strip(),
    })
    os.environ["CONFLUENCE_EMAIL"] = body.email.strip()
    os.environ["CONFLUENCE_API_TOKEN"] = body.token.strip()
    block = read_config().get("sources", {}).get("confluence", {}) or {}
    if body.scope:
        kept, _rejected = _sanitize_scope("confluence", body.scope)
        space_keys, page_ids = _split_confluence_scope(kept)
    else:
        space_keys = block.get("space_keys", []) or []
        page_ids = block.get("page_ids", []) or []
    block = {
        "enabled": True,
        "base_url": body.base_url.strip().rstrip("/"),
        "email_env": "CONFLUENCE_EMAIL",
        "token_env": "CONFLUENCE_API_TOKEN",
        "space_keys": space_keys,
        "page_ids": page_ids,
        "concurrency": block.get("concurrency", 3),
    }
    upsert_source("confluence", block)
    return {"ok": True}


# ─── obsidian ──────────────────────────────────────────────────────


class ObsidianValidate(BaseModel):
    vault_path: str


@router.post("/connections/obsidian/validate")
async def validate_obsidian(body: ObsidianValidate):
    """Verify a path points to a real Obsidian vault.

    Wraps ``ObsidianHarvesterPlugin.test_connection`` so the frontend can
    show a sage banner before saving (no `.env` writes happen until save).
    """
    from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin
    from src.harvester.obsidian.models import ObsidianVaultConfig

    vault_path = (body.vault_path or "").strip()
    if not vault_path:
        return {
            "ok": False,
            "reason": "vault_path required",
            "file_count": 0,
            "has_obsidian_dir": False,
        }

    try:
        cfg = ObsidianVaultConfig(vault_path=vault_path)
        plugin = ObsidianHarvesterPlugin(cfg)
        status = await plugin.test_connection()
        if status.healthy:
            details = status.details or {}
            return {
                "ok": True,
                "file_count": int(details.get("note_count", 0)),
                "has_obsidian_dir": True,
            }
        return {
            "ok": False,
            "reason": status.message,
            "file_count": 0,
            "has_obsidian_dir": False,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "reason": str(e),
            "file_count": 0,
            "has_obsidian_dir": False,
        }


class ObsidianDiscover(BaseModel):
    vault_path: str | None = None


def _walk_subfolders(raw: str) -> dict[str, Any]:
    """Every subfolder under ``raw`` as a tree-shaped item list for the
    frontend's tree picker (``parent_id`` = parent's relative path, ``None``
    at the top level). Hidden folders are skipped. Capped at 4000 entries,
    breadth-first, so a huge tree clips deep layers rather than breadth.
    Shared by the Obsidian and local-folder discover routes."""
    try:
        root = Path(os.path.expanduser(raw)).resolve()
    except Exception as e:  # noqa: BLE001
        return {"items": [], "error": f"Invalid path: {e}"}

    if not root.is_dir():
        return {"items": [], "error": "path is not a directory"}

    HARD_CAP = 4000
    items: list[dict[str, Any]] = []
    queue: list[Path] = [root]
    while queue and len(items) < HARD_CAP:
        current = queue.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda x: x.name.lower())
        except (PermissionError, OSError):
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            try:
                rel = child.relative_to(root).as_posix()
            except ValueError:
                continue
            parent_rel = (
                None
                if current == root
                else current.relative_to(root).as_posix()
            )
            items.append({
                "id": rel,
                "title": child.name,
                "kind": "folder",
                "parent_id": parent_rel,
                "count": 0,
            })
            if len(items) >= HARD_CAP:
                break
            queue.append(child)

    return {"items": items, "total_accessible": len(items)}


@router.post("/connections/obsidian/discover")
async def discover_obsidian(body: ObsidianDiscover | None = None):
    """Walk an Obsidian vault and return its subfolders as a tree — see
    ``_walk_subfolders``. With no ``vault_path`` in the body, uses the saved
    one (Manage Scope on an already-connected vault)."""
    raw = (body.vault_path or "").strip() if body else ""
    if not raw:
        cfg = load_config_file()
        raw = (cfg.get("sources", {}).get("obsidian", {}) or {}).get("vault_path", "")
    if not raw:
        return {"items": [], "error": "no vault path saved"}
    out = _walk_subfolders(raw)
    if out.get("error") == "path is not a directory":
        out["error"] = "vault path is not a directory"
    return out


class ObsidianSave(BaseModel):
    vault_path: str
    scope: list[str] = []  # watch_folders


@router.post("/connections/obsidian/save")
async def save_obsidian(body: ObsidianSave):
    """Persist Obsidian vault config to mnemify.yaml.

    Obsidian has no credentials to write to .env — the vault path itself
    lives in YAML. Existing block fields (concurrency, ignore_patterns) are
    preserved.
    """
    block = read_config().get("sources", {}).get("obsidian", {}) or {}
    new_block: dict[str, Any] = {
        "enabled": True,
        "vault_path": body.vault_path.strip(),
        "concurrency": block.get("concurrency", 10),
    }
    if body.scope:
        new_block["watch_folders"] = body.scope
    elif "watch_folders" in block:
        new_block["watch_folders"] = block["watch_folders"]
    if "ignore_patterns" in block:
        new_block["ignore_patterns"] = block["ignore_patterns"]
    upsert_source("obsidian", new_block)
    return {"ok": True}


# ─── local files (any folder of .md / .txt / .pdf) ─────────────────


class LocalFilesValidate(BaseModel):
    root_path: str


@router.post("/connections/localfiles/validate")
async def validate_localfiles(body: LocalFilesValidate):
    """Check a folder exists and count the files Mnemify can read in it.

    Returns ``by_format`` (``{"md": 12, "txt": 3, "pdf": 5}``) so the wizard
    can tell the user what it found before they commit."""
    from src.harvester.localfiles.models import LocalFilesConfig
    from src.harvester.localfiles.plugin import LocalFilesHarvesterPlugin

    root_path = (body.root_path or "").strip()
    if not root_path:
        return {"ok": False, "reason": "root_path required", "file_count": 0, "by_format": {}}
    try:
        plugin = LocalFilesHarvesterPlugin(LocalFilesConfig(root_path=root_path))
        status = await plugin.test_connection()
        if status.healthy:
            details = status.details or {}
            return {
                "ok": True,
                "file_count": int(details.get("file_count", 0)),
                "by_format": details.get("by_format", {}),
                "root_path": details.get("root_path", root_path),
            }
        return {"ok": False, "reason": status.message, "file_count": 0, "by_format": {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e), "file_count": 0, "by_format": {}}


class LocalFilesDiscover(BaseModel):
    root_path: str | None = None


def _walk_supported_tree(raw: str) -> dict[str, Any]:
    """Folders AND the supported files inside them, as one tree for the
    scope picker — so the user can see *what* Mnemify would read and pick
    single files as well as folders. Folder items carry a ``subtitle`` with
    their recursive counts per format. A folder's files sit under one
    collapsible ``kind="filegroup"`` row (``id="files:<folder>"``, virtual —
    never saved) as ``kind="file"`` items whose id is ``file:<relpath>``,
    which is exactly what the scanner accepts in ``watch_folders``. Hidden
    folders and the scanner's default ignores are skipped. Capped at 4000
    entries, breadth-first."""
    from src.harvester.localfiles.scanner import DEFAULT_IGNORE, FILE_SCOPE_PREFIX, format_for

    try:
        root = Path(os.path.expanduser(raw)).resolve()
    except Exception as e:  # noqa: BLE001
        return {"items": [], "error": f"Invalid path: {e}"}
    if not root.is_dir():
        return {"items": [], "error": "path is not a directory"}

    ignored_dirs = {p[:-2] for p in DEFAULT_IGNORE if p.endswith("/*")}

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    # Pass 1: recursive per-folder counts by format (so a parent folder
    # summarises everything beneath it).
    counts: dict[str, dict[str, int]] = {}
    total_files = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and rel(Path(dirpath) / d) not in ignored_dirs
        )
        for name in filenames:
            if name.startswith("."):
                continue
            fmt = format_for(Path(name))
            if fmt is None:
                continue
            total_files += 1
            cur = Path(dirpath)
            while True:
                key = "" if cur == root else rel(cur)
                bucket = counts.setdefault(key, {})
                bucket[fmt] = bucket.get(fmt, 0) + 1
                if cur == root:
                    break
                cur = cur.parent

    def summary(key: str) -> str:
        c = counts.get(key, {})
        if not c:
            return "no supported files"
        parts = [f"{n} {fmt}" for fmt, n in sorted(c.items(), key=lambda kv: -kv[1])]
        return " · ".join(parts)

    HARD_CAP = 4000
    items: list[dict[str, Any]] = []
    queue: list[Path] = [root]
    while queue and len(items) < HARD_CAP:
        current = queue.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except (PermissionError, OSError):
            continue
        parent_rel = None if current == root else rel(current)
        file_items: list[dict[str, Any]] = []
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir():
                r = rel(child)
                if r in ignored_dirs:
                    continue
                items.append({
                    "id": r,
                    "title": child.name,
                    "kind": "folder",
                    "subtitle": summary(r),
                    "parent_id": parent_rel,
                    "count": sum(counts.get(r, {}).values()),
                })
                queue.append(child)
            elif child.is_file() and not child.is_symlink():
                fmt = format_for(child)
                if fmt is None:
                    continue
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                file_items.append({
                    "id": f"{FILE_SCOPE_PREFIX}{rel(child)}",
                    "title": child.name,
                    "kind": "file",
                    "subtitle": f"{fmt} · {_human_size(size)}",
                    "parent_id": None,  # filled below with the group id
                    "count": 0,
                })
            if len(items) >= HARD_CAP:
                break
        if file_items and len(items) < HARD_CAP:
            group_id = f"files:{parent_rel or ''}"
            n = len(file_items)
            items.append({
                "id": group_id,
                "title": f"{n} file{'s' if n != 1 else ''} here",
                "kind": "filegroup",
                "subtitle": "pick single files, or the whole folder above",
                "parent_id": parent_rel,
                "count": n,
            })
            for fi in file_items:
                fi["parent_id"] = group_id
            items.extend(file_items[: max(0, HARD_CAP - len(items))])

    return {
        "items": items,
        "total_accessible": len(items),
        "file_count": total_files,
        "by_format": counts.get("", {}),
    }


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@router.post("/connections/localfiles/discover")
async def discover_localfiles(body: LocalFilesDiscover | None = None):
    """Sub-folders plus the supported files in each, for the scope picker.
    With no ``root_path`` in the body, uses the saved one."""
    raw = (body.root_path or "").strip() if body else ""
    if not raw:
        from src.harvester.localfiles.models import LocalFilesConfig
        cfg = load_config_file()
        roots = LocalFilesConfig.from_yaml(cfg.get("sources", {}).get("localfiles", {}) or {}).roots
        raw = roots[0].key if roots else ""
    if not raw:
        return {"items": [], "error": "no folder linked yet"}
    return _walk_supported_tree(raw)


class LocalFilesSave(BaseModel):
    root_path: str
    scope: list[str] = []  # root-relative folders and ``file:<relpath>`` entries


@router.post("/connections/localfiles/save")
async def save_localfiles(body: LocalFilesSave):
    """Link a folder (or re-scope one already linked). Other linked folders
    are untouched — the local-files source is a *list* of roots. No secrets
    involved; the paths are the whole configuration."""
    from src.harvester.localfiles.models import LocalFilesConfig, LocalRoot, root_key

    block = read_config().get("sources", {}).get("localfiles", {}) or {}
    roots = LocalFilesConfig.from_yaml(block).roots
    key = root_key(body.root_path.strip())
    scope = _drop_virtual_scope(body.scope)
    replaced = False
    for i, r in enumerate(roots):
        if r.key == key:
            roots[i] = LocalRoot(path=key, watch_folders=scope, ignore_patterns=r.ignore_patterns)
            replaced = True
            break
    if not replaced:
        roots.append(LocalRoot(path=key, watch_folders=scope))
    upsert_source("localfiles", _localfiles_block(block, roots))
    return {"ok": True, "root_path": key, "root_count": len(roots)}


class LocalFilesRemoveRoot(BaseModel):
    root_path: str


@router.post("/connections/localfiles/remove-root")
async def remove_localfiles_root(body: LocalFilesRemoveRoot):
    """Unlink one folder. Its documents fall out of scope on the next
    harvest (scope-aware deletion); the folder itself is never touched.
    Removing the last root disables the source, same as Remove on the card."""
    from src.harvester.localfiles.models import LocalFilesConfig, root_key

    block = read_config().get("sources", {}).get("localfiles", {}) or {}
    roots = LocalFilesConfig.from_yaml(block).roots
    key = root_key(body.root_path.strip())
    remaining = [r for r in roots if r.key != key]
    if len(remaining) == len(roots):
        raise HTTPException(404, "that folder is not linked")
    upsert_source("localfiles", _localfiles_block(block, remaining))
    return {"ok": True, "root_count": len(remaining)}


class BrowseDir(BaseModel):
    path: str | None = None  # absolute path, with optional ~ expansion. Defaults to $HOME.


@router.post("/connections/browse-dir")
async def browse_dir(body: BrowseDir):
    """List subdirectories of a path so the FE can render a folder picker.

    Marks any directory containing a ``.obsidian/`` sub-folder as a vault so
    the picker can highlight valid Obsidian targets.
    """
    raw = (body.path or "~").strip() or "~"
    try:
        p = Path(os.path.expanduser(raw)).resolve()
    except Exception as e:  # noqa: BLE001
        return {
            "path": raw,
            "parent": None,
            "entries": [],
            "error": f"Invalid path: {e}",
        }

    if not p.exists():
        return {
            "path": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "entries": [],
            "error": f"Path not found: {p}",
        }
    if not p.is_dir():
        return {
            "path": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "entries": [],
            "error": f"Not a directory: {p}",
        }

    try:
        children = sorted(p.iterdir(), key=lambda x: x.name.lower())
    except PermissionError:
        return {
            "path": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "entries": [],
            "error": f"Permission denied: {p}",
        }

    from src.harvester.localfiles.scanner import format_for

    def _supported_here(d: Path) -> int:
        """Supported files DIRECTLY in ``d`` (non-recursive — cheap enough
        to run for every row of the folder picker)."""
        try:
            return sum(
                1
                for f in d.iterdir()
                if f.is_file() and not f.name.startswith(".") and format_for(f) is not None
            )
        except (PermissionError, OSError):
            return 0

    def _files_here(d: Path, cap: int = 300) -> list[dict[str, Any]]:
        """Supported files DIRECTLY in ``d`` for the picker to display, so the
        user can see what a folder holds before choosing it."""
        out: list[dict[str, Any]] = []
        try:
            kids = sorted(d.iterdir(), key=lambda x: x.name.lower())
        except (PermissionError, OSError):
            return out
        for f in kids:
            if len(out) >= cap:
                break
            if not f.is_file() or f.name.startswith("."):
                continue
            fmt = format_for(f)
            if fmt is None:
                continue
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            out.append({"name": f.name, "format": fmt, "size": _human_size(size)})
        return out

    is_self_vault = (p / ".obsidian").is_dir()
    entries: list[dict[str, Any]] = []
    for child in children:
        name = child.name
        # Hide hidden folders except .obsidian (which we surface as a badge,
        # not as a navigable entry — drop it here too).
        if name.startswith("."):
            continue
        try:
            if not child.is_dir():
                continue
            try:
                is_vault = (child / ".obsidian").is_dir()
            except (PermissionError, OSError):
                is_vault = False
            entries.append({
                "name": name,
                "is_vault": is_vault,
                "file_count": _supported_here(child),
            })
        except (PermissionError, OSError):
            continue

    return {
        "path": str(p),
        "parent": str(p.parent) if p.parent != p else None,
        "entries": entries,
        "is_self_vault": is_self_vault,
        "file_count": _supported_here(p),
        "files": _files_here(p),
    }


@router.delete("/connections/{source}")
async def disconnect(source: str):
    disable_source(source)
    if source == "notion":
        delete_secrets(["NOTION_TOKEN"])
    elif source == "confluence":
        delete_secrets(["CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"])
    elif source == "jira":
        delete_secrets(["JIRA_EMAIL", "JIRA_API_TOKEN"])
    return {"ok": True}
