"""/api/regions — the region workspace.

A region at any level of the compiled tree opens as a workspace: an overview
(brief, decisions, open questions, action items, sources), the memory the
user kept there, and the conversations that belong to it. Read endpoints
work straight off ``terrain.json`` / ``mocknotes.json`` through
``region_scope``; everything user-authored goes through ``workspace_store``.

Region ids are content hashes that change on recompile, so every request that
touches the store first runs ``region_reconcile.ensure_reconciled`` (a no-op
once per compile). An old id that was remapped answers ``404`` with
``moved_to``; one that could not be re-attached answers ``410`` with the
anchor key so the UI can show its memory under "Unassigned".
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src import paths
from src.utils.hashing import short_hash

from . import region_overview, region_reconcile, region_scope, routes_action_items, routes_changes
from .workspace_store import ACTION_ITEM_STATUSES, WorkspaceStore

logger = logging.getLogger(__name__)

router = APIRouter()

_SIGNAL_CAP = 25
_MEMORY_PREVIEW = 5


# ── helpers ──────────────────────────────────────────────────────────


def _index() -> region_scope.RegionIndex:
    index = region_scope.region_index()
    if index is None:
        raise HTTPException(404, "no compiled map yet — run a compile")
    return index


def _scope(index: region_scope.RegionIndex, region_id: str, store: WorkspaceStore | None):
    """Resolve or explain: remapped → 404 + moved_to, orphaned → 410."""
    scope = region_scope.resolve_region(index, region_id)
    if scope is not None:
        return scope
    if store is not None:
        anchor = store.anchor_for_history_id(region_id)
        if anchor is not None:
            if anchor.get("region_id"):
                raise HTTPException(
                    404,
                    {"detail": "region was remapped after a recompile",
                     "moved_to": anchor["region_id"]},
                )
            raise HTTPException(
                410,
                {"detail": "region no longer exists in the current map",
                 "region_key": anchor["key"], "region_name": anchor["region_name"]},
            )
    raise HTTPException(404, f"unknown region {region_id}")


def _open_store_rw(index: region_scope.RegionIndex) -> WorkspaceStore:
    store = WorkspaceStore()
    region_reconcile.ensure_reconciled(store, index)
    return store


def _open_store_ro(index: region_scope.RegionIndex) -> WorkspaceStore | None:
    store = WorkspaceStore.open_if_exists()
    if store is not None:
        region_reconcile.ensure_reconciled(store, index)
    return store


def _anchor(store: WorkspaceStore, index: region_scope.RegionIndex, scope: region_scope.RegionScope) -> dict:
    return store.get_or_create_anchor(
        scope.region_id, name=scope.name, level=scope.level,
        note_ids=scope.note_ids, generated_at=index.generated_at,
    )


def _subtree_anchors(store: WorkspaceStore | None, scope: region_scope.RegionScope) -> dict[str, dict]:
    """``{region_id: anchor}`` for every anchor attached inside the subtree."""
    if store is None:
        return {}
    out: dict[str, dict] = {}
    for a in store.anchors_all():
        rid = a.get("region_id")
        if rid and rid in scope.descendant_ids:
            out[rid] = a
    return out


_DOC_LOCK = threading.Lock()
_DOC_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def _manifest_path() -> Path:
    return paths.data_dir() / "harvest-manifest.db"


def note_doc_map() -> dict[str, str]:
    """``note id → harvest-manifest doc id`` (notes are ``n-<short_hash(doc_id, 8)>``).
    Cached by manifest mtime."""
    p = _manifest_path()
    if not p.is_file():
        return {}
    key = str(p.resolve())
    mtime = p.stat().st_mtime
    with _DOC_LOCK:
        hit = _DOC_CACHE.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    from src.harvester.manifest import HarvestManifest

    out: dict[str, str] = {}
    try:
        manifest = HarvestManifest(p)
        try:
            for row in manifest.get_documents():
                did = row.get("id")
                if isinstance(did, str):
                    out[f"n-{short_hash(did, 8)}"] = did
        finally:
            manifest.close()
    except Exception:  # noqa: BLE001
        logger.exception("regions: cannot read manifest for doc ids")
        return {}
    with _DOC_LOCK:
        _DOC_CACHE[key] = (mtime, out)
    return out


def _signal_out(signal: dict, index: region_scope.RegionIndex, docs: dict[str, str]) -> dict:
    srcs = [s for s in (signal.get("source_note_ids") or []) if isinstance(s, str)]
    first = next((s for s in srcs if s in index.notes), srcs[0] if srcs else None)
    note = index.notes.get(first) if first else None
    return {
        "id": signal.get("id"),
        "kind": signal.get("kind"),
        "title": signal.get("title") or "",
        "summary": signal.get("summary") or "",
        "severity": int(signal.get("severity") or 0),
        "status": signal.get("status") or "open",
        "owner": signal.get("owner"),
        "due_date": signal.get("due_date"),
        "due_text": signal.get("due_text"),
        "created_or_updated_at": signal.get("created_or_updated_at"),
        "source_note_ids": srcs,
        "source_note_id": first,
        "source_note_title": note.get("title") if note else None,
        "source_note_url": note.get("sourceUrl") if note else None,
        "source_doc_id": docs.get(first) if first else None,
        "region_id": signal.get("region_id"),
        "region_label": signal.get("region_label"),
        "tag_id": signal.get("tag_id"),
        "tag_label": signal.get("tag_label"),
    }


def _sources_breakdown(index: region_scope.RegionIndex, note_ids: set[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for nid in note_ids:
        n = index.notes.get(nid)
        if n is None:
            continue
        src = n.get("source") or "unknown"
        counts[src] = counts.get(src, 0) + 1
    return [{"source": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def _last_touched(index: region_scope.RegionIndex, note_ids: set[str]) -> str | None:
    best: str | None = None
    for nid in note_ids:
        n = index.notes.get(nid)
        if not n:
            continue
        stamp = n.get("updatedAt") or n.get("createdAt")
        if isinstance(stamp, str) and (best is None or stamp > best):
            best = stamp
    return best


def _card(
    index: region_scope.RegionIndex,
    rid: str,
    *,
    anchors: dict[str, dict],
    counts: dict[str, dict[str, int]],
    visits: dict[str, str | None],
    depth: int,
) -> dict:
    node = index.nodes[rid]
    kinds = {"decision": 0, "open_question": 0, "todo": 0, "risk": 0}
    for s in region_scope.signals_in_subtree(index, rid):
        k = s.get("kind")
        if k in kinds and s.get("status") != "resolved":
            kinds[k] += 1
    anchor = anchors.get(rid)
    key = anchor["key"] if anchor else None
    note_ids = set(region_scope.subtree_note_ids(index, rid))
    return {
        "id": rid,
        "name": node.get("name") or rid,
        "level": int(node.get("level") or 0),
        "parent_id": index.parent.get(rid),
        "summary": node.get("summary") or "",
        "color": node.get("color"),
        "counts": node.get("aggregateCounts") or {},
        "note_count": len(note_ids),
        "attention": {
            "score": node.get("attentionScore"),
            "level": node.get("attentionLevel"),
        },
        "signal_counts": kinds,
        "memory_count": counts.get(key, {}).get("memory", 0) if key else 0,
        "thread_count": counts.get(key, {}).get("threads", 0) if key else 0,
        "last_visited_at": visits.get(key) if key else None,
        "last_touched_at": _last_touched(index, note_ids),
        "children": [
            _card(index, c, anchors=anchors, counts=counts, visits=visits, depth=depth + 1)
            for c in index.children.get(rid, [])
        ] if depth < 8 else [],
    }


def _memory_out(item: dict, anchor: dict | None) -> dict:
    return {
        **item,
        "region_id": anchor.get("region_id") if anchor else None,
        "region_name": anchor.get("region_name") if anchor else None,
    }


def _thread_out(t: dict, anchors_by_key: dict[str, dict]) -> dict:
    a = anchors_by_key.get(t.get("region_key") or "")
    return {
        "id": t["id"],
        "region_id": a.get("region_id") if a else None,
        "region_name": a.get("region_name") if a else None,
        "title": t.get("title") or "New thread",
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "message_count": int(t.get("message_count") or 0),
    }


def _message_out(m: dict) -> dict:
    payload = m.get("payload") or {}
    return {"id": m["id"], "role": m["role"], "text": m["text"], **payload}


# ── index ────────────────────────────────────────────────────────────


@router.get("/regions")
async def list_regions():
    index = _index()
    store = _open_store_ro(index)
    try:
        anchors_all = store.anchors_all() if store else []
        anchors = {a["region_id"]: a for a in anchors_all if a.get("region_id")}
        keys = [a["key"] for a in anchors_all]
        counts = store.anchor_counts(keys) if store else {}
        visits = {k: store.last_visit(k) for k in keys} if store else {}
        regions = [
            _card(index, rid, anchors=anchors, counts=counts, visits=visits, depth=0)
            for rid in index.roots
        ]
        unassigned = [
            {
                "region_key": a["key"],
                "region_name": a["region_name"],
                "memory_count": counts.get(a["key"], {}).get("memory", 0),
                "thread_count": counts.get(a["key"], {}).get("threads", 0),
            }
            for a in anchors_all
            if a.get("status") == "orphaned"
            and (counts.get(a["key"], {}).get("memory", 0) or counts.get(a["key"], {}).get("threads", 0))
        ]
    finally:
        if store:
            store.close()
    return {"generated_at": index.generated_at or None, "regions": regions, "unassigned": unassigned}


# ── static-prefix routes (declared before /regions/{region_id}) ──────


@router.get("/regions/threads")
async def list_all_threads(region_id: str | None = Query(default=None)):
    index = region_scope.region_index()
    store = WorkspaceStore.open_if_exists()
    if store is None:
        return {"threads": []}
    try:
        if index is not None:
            region_reconcile.ensure_reconciled(store, index)
        anchors_by_key = {a["key"]: a for a in store.anchors_all()}
        keys: list[str] | None = None
        if region_id:
            a = store.anchor_by_region_id(region_id)
            keys = [a["key"]] if a else []
        return {"threads": [_thread_out(t, anchors_by_key) for t in store.list_threads(keys)]}
    finally:
        store.close()


@router.get("/regions/threads/{thread_id}")
async def get_thread(thread_id: str):
    store = WorkspaceStore.open_if_exists()
    if store is None:
        raise HTTPException(404, "no such thread")
    try:
        t = store.get_thread(thread_id)
        if t is None:
            raise HTTPException(404, "no such thread")
        anchors_by_key = {a["key"]: a for a in store.anchors_all()}
        msgs = store.thread_messages(thread_id)
        t["message_count"] = len(msgs)
        return {"thread": _thread_out(t, anchors_by_key), "messages": [_message_out(m) for m in msgs]}
    finally:
        store.close()


class ThreadPatch(BaseModel):
    region_id: str | None = Field(default=None, max_length=80)


@router.patch("/regions/threads/{thread_id}")
async def patch_thread(thread_id: str, body: ThreadPatch):
    index = _index()
    store = _open_store_rw(index)
    try:
        if store.get_thread(thread_id) is None:
            raise HTTPException(404, "no such thread")
        key: str | None = None
        if body.region_id:
            scope = _scope(index, body.region_id, store)
            key = _anchor(store, index, scope)["key"]
        store.set_thread_region(thread_id, key)
        anchors_by_key = {a["key"]: a for a in store.anchors_all()}
        t = store.get_thread(thread_id) or {}
        t["message_count"] = len(store.thread_messages(thread_id))
        return _thread_out(t, anchors_by_key)
    finally:
        store.close()


@router.delete("/regions/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str):
    store = WorkspaceStore.open_if_exists()
    if store is None:
        raise HTTPException(404, "no such thread")
    try:
        if not store.delete_thread(thread_id):
            raise HTTPException(404, "no such thread")
    finally:
        store.close()
    return None


class MemoryPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    region_id: str | None = Field(default=None, max_length=80)


@router.patch("/regions/memory/{item_id}")
async def patch_memory(item_id: str, body: MemoryPatch):
    index = _index()
    store = _open_store_rw(index)
    try:
        if store.get_memory(item_id) is None:
            raise HTTPException(404, "no such memory item")
        key: str | None = None
        if body.region_id:
            scope = _scope(index, body.region_id, store)
            key = _anchor(store, index, scope)["key"]
        item = store.update_memory(item_id, title=body.title, body=body.body, region_key=key)
        return _memory_out(item, store.anchor_by_key(item["region_key"]))  # type: ignore[index]
    finally:
        store.close()


@router.delete("/regions/memory/{item_id}", status_code=204)
async def delete_memory(item_id: str):
    store = WorkspaceStore.open_if_exists()
    if store is None:
        raise HTTPException(404, "no such memory item")
    try:
        if not store.delete_memory(item_id):
            raise HTTPException(404, "no such memory item")
    finally:
        store.close()
    return None


@router.get("/regions/unassigned/{region_key}")
async def get_unassigned(region_key: str):
    store = WorkspaceStore.open_if_exists()
    if store is None:
        raise HTTPException(404, "no such region")
    try:
        a = store.anchor_by_key(region_key)
        if a is None:
            raise HTTPException(404, "no such region")
        anchors_by_key = {region_key: a}
        return {
            "region_key": a["key"],
            "region_name": a["region_name"],
            "status": a["status"],
            "current_region_id": a.get("region_id"),
            "items": [_memory_out(m, a) for m in store.list_memory([region_key])],
            "threads": [_thread_out(t, anchors_by_key) for t in store.list_threads([region_key])],
        }
    finally:
        store.close()


class ReassignBody(BaseModel):
    region_id: str = Field(min_length=1, max_length=80)


@router.post("/regions/unassigned/{region_key}/reassign")
async def reassign_unassigned(region_key: str, body: ReassignBody):
    """Pin an orphaned anchor to a region by hand: its memory and threads
    move onto that region's anchor and the orphan row goes away."""
    index = _index()
    store = _open_store_rw(index)
    try:
        a = store.anchor_by_key(region_key)
        if a is None:
            raise HTTPException(404, "no such region")
        scope = _scope(index, body.region_id, store)
        target = _anchor(store, index, scope)
        if target["key"] == region_key:
            return {"region_id": scope.region_id, "moved_memory": 0, "moved_threads": 0}
        moved_m = moved_t = 0
        for m in store.list_memory([region_key]):
            store.update_memory(m["id"], region_key=target["key"])
            moved_m += 1
        for t in store.list_threads([region_key]):
            store.set_thread_region(t["id"], target["key"])
            moved_t += 1
        with store._transaction():
            store._conn.execute("DELETE FROM region_anchors WHERE key = ?", (region_key,))
        return {"region_id": scope.region_id, "moved_memory": moved_m, "moved_threads": moved_t}
    finally:
        store.close()


# ── per-region ───────────────────────────────────────────────────────


@router.get("/regions/{region_id}")
async def get_region(region_id: str):
    index = _index()
    store = _open_store_ro(index)
    try:
        scope = _scope(index, region_id, store)
        node = scope.node
        docs = note_doc_map()
        anchors = _subtree_anchors(store, scope)
        self_anchor = anchors.get(region_id)
        keys = [a["key"] for a in anchors.values()]
        counts = store.anchor_counts(keys) if store else {}
        visits = {k: store.last_visit(k) for k in keys} if store else {}

        brief = {
            "source": "compiled",
            "text": node.get("compiled_note") or node.get("summary") or "",
            "created_at": index.generated_at or None,
            "provider": None,
            "model": None,
        }
        if store and self_anchor:
            row = store.get_brief(self_anchor["key"])
            if row and row.get("terrain_generated_at") == index.generated_at:
                brief = {
                    "source": "refreshed", "text": row["text"], "created_at": row["created_at"],
                    "provider": row["provider"], "model": row["model"],
                }

        decisions = [
            _signal_out(s, index, docs)
            for s in region_scope.signals_in_subtree(index, region_id, kinds={"decision"})
        ]
        questions = [
            _signal_out(s, index, docs)
            for s in region_scope.signals_in_subtree(index, region_id, kinds={"open_question"})
        ]
        decisions.sort(key=lambda s: (-s["severity"], s["title"].lower()))
        questions.sort(key=lambda s: (-s["severity"], s["title"].lower()))

        statuses = store.statuses() if store else {}
        items, bucket_counts, status_counts = routes_action_items.build_items(
            index, region_id=region_id, today=routes_action_items._today(), statuses=statuses
        )
        for it in items:
            first = next((s for s in it["source_note_ids"] if s in index.notes), None)
            it["source_doc_id"] = docs.get(first) if first else None
            it["source_note_title"] = index.notes[first].get("title") if first else None

        memory_preview: list[dict] = []
        if store and keys:
            anchors_by_key = {a["key"]: a for a in anchors.values()}
            memory_preview = [
                _memory_out(m, anchors_by_key.get(m["region_key"]))
                for m in store.list_memory(keys, limit=_MEMORY_PREVIEW)
            ]

        children = [
            _card(index, c, anchors=anchors, counts=counts, visits=visits, depth=7)
            for c in index.children.get(region_id, [])
        ]
        for c in children:
            c["children"] = []

        return {
            "region": {
                "id": region_id,
                "name": scope.name,
                "level": scope.level,
                "summary": node.get("summary") or "",
                "color": node.get("color"),
                "counts": node.get("aggregateCounts") or {},
                "note_count": len(scope.note_ids_extended),
                "attention": {"score": node.get("attentionScore"), "level": node.get("attentionLevel")},
                "last_touched_at": _last_touched(index, scope.note_ids_extended),
            },
            "path": scope.path,
            "children": children,
            "brief": brief,
            "decisions": {"total": len(decisions), "items": decisions[:_SIGNAL_CAP]},
            "open_questions": {"total": len(questions), "items": questions[:_SIGNAL_CAP]},
            "action_items": {"counts": bucket_counts, "counts_by_status": status_counts, "items": items},
            "sources": _sources_breakdown(index, scope.note_ids_extended),
            "memory_preview": memory_preview,
            "memory_count": sum(counts.get(k, {}).get("memory", 0) for k in keys),
            "thread_count": sum(counts.get(k, {}).get("threads", 0) for k in keys),
            "map": {
                "center": node.get("center"),
                "radius": node.get("radius"),
                "children": [
                    {"id": c.get("id"), "name": c.get("name"), "center": c.get("center"),
                     "radius": c.get("radius")}
                    for c in (node.get("children") or [])
                ],
            },
            "last_visited_at": visits.get(self_anchor["key"]) if self_anchor else None,
            "region_key": self_anchor["key"] if self_anchor else None,
            "generated_at": index.generated_at or None,
        }
    finally:
        if store:
            store.close()


async def subtree_changes(
    index: region_scope.RegionIndex, scope: region_scope.RegionScope, *, since: str, limit: int
) -> dict:
    raw = await routes_changes.list_changes(since=since, source=None, limit=1000)
    out: list[dict] = []
    unmapped = 0
    for c in raw["changes"]:
        did = c.get("doc_id")
        nid = f"n-{short_hash(did, 8)}" if isinstance(did, str) else None
        if nid is None or nid not in index.notes:
            unmapped += 1
            continue
        if nid not in scope.note_ids_extended:
            continue
        note = index.notes[nid]
        rid = note.get("regionId")
        out.append({
            **c,
            "note_id": nid,
            "region_id": rid,
            "region_name": (index.nodes.get(rid) or {}).get("name") if isinstance(rid, str) else None,
        })
    return {
        "boundary": raw["boundary"],
        "changes": out[:limit],
        "unmapped_count": unmapped,
        "truncated": raw["truncated"] or len(out) > limit,
    }


@router.get("/regions/{region_id}/changes")
async def region_changes(
    region_id: str,
    since: str = Query("last_compile"),
    limit: int = Query(200, ge=1, le=1000),
):
    index = _index()
    store = _open_store_ro(index)
    try:
        scope = _scope(index, region_id, store)
    finally:
        if store:
            store.close()
    return await subtree_changes(index, scope, since=since, limit=limit)


# ── memory ───────────────────────────────────────────────────────────


@router.get("/regions/{region_id}/memory")
async def list_memory(region_id: str):
    index = _index()
    store = _open_store_ro(index)
    try:
        scope = _scope(index, region_id, store)
        anchors = _subtree_anchors(store, scope)
        groups: list[dict] = []
        if store:
            ordered = [region_id] + sorted(
                (rid for rid in anchors if rid != region_id),
                key=lambda rid: [p["name"] for p in region_scope.region_path(index, rid)],
            )
            for rid in ordered:
                a = anchors.get(rid)
                items = [_memory_out(m, a) for m in store.list_memory([a["key"]])] if a else []
                if rid != region_id and not items:
                    continue
                groups.append({
                    "region_id": rid,
                    "region_name": index.nodes[rid].get("name") or rid,
                    "is_self": rid == region_id,
                    "path": [p["name"] for p in region_scope.region_path(index, rid)],
                    "items": items,
                })
        else:
            groups.append({
                "region_id": region_id, "region_name": scope.name, "is_self": True,
                "path": [p["name"] for p in scope.path], "items": [],
            })
        return {"groups": groups}
    finally:
        if store:
            store.close()


class MemoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    kind: Literal["answer", "selection"] = "answer"
    citations: list[dict] = Field(default_factory=list)
    source_note_ids: list[str] = Field(default_factory=list)
    origin: dict = Field(default_factory=dict)


@router.post("/regions/{region_id}/memory", status_code=201)
async def create_memory(region_id: str, body: MemoryCreate):
    index = _index()
    store = _open_store_rw(index)
    try:
        scope = _scope(index, region_id, store)
        anchor = _anchor(store, index, scope)
        item = store.create_memory(
            anchor["key"], title=body.title.strip(), body=body.body.strip(), kind=body.kind,
            citations=body.citations[:40], source_note_ids=body.source_note_ids[:100],
            origin=body.origin,
        )
        return _memory_out(item, anchor)
    finally:
        store.close()


# ── threads / visits / brief ─────────────────────────────────────────


@router.get("/regions/{region_id}/threads")
async def region_threads(region_id: str):
    index = _index()
    store = _open_store_ro(index)
    try:
        scope = _scope(index, region_id, store)
        if store is None:
            return {"threads": []}
        anchors = _subtree_anchors(store, scope)
        anchors_by_key = {a["key"]: a for a in anchors.values()}
        return {
            "threads": [
                _thread_out(t, anchors_by_key)
                for t in store.list_threads(list(anchors_by_key))
            ]
        }
    finally:
        if store:
            store.close()


@router.post("/regions/{region_id}/visit")
async def visit_region(region_id: str):
    index = _index()
    store = _open_store_rw(index)
    try:
        scope = _scope(index, region_id, store)
        anchor = _anchor(store, index, scope)
        previous, now = store.touch_visit(anchor["key"])
        return {"previous_visited_at": previous, "visited_at": now, "region_key": anchor["key"]}
    finally:
        store.close()


class RefreshBody(BaseModel):
    provider: str = Field(pattern=r"^(anthropic|openai|claude)$")
    model: str = Field(min_length=1, max_length=120)


@router.post("/regions/{region_id}/overview/refresh")
async def refresh_overview(
    region_id: str,
    body: RefreshBody,
    authorization: str | None = Header(default=None),
):
    from . import routes_ask

    key = routes_ask._resolve_key(body.provider, authorization)
    if routes_ask._PROVIDER_KEY_ENV.get(body.provider) and not key:
        raise HTTPException(
            401,
            f"no API key for {body.provider} — add it under Settings → AI & Models, "
            "or send Authorization: Bearer <key>.",
        )
    index = _index()
    store = _open_store_rw(index)
    try:
        scope = _scope(index, region_id, store)
        anchor = _anchor(store, index, scope)
        anchors = _subtree_anchors(store, scope)
        keys = [a["key"] for a in anchors.values()]
        memory = store.list_memory(keys, limit=20)
        statuses = store.statuses()
        todos, _b, _s = routes_action_items.build_items(
            index, region_id=region_id, today=routes_action_items._today(), statuses=statuses
        )
        todos = [t for t in todos if t["user_status"] != "dismissed"]
        try:
            changes = (await subtree_changes(index, scope, since="last_compile", limit=15))["changes"]
        except Exception:  # noqa: BLE001
            logger.exception("overview refresh: changes unavailable")
            changes = []
        prompt = region_overview.build_prompt(
            scope,
            memory_items=memory,
            decisions=region_scope.signals_in_subtree(index, region_id, kinds={"decision"}),
            open_questions=region_scope.signals_in_subtree(index, region_id, kinds={"open_question"}),
            todos=todos,
            changes=changes,
            sources={s["source"]: s["count"] for s in _sources_breakdown(index, scope.note_ids_extended)},
        )
    except Exception:
        store.close()
        raise

    async def gen():
        try:
            async for ev in region_overview.stream_brief(
                provider=body.provider, model=body.model, key=key, prompt=prompt,
                store=store, region_key=anchor["key"], terrain_generated_at=index.generated_at,
            ):
                yield ev
        finally:
            store.close()

    return EventSourceResponse(gen())


# ── import ───────────────────────────────────────────────────────────


class ImportBody(BaseModel):
    threads: list[dict] = Field(default_factory=list, max_length=200)
    dismissed_action_item_ids: list[str] = Field(default_factory=list, max_length=5000)


@router.post("/workspace/import")
async def import_workspace(body: ImportBody):
    """One-time import of the browser's localStorage state. Idempotent."""
    store = WorkspaceStore()
    try:
        t_imp, t_skip = store.import_threads(body.threads[:200])
        d_imp, d_skip = store.import_dismissals(body.dismissed_action_item_ids)
    finally:
        store.close()
    return {
        "threads_imported": t_imp, "threads_skipped": t_skip,
        "dismissals_imported": d_imp, "dismissals_skipped": d_skip,
    }
