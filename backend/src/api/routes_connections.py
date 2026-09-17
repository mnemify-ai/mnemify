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
        })
    return out


# Which yaml key holds the "what to harvest" list, per source.
_SCOPE_KEY = {
    "notion": "scope",
    "confluence": "space_keys",
    "obsidian": "watch_folders",
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
    return list(scope), []


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
    if not (base and email and token):
        refresh()
        cfg = load_config_file()
        src = cfg.get("sources", {}).get("confluence", {})
        base = base or (src.get("base_url") or "").rstrip("/")
        email = email or os.environ.get(src.get("email_env", "CONFLUENCE_EMAIL"), "").strip()
        token = token or os.environ.get(src.get("token_env", "CONFLUENCE_API_TOKEN"), "").strip()
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


@router.post("/connections/obsidian/discover")
async def discover_obsidian(body: ObsidianDiscover | None = None):
    """Walk an Obsidian vault and return every subfolder as a tree-shaped
    list of items, so the frontend's tree picker can show a hierarchical
    folder selector.

    Returns items with ``parent_id`` set to the parent folder's relative
    path (or ``None`` for top-level folders). Hidden folders (``.obsidian``,
    ``.git``, etc.) are skipped. Capped at 4000 entries to keep responses
    bounded for huge vaults.
    """
    raw = (body.vault_path or "").strip() if body else ""
    if not raw:
        cfg = load_config_file()
        raw = (cfg.get("sources", {}).get("obsidian", {}) or {}).get("vault_path", "")
    if not raw:
        return {"items": [], "error": "no vault path saved"}

    try:
        root = Path(os.path.expanduser(raw)).resolve()
    except Exception as e:  # noqa: BLE001
        return {"items": [], "error": f"Invalid vault path: {e}"}

    if not root.is_dir():
        return {"items": [], "error": "vault path is not a directory"}

    HARD_CAP = 4000
    items: list[dict[str, Any]] = []
    # Walk breadth-first so the cap clips deeper layers, not breadth.
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
            entries.append({"name": name, "is_vault": is_vault})
        except (PermissionError, OSError):
            continue

    return {
        "path": str(p),
        "parent": str(p.parent) if p.parent != p else None,
        "entries": entries,
        "is_self_vault": is_self_vault,
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
