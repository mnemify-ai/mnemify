"""Where a harvested document lives inside its source.

Shared by ``/api/documents`` (breadcrumbs, the tree endpoint) and the terrain
compiler (``Note.docPath``), so the doc viewer's breadcrumb and the map's
Sources tree use the same rules. (The compiler resolves Notion parents among
the documents it compiled, so a parent left out of a compile can make the two
differ.)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.harvester.manifest import HarvestManifest


def parse_metadata(r: dict) -> dict:
    md = r.get("metadata") or {}
    if isinstance(md, str):
        try:
            return json.loads(md)
        except Exception:  # noqa: BLE001
            return {}
    return md if isinstance(md, dict) else {}


def compute_doc_path(
    r: dict,
    *,
    by_source_id: dict | None = None,
    manifest: HarvestManifest | None = None,
) -> tuple[list[str], list[str]]:
    """Compute the ancestor breadcrumb for a document, root-first, EXCLUDING
    the document itself.

    Strategy per source:
      • Obsidian / local files — split ``metadata.folder`` (root-relative).
      • Confluence — start with the space name/key, then walk
        ``metadata.ancestors`` (already root-first per the Confluence API).
      • Notion — walk ``parent_id`` chain. Uses ``by_source_id`` when
        provided (one O(1) dict instead of N manifest queries), otherwise
        falls back to manifest lookups for the single-doc endpoint.

    Returns parallel ``(titles, ids)`` lists. An empty ``id`` means the
    ancestor isn't itself a harvested document we can link to.
    """
    src = r.get("source_type")
    md = parse_metadata(r)

    if src in ("obsidian", "localfiles"):
        folder = md.get("folder") or ""
        titles = [seg for seg in folder.replace("\\", "/").split("/") if seg]
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
            pmd = parse_metadata(parent)
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
