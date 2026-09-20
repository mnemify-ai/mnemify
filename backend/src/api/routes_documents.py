"""/api/documents/* — list, detail, content, tree, stats, graph."""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.harvester.manifest import HarvestManifest


router = APIRouter()
from src import paths  # data dir resolved at call time — see src/paths.py


def _attachments_dir(row: dict) -> Path | None:
    """Resolve a doc row's attachments directory on disk.

    Layout (see ``RawStore.write_attachment``):
        {data_dir}/raw/{source}/{source_id[:2]}/{source_id}/attachments/
    """
    raw = row.get("raw_path")
    if not raw:
        return None
    raw_p = Path(raw)
    # The raw file lives at .../{source_id}.{ext}; attachments sit alongside
    # it in a sibling sub-directory named after the source_id (no extension).
    candidate = raw_p.with_suffix("") / "attachments"
    if candidate.is_dir():
        return candidate
    # Fallback: if raw_path is .../{shard}/{source_id}.json then the
    # attachments dir is .../{shard}/{source_id}/attachments
    alt = raw_p.parent / raw_p.stem / "attachments"
    if alt.is_dir():
        return alt
    return None


def _manifest() -> HarvestManifest | None:
    db = paths.data_dir() / "harvest-manifest.db"
    if not db.exists():
        return None
    return HarvestManifest(db)


def _parse_metadata(r: dict) -> dict:
    md = r.get("metadata") or {}
    if isinstance(md, str):
        try:
            return json.loads(md)
        except Exception:  # noqa: BLE001
            return {}
    return md if isinstance(md, dict) else {}


def _compute_path(
    r: dict,
    *,
    by_source_id: dict | None = None,
    manifest: HarvestManifest | None = None,
) -> tuple[list[str], list[str]]:
    """Compute the ancestor breadcrumb for a document, root-first, EXCLUDING
    the document itself.

    Strategy per source:
      • Obsidian — split ``metadata.folder`` (already vault-relative).
      • Confluence — start with the space name/key, then walk
        ``metadata.ancestors`` (already root-first per the Confluence API).
      • Notion — walk ``parent_id`` chain. Uses ``by_source_id`` when
        provided (one O(1) dict instead of N manifest queries), otherwise
        falls back to manifest lookups for the single-doc endpoint.

    Returns parallel ``(titles, ids)`` lists. An empty ``id`` means the
    ancestor isn't itself a harvested document we can link to.
    """
    src = r.get("source_type")
    md = _parse_metadata(r)

    if src == "obsidian":
        folder = md.get("folder") or ""
        titles = [seg for seg in folder.split("/") if seg]
        return titles, ["" for _ in titles]

    if src == "confluence":
        titles: list[str] = []
        ids: list[str] = []
        space = md.get("space_key") or md.get("space")
        if space:
            titles.append(space)
            ids.append("")
        for a in md.get("ancestors") or []:
            if isinstance(a, dict):
                titles.append(a.get("title") or "Untitled")
                aid = str(a.get("id") or "")
                hit = by_source_id.get(aid) if by_source_id else None
                ids.append(hit.get("id") if hit else "")
        return titles, ids

    if src == "notion":
        chain: list[tuple[str, str]] = []
        # Linkable parent types we know how to look up in the manifest.
        # ``data_source_id`` was added by Notion API ≥ 2025-09-03 — pages
        # inside a database now point at the data_source (which we harvest
        # as ``document_type="database"``) rather than the database id
        # directly. Without it here, the walker stops immediately on every
        # database row and the breadcrumb stays empty.
        linkable = ("page_id", "database_id", "data_source_id")

        def _next_step(meta: dict) -> tuple[str, str]:
            """Pick the next (parent_type, parent_id) for the walker.

            When a doc's natural parent is a database container that the
            Notion API never returns from /search, the harvester stashes
            the container's own parent on metadata as ``container``. Prefer
            the container's parent over the literal one so the breadcrumb
            bridges past the un-harvested wrapper to reach the real
            ancestor page (e.g. the page that *contains* the database).
            """
            ptype = meta.get("parent_type") or ""
            pid = meta.get("parent_id") or ""
            container = meta.get("container")
            if (
                isinstance(container, dict)
                and ptype == "database_id"
                and container.get("parent_type")
            ):
                return (
                    container.get("parent_type") or "",
                    str(container.get("parent_id") or ""),
                )
            return ptype, str(pid)

        cur_ptype, cur_pid = _next_step(md)
        seen = {r.get("source_id")}
        # Cap the walk so a malformed parent_id loop can't run unboundedly.
        for _ in range(20):
            if not cur_pid or cur_ptype not in linkable:
                break
            if cur_pid in seen:
                break
            seen.add(cur_pid)
            parent = None
            if by_source_id and cur_pid in by_source_id:
                parent = by_source_id[cur_pid]
            elif manifest is not None:
                parent = manifest.lookup(src, cur_pid)
            if not parent:
                # Best-effort: surface the immediate parent_title as a hint
                # the first time we miss the lookup, then stop.
                if not chain and md.get("parent_title"):
                    chain.append((md.get("parent_title") or "Untitled", ""))
                break
            pmd = _parse_metadata(parent)
            chain.append((parent.get("title") or "Untitled", parent.get("id") or ""))
            cur_ptype, cur_pid = _next_step(pmd)
        # Reverse so root is first.
        titles = [t for t, _ in reversed(chain)]
        ids = [i for _, i in reversed(chain)]
        # Seed "Workspace" only when the chain is otherwise empty (top-level
        # page rooted at the workspace, or a chain that couldn't resolve any
        # ancestor at all). When real ancestors exist they carry more
        # information than the generic "Workspace" label and are sufficient
        # on their own.
        if not titles:
            titles.insert(0, "Workspace")
            ids.insert(0, "")
        return titles, ids

    return [], []


def _row_to_doc(
    r: dict,
    *,
    by_source_id: dict | None = None,
    manifest: HarvestManifest | None = None,
) -> dict:
    metadata = _parse_metadata(r)
    properties = metadata.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    path_titles, path_ids = _compute_path(
        r, by_source_id=by_source_id, manifest=manifest
    )
    return {
        "id": r.get("id"),
        "source": r.get("source_type"),
        "source_id": r.get("source_id"),
        "title": r.get("title") or "Untitled",
        "space": metadata.get("space_key")
        or metadata.get("space")
        or metadata.get("parent_title")
        or "—",
        "type": metadata.get("document_type") or "page",
        "size_bytes": (_read_size(r.get("raw_path")) or 0),
        "updated_at": r.get("source_modified"),
        "harvested_at": r.get("harvested_at"),
        "author": metadata.get("author_name") or metadata.get("created_by"),
        "last_modified_by": metadata.get("last_modified_by"),
        "excerpt": metadata.get("excerpt") or "",
        "raw_path": r.get("raw_path"),
        "path_titles": path_titles,
        "path_ids": path_ids,
        # Structured source-side properties (Notion database-row fields, Jira
        # custom fields, etc.). Empty {} for documents that have none.
        "properties": properties,
    }


def _read_size(raw_path: str | None) -> int | None:
    if not raw_path:
        return None
    p = Path(raw_path)
    try:
        return p.stat().st_size
    except Exception:  # noqa: BLE001
        return None


@router.get("/documents")
async def list_documents(
    source: str | None = None,
    search: str | None = None,
    page: int = 0,
    limit: int = 50,
    include_out_of_scope: bool = False,
):
    m = _manifest()
    if not m:
        return {
            "total": 0,
            "page": page,
            "limit": limit,
            "rows": [],
            "out_of_scope_count": 0,
        }
    all_rows = m.get_documents(source_type=source)
    if include_out_of_scope:
        oos_rows = m.get_documents(source_type=source, status="out_of_scope")
        all_rows = list(all_rows) + list(oos_rows)
        oos_total = len(oos_rows)
    else:
        oos_total = len(m.get_documents(source_type=source, status="out_of_scope"))
    # Build one source_id → row lookup so the path-walker can resolve Notion
    # ancestor chains in O(1) per hop instead of issuing N manifest queries.
    by_source_id = {str(r.get("source_id")): r for r in all_rows if r.get("source_id")}
    rows = []
    for r in all_rows:
        doc = _row_to_doc(r, by_source_id=by_source_id)
        doc["harvest_status"] = r.get("harvest_status") or "active"
        rows.append(doc)
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in (r["title"] or "").lower()]
    total = len(rows)
    start = page * limit
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "rows": rows[start : start + limit],
        # How many out_of_scope docs exist for this filter — the UI uses this
        # to decide whether to show the "include archived" affordance.
        "out_of_scope_count": oos_total,
    }


@router.get("/documents/stats")
async def stats():
    m = _manifest()
    if not m:
        return {
            "total_documents": 0,
            "total_bytes": 0,
            "sources_connected": 0,
            "last_harvest_at": None,
            "by_source": {},
            "timeseries": [],
        }
    rows = m.get_documents()
    total_bytes = 0
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r.get("source_type") or "?"] = by_source.get(r.get("source_type") or "?", 0) + 1
        sz = _read_size(r.get("raw_path"))
        if sz:
            total_bytes += sz

    # Coarse timeseries: bucket by harvested_at date, last 14 days.
    buckets: dict[str, int] = {}
    for r in rows:
        ts = r.get("harvested_at")
        if not ts:
            continue
        day = ts[:10]
        buckets[day] = buckets.get(day, 0) + 1

    from datetime import timedelta

    today = datetime.utcnow().date()
    series = []
    for i in range(14):
        d = (today - timedelta(days=13 - i)).isoformat()
        series.append({"date": d, "count": buckets.get(d, 0)})

    # Latest harvested_at
    last = None
    for r in rows:
        ts = r.get("harvested_at")
        if ts and (last is None or ts > last):
            last = ts

    return {
        "total_documents": len(rows),
        "total_bytes": total_bytes,
        "sources_connected": len(by_source),
        "last_harvest_at": last,
        "by_source": by_source,
        "timeseries": series,
    }


@router.get("/documents/tree")
async def tree(source: str | None = None):
    """Build a hierarchical tree of harvested documents.

    Shape:

        {
          "tree": {
            "<source>": {
              "<group_label>": [           # Confluence space, or
                                           # Notion parent-page title.
                {"id", "title", "type", "children": [recursive] }
              ]
            }
          }
        }

    For Notion we surface the page→child-page hierarchy by walking
    ``metadata.parent_id`` from each row. For Confluence we group by
    space_key and keep the page list flat (the existing harvester
    doesn't preserve ancestor chains in metadata yet).

    Skipped / failed / soft-deleted documents are excluded so the tree
    only shows what was actually mapped.
    """
    m = _manifest()
    if not m:
        return {"tree": {}}
    rows = m.get_documents(source_type=source)

    # Filter to what successfully landed on disk.
    rows = [r for r in rows if (r.get("harvest_status") or "active") == "active"]

    # Index by source_id so we can walk parent → child relationships.
    by_source_id: dict[str, dict] = {}
    for r in rows:
        sid = r.get("source_id")
        if sid:
            by_source_id[sid] = r

    out: dict[str, dict[str, list[dict]]] = {}

    def _meta(r):
        md = r.get("metadata") or {}
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:  # noqa: BLE001
                md = {}
        return md

    def _node(r):
        d = _row_to_doc(r)
        return {
            "id": d["id"],
            "title": d["title"],
            "type": d["type"],
            "children": [],
        }

    for r in rows:
        src_type = r.get("source_type")
        out.setdefault(src_type, {})

        if src_type == "notion":
            md = _meta(r)
            parent_id = md.get("parent_id")
            parent_type = md.get("parent_type")
            # If the parent is another harvested page, attach this row
            # as a child of that page's node. Otherwise it's top-level
            # for its source.
            if parent_type == "page_id" and parent_id in by_source_id:
                # Defer — handled in the second pass after all nodes exist.
                continue
            # Top-level: file under "Top level" group within this source.
            out[src_type].setdefault("Top level", []).append(_node(r))
        else:
            # Confluence / Jira / Obsidian — group by space_key (or "—").
            label = _row_to_doc(r)["space"]
            out[src_type].setdefault(label, []).append(_node(r))

    # Second pass for Notion: attach children to their parents.
    if "notion" in out:
        # Build a lookup: doc_id -> node (only for top-level Notion nodes
        # we've already created, plus all rows so we can resolve parents
        # that became top-level themselves).
        all_nodes: dict[str, dict] = {}
        for group in out.get("notion", {}).values():
            for n in group:
                all_nodes[n["id"]] = n

        # We need to materialize nodes for any non-top-level rows too,
        # then graft them onto their parents. Walk rows again.
        for r in rows:
            if r.get("source_type") != "notion":
                continue
            md = _meta(r)
            parent_type = md.get("parent_type")
            parent_id = md.get("parent_id")
            if parent_type != "page_id" or parent_id not in by_source_id:
                continue  # already placed at top level
            child = _node(r)
            all_nodes[child["id"]] = child
            parent_doc_id = by_source_id[parent_id].get("id")
            parent_node = all_nodes.get(parent_doc_id)
            if parent_node is None:
                # Parent wasn't placed at top level (it's also nested).
                # Synthesize a minimal node and stash for later — the
                # next iteration will graft it.
                parent_node = _node(by_source_id[parent_id])
                all_nodes[parent_doc_id] = parent_node
                # Tentatively put it at top level; if a later row
                # promotes it as a child, we'll move it.
                out["notion"].setdefault("Top level", []).append(parent_node)
            parent_node["children"].append(child)

    # Sort: top-level first, alphabetical groups, alphabetical items.
    for src_type, groups in out.items():
        for label, items in groups.items():
            items.sort(key=lambda x: x["title"].lower())
        out[src_type] = dict(
            sorted(
                groups.items(),
                key=lambda kv: (kv[0] != "Top level", kv[0].lower()),
            )
        )

    return {"tree": out}


@router.get("/documents/graph")
async def graph():
    m = _manifest()
    if not m:
        return {"nodes": [], "links": []}
    rows = [_row_to_doc(r) for r in m.get_documents()]
    rows = rows[:200]
    nodes = [{"id": r["id"], "source": r["source"], "title": r["title"], "space": r["space"]} for r in rows]
    links: list[dict] = []
    # Connect nodes that share (source, space).
    by_space: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        by_space.setdefault((r["source"], r["space"]), []).append(r["id"])
    for ids in by_space.values():
        for i in range(len(ids) - 1):
            links.append({"source": ids[i], "target": ids[i + 1]})
            if len(links) > 320:
                return {"nodes": nodes, "links": links}
    return {"nodes": nodes, "links": links}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    m = _manifest()
    if not m:
        raise HTTPException(404, "no documents yet")
    row = m.lookup_by_id(doc_id)
    if not row:
        raise HTTPException(404, "not found")
    # Single-doc fetch — pass the manifest so the Notion path walker can
    # resolve ancestor rows via lookup_by_source_id. The viewer breadcrumb
    # needs the full chain, not just the immediate parent.
    return _row_to_doc(row, manifest=m)


_CONTENT_CAP_BYTES = 2_000_000


@router.get("/documents/{doc_id}/content")
async def get_content(doc_id: str):
    m = _manifest()
    if not m:
        raise HTTPException(404, "no documents yet")
    row = m.lookup_by_id(doc_id)
    if not row:
        raise HTTPException(404, "not found")
    raw = row.get("raw_path")
    raw_format = (row.get("raw_format") or "text").lower()
    if raw and Path(raw).is_file():
        try:
            text = Path(raw).read_text(encoding="utf-8", errors="replace")
            if len(text) <= _CONTENT_CAP_BYTES:
                return {"id": doc_id, "content": text, "format": raw_format}
            # Over the cap. For structured formats (JSON, HTML) a mid-stream
            # truncation breaks the client renderer (Notion's JSON.parse, HTML
            # parser). Fall back to the normalized markdown when available so
            # the FE still has something coherent to display.
            normalized = row.get("normalized_path")
            if raw_format in ("json", "html") and normalized and Path(normalized).is_file():
                md = Path(normalized).read_text(encoding="utf-8", errors="replace")
                return {
                    "id": doc_id,
                    "content": md[:_CONTENT_CAP_BYTES],
                    "format": row.get("normalized_format") or "markdown",
                }
            # Plain-text formats can be safely truncated.
            return {"id": doc_id, "content": text[:_CONTENT_CAP_BYTES], "format": raw_format}
        except Exception:  # noqa: BLE001
            pass
    return {"id": doc_id, "content": "Preview unavailable.", "format": "text"}


@router.get("/documents/{doc_id}/attachments")
async def list_attachments(doc_id: str):
    """List downloadable attachments for a document.

    Reads the on-disk ``attachments/`` directory next to the doc's raw file.
    The orchestrator stores files under content-hashed names (e.g.
    ``30b48dad97a296a9.png``) but records the *original* source-side
    filename in the manifest's ``metadata.attachments``. We surface the
    original name so the FE can both label the gallery readably and match
    inline markdown references like ``![alt](image-20250916-105445.png)``
    against the right file. The ``url`` continues to point at the on-disk
    hashed name, which is what :func:`get_attachment` serves.
    """
    m = _manifest()
    if not m:
        raise HTTPException(404, "no documents yet")
    row = m.lookup_by_id(doc_id)
    if not row:
        raise HTTPException(404, "not found")
    attach_dir = _attachments_dir(row)
    if not attach_dir:
        return {"items": []}

    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}
    disk_to_original: dict[str, str] = {}
    for a in metadata.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        local_path = a.get("local_path") or ""
        original = a.get("filename") or ""
        if local_path and original:
            disk_to_original[Path(local_path).name] = original

    items = []
    for p in sorted(attach_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        mime, _ = mimetypes.guess_type(p.name)
        mime = mime or "application/octet-stream"
        original = disk_to_original.get(p.name, p.name)
        items.append({
            "name": original,
            "disk_name": p.name,
            "size_bytes": size,
            "mime": mime,
            "is_image": mime.startswith("image/"),
            "url": f"/api/documents/{doc_id}/attachments/{p.name}",
        })
    return {"items": items}


@router.get("/documents/{doc_id}/attachments/{filename}")
async def get_attachment(doc_id: str, filename: str, inline: int = 0):
    """Serve a single attachment's bytes.

    Guards against directory traversal by resolving the requested filename
    against the doc's attachments dir and rejecting anything that escapes.

    ``?inline=1`` flips Content-Disposition from ``attachment`` (browser-
    triggered download) to ``inline`` so the in-app AttachmentViewer can
    feed bytes to pdf.js / fetch() without a save dialog.
    """
    # Reject obvious traversal up front — defense in depth alongside the
    # resolve+relative_to check below.
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(400, "invalid attachment name")

    m = _manifest()
    if not m:
        raise HTTPException(404, "no documents yet")
    row = m.lookup_by_id(doc_id)
    if not row:
        raise HTTPException(404, "not found")
    attach_dir = _attachments_dir(row)
    if not attach_dir:
        raise HTTPException(404, "no attachments for this document")

    target = (attach_dir / filename).resolve()
    try:
        target.relative_to(attach_dir.resolve())
    except ValueError:
        raise HTTPException(400, "invalid attachment path")
    if not target.is_file():
        raise HTTPException(404, "attachment not found")

    mime, _ = mimetypes.guess_type(target.name)
    mime = mime or "application/octet-stream"
    # Filenames in the attachments dir are content-addressed (raw_store writes
    # ``{hash}{ext}``) so the bytes for a given URL never change. A day of
    # browser caching means re-opening a PDF in the viewer is instant instead
    # of re-fetching + re-parsing on every modal open.
    #
    # The attachment bytes are whatever the source page's author uploaded,
    # and this URL is on the same origin as the API. Rendered as a document
    # (``inline`` + a browser-executable type such as text/html or SVG) a
    # hostile attachment would run script with full access to ``/api``. So:
    # ``nosniff`` stops the browser second-guessing the type, ``sandbox``
    # denies script even if a type slips through, and ``inline`` is granted
    # only to types the browser renders passively.
    headers = {
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }
    if inline and _inline_safe(mime):
        # Starlette's FileResponse forces ``Content-Disposition: attachment``
        # whenever ``filename=`` is set, overriding any custom header we
        # supply. Pass filename=None so our inline header survives. No CSP
        # ``sandbox`` here: passive types cannot run script, and a sandboxed
        # top-level PDF navigation trips up Chrome's built-in viewer.
        headers["Content-Disposition"] = f'inline; filename="{target.name}"'
        return FileResponse(target, media_type=mime, headers=headers)
    # Everything else is a download, and would be script-free even if the
    # browser somehow rendered it.
    headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    if _browser_executable(mime):
        # Never let the browser interpret these, even as a download it might
        # later open: force the opaque type.
        mime = "application/octet-stream"
    return FileResponse(target, media_type=mime, filename=target.name, headers=headers)


#: Types a browser renders without running anything from the file.
_INLINE_SAFE_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/avif",
        "text/plain",
        "text/csv",
        "application/json",
    }
)
#: Types the browser would execute or that can carry script.
_BROWSER_EXECUTABLE_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
        "text/javascript",
        "application/javascript",
        "application/x-javascript",
        "text/ecmascript",
    }
)


def _inline_safe(mime: str) -> bool:
    return mime in _INLINE_SAFE_TYPES or mime.startswith(("video/", "audio/"))


def _browser_executable(mime: str) -> bool:
    return mime in _BROWSER_EXECUTABLE_TYPES


@router.post("/documents/{doc_id}/reharvest")
async def reharvest_document(doc_id: str):
    """Force-fetch a single document and return the updated manifest row.

    Out-of-band: does not create a ``harvest_runs`` row, does not emit
    SSE events. Synchronous; the request stays open until the fetch +
    write completes (~3s worst case for a Notion page including
    rate-limit waits). The caller refetches the doc detail on success.
    """
    from src.config_file import get_source_config, load_config_file
    from src.harvester import DocRef
    from src.harvester.logger import HarvestLogger
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.orchestrator import HarvestOrchestrator
    from src.harvester.raw_store import RawStore
    from src.api import orchestrator as api_orch

    m = _manifest()
    if not m:
        raise HTTPException(404, "no documents yet")
    row = m.lookup_by_id(doc_id)
    if not row:
        raise HTTPException(404, "not found")

    # Reconstruct a DocRef from the manifest row.
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}
    modified_at = None
    sm = row.get("source_modified")
    if sm:
        try:
            modified_at = datetime.fromisoformat(sm)
        except (TypeError, ValueError):
            modified_at = None
    doc_ref = DocRef(
        source_id=row["source_id"],
        title=row.get("title") or "Untitled",
        source_type=row["source_type"],
        source_url=row.get("source_url"),
        modified_at=modified_at,
        metadata=metadata,
    )

    # Build a one-shot orchestrator scoped to just this doc. Reuse the
    # same plugin factory the regular harvest pipeline uses so token /
    # rate-limit config flows through identically.
    cfg = load_config_file()
    try:
        source_cfg = get_source_config(cfg, doc_ref.source_type)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"source config: {e}") from e

    plugin, closeable = api_orch._make_plugin(doc_ref.source_type, source_cfg)

    try:
        # HarvestOrchestrator requires a HarvestLogger. Per-doc reharvest is
        # out-of-band (no SSE, no harvest_runs row), so a plain file-only
        # logger writing to harvest-log.jsonl is enough — the harvester
        # invariants still hold (skipped/failed/deleted events get recorded).
        orchestrator = HarvestOrchestrator(
            plugin=plugin,
            manifest=m,
            harvest_logger=HarvestLogger(paths.data_dir() / "harvest-log.jsonl"),
            raw_store=RawStore(
                paths.data_dir() / "raw",
                converter_version=cfg.get("converter_version", "0.1.0"),
            ),
            normalized_store=NormalizedStore(paths.data_dir() / "normalized"),
            max_concurrent=1,
        )
        result = await orchestrator.harvest_one(doc_ref, force_full=True)
    finally:
        try:
            if closeable is not None and hasattr(closeable, "aclose"):
                await closeable.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await plugin.aclose()
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": True,
        "action": result["action"],
        "doc": _row_to_doc(result["row"]) if result.get("row") else None,
    }
