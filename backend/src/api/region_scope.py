"""Region subtree resolution over the compiled map.

One shared view of "everything under region X" for the workspace routes, the
action-items filter and the region-scoped ``/api/ask``. Works on the raw
``terrain.json`` / ``mocknotes.json`` dicts (like ``routes_action_items``)
and caches the parsed index by file mtime, the way ``ask_asof`` caches note
dates — a 7 MB file must not be re-read on every card render.

Vocabulary
----------
* ``descendant_ids`` — the region plus every region beneath it.
* ``leaf_ids`` — descendants with tags (tags only exist on leaves).
* ``note_ids`` — *primary* members: notes whose ``regionId`` is a leaf here.
  This is the set the reconciler snapshots (stable across moves of a single
  secondary tag link).
* ``note_ids_extended`` — primary ∪ notes that carry one of this subtree's
  tags as a secondary tag. This is what retrieval is scoped to, so a
  cross-cutting document is still reachable from every region it touches.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from src import paths
from src.terrain.utils.models import GraphView, KnowledgeMap

logger = logging.getLogger(__name__)


def _terrain_path() -> Path:
    return paths.data_dir() / "terrain.json"


def _notes_path() -> Path:
    return paths.data_dir() / "mocknotes.json"


@dataclass
class RegionIndex:
    generated_at: str
    nodes: dict[str, dict]
    parent: dict[str, str | None]
    children: dict[str, list[str]]
    roots: list[str]
    tag_owner: dict[str, str]
    tag_label: dict[str, str]
    notes: dict[str, dict]
    notes_by_region: dict[str, list[str]]
    notes_by_tag: dict[str, list[str]]
    _subtree_cache: dict[str, frozenset[str]] = field(default_factory=dict)
    _descendants_cache: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass
class RegionScope:
    region_id: str
    name: str
    level: int
    node: dict
    path: list[dict]
    descendant_ids: set[str]
    leaf_ids: set[str]
    tag_ids: set[str]
    note_ids: set[str]
    note_ids_extended: set[str]


_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[tuple[float, float], RegionIndex]] = {}


def region_index(
    terrain_path: Path | None = None, notes_path: Path | None = None
) -> RegionIndex | None:
    """Parsed, cached region index; ``None`` when no map is compiled."""
    tp = terrain_path or _terrain_path()
    np_ = notes_path or _notes_path()
    if not tp.is_file():
        return None
    key = str(tp.resolve())
    stamp = (tp.stat().st_mtime, np_.stat().st_mtime if np_.is_file() else 0.0)
    with _CACHE_LOCK:
        hit = _INDEX_CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    try:
        bm = json.loads(tp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("region index: cannot read %s", tp)
        return None
    notes_payload: dict = {}
    if np_.is_file():
        try:
            notes_payload = json.loads(np_.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("region index: cannot read %s", np_)
    index = build_index(bm, notes_payload)
    with _CACHE_LOCK:
        _INDEX_CACHE[key] = (stamp, index)
    return index


def build_index(bm: dict, notes_payload: dict | None = None) -> RegionIndex:
    nodes: dict[str, dict] = {}
    parent: dict[str, str | None] = {}
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    tag_owner: dict[str, str] = {}
    tag_label: dict[str, str] = {}

    def walk(node: dict, parent_id: str | None) -> None:
        nid = node.get("id")
        if not isinstance(nid, str):
            return
        nodes[nid] = node
        parent[nid] = parent_id
        children.setdefault(nid, [])
        if parent_id is None:
            roots.append(nid)
        else:
            children.setdefault(parent_id, []).append(nid)
        for tag in node.get("tags", []) or []:
            tid = tag.get("id")
            if isinstance(tid, str):
                tag_owner[tid] = nid
                tag_label[tid] = tag.get("label") or tid
        for child in node.get("children", []) or []:
            walk(child, nid)

    for root in bm.get("tree", []) or []:
        walk(root, None)

    notes: dict[str, dict] = {}
    notes_by_region: dict[str, list[str]] = {}
    notes_by_tag: dict[str, list[str]] = {}
    for n in (notes_payload or {}).get("notes", []) or []:
        nid = n.get("id")
        if not isinstance(nid, str):
            continue
        notes[nid] = n
        rid = n.get("regionId")
        if isinstance(rid, str):
            notes_by_region.setdefault(rid, []).append(nid)
        for tid in n.get("tagIds", []) or []:
            if isinstance(tid, str):
                notes_by_tag.setdefault(tid, []).append(nid)

    return RegionIndex(
        generated_at=str(bm.get("generatedAt") or ""),
        nodes=nodes, parent=parent, children=children, roots=roots,
        tag_owner=tag_owner, tag_label=tag_label, notes=notes,
        notes_by_region=notes_by_region, notes_by_tag=notes_by_tag,
    )


def descendant_ids(index: RegionIndex, region_id: str) -> frozenset[str]:
    hit = index._descendants_cache.get(region_id)
    if hit is not None:
        return hit
    out: set[str] = set()
    stack = [region_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(index.children.get(cur, []))
    fs = frozenset(out)
    index._descendants_cache[region_id] = fs
    return fs


def subtree_note_ids(index: RegionIndex, region_id: str) -> frozenset[str]:
    """Primary note members of the subtree (memoised per index)."""
    hit = index._subtree_cache.get(region_id)
    if hit is not None:
        return hit
    out: set[str] = set()
    for rid in descendant_ids(index, region_id):
        out.update(index.notes_by_region.get(rid, []))
    fs = frozenset(out)
    index._subtree_cache[region_id] = fs
    return fs


def region_path(index: RegionIndex, region_id: str) -> list[dict]:
    chain: list[str] = []
    cur: str | None = region_id
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = index.parent.get(cur)
    chain.reverse()
    return [
        {"id": rid, "name": index.nodes[rid].get("name") or rid,
         "level": int(index.nodes[rid].get("level") or 0)}
        for rid in chain if rid in index.nodes
    ]


def resolve_region(index: RegionIndex, region_id: str) -> RegionScope | None:
    node = index.nodes.get(region_id)
    if node is None:
        return None
    desc = set(descendant_ids(index, region_id))
    leaf_ids = {rid for rid in desc if index.nodes[rid].get("tags")}
    tag_ids = {tid for tid, owner in index.tag_owner.items() if owner in desc}
    note_ids = set(subtree_note_ids(index, region_id))
    extended = set(note_ids)
    for tid in tag_ids:
        extended.update(index.notes_by_tag.get(tid, []))
    return RegionScope(
        region_id=region_id,
        name=node.get("name") or region_id,
        level=int(node.get("level") or 0),
        node=node,
        path=region_path(index, region_id),
        descendant_ids=desc,
        leaf_ids=leaf_ids,
        tag_ids=tag_ids,
        note_ids=note_ids,
        note_ids_extended=extended,
    )


def signals_in_subtree(
    index: RegionIndex, region_id: str, kinds: set[str] | None = None
) -> list[dict]:
    """Every signal under ``region_id`` once, with its most specific
    attribution: tags are walked before their region so a tag-level copy
    wins, and a parent's top-N roll-up never duplicates a child's signal."""
    root = index.nodes.get(region_id)
    if root is None:
        return []
    out: dict[str, dict] = {}

    def add(signal: dict, *, region: dict, tag: dict | None) -> None:
        sid = signal.get("id")
        if not sid or sid in out:
            return
        if kinds is not None and signal.get("kind") not in kinds:
            return
        out[sid] = {
            **signal,
            "region_id": region.get("id"),
            "region_label": region.get("name"),
            "tag_id": tag.get("id") if tag else None,
            "tag_label": tag.get("label") if tag else None,
        }

    def walk(node: dict) -> None:
        for tag in node.get("tags", []) or []:
            for signal in tag.get("signals", []) or []:
                add(signal, region=node, tag=tag)
        for signal in node.get("signals", []) or []:
            add(signal, region=node, tag=None)
        for child in node.get("children", []) or []:
            walk(child)

    # Children first so a signal rolled up onto the parent is attributed to
    # the child that actually owns it.
    for child in root.get("children", []) or []:
        walk(child)
    for tag in root.get("tags", []) or []:
        for signal in tag.get("signals", []) or []:
            add(signal, region=root, tag=tag)
    for signal in root.get("signals", []) or []:
        add(signal, region=root, tag=None)
    return list(out.values())


def restrict_graph_to_region(graph: GraphView, scope: RegionScope) -> GraphView:
    """Copy of ``graph`` holding only this subtree: its region, tag and note
    nodes, signals with an in-scope source, and entities that still touch
    something. Generalises ``ask_asof.restrict_graph``."""
    dropped: set[str] = set()
    kept: list = []
    for n in graph.nodes:
        t = n.type
        if t == "note":
            keep = n.id in scope.note_ids_extended
        elif t == "region":
            keep = n.id in scope.descendant_ids
        elif t == "tag":
            keep = n.id in scope.tag_ids
        elif t == "signal":
            srcs = n.sourceNoteIds or []
            keep = any(s in scope.note_ids_extended for s in srcs) or (
                not srcs and (n.homeRegionId in scope.descendant_ids)
            )
        else:
            keep = True  # entities decided below
        if keep:
            kept.append(n)
        else:
            dropped.add(n.id)
    edges = [e for e in graph.edges if e.from_ not in dropped and e.to not in dropped]
    touched = {e.from_ for e in edges} | {e.to for e in edges}
    final_nodes = []
    for n in kept:
        if n.type == "entity" and n.id not in touched:
            dropped.add(n.id)
            continue
        final_nodes.append(n)
    edges = [e for e in edges if e.from_ not in dropped and e.to not in dropped]
    surprising = [
        s for s in graph.surprisingConnections
        if s.from_ not in dropped and s.to not in dropped
    ]
    return graph.model_copy(
        update={"nodes": final_nodes, "edges": edges, "surprisingConnections": surprising}
    )


def restrict_knowledge_map(km: KnowledgeMap, scope: RegionScope) -> KnowledgeMap:
    if km.graph is None:
        return km
    graph = restrict_graph_to_region(km.graph, scope)
    if hasattr(km, "model_copy"):
        return km.model_copy(update={"graph": graph})
    import copy

    clone = copy.copy(km)
    clone.graph = graph
    return clone


_MEMORY_MAX_ITEMS = 20
_MEMORY_MAX_CHARS = 4000
_MEMORY_BODY_CHARS = 600


def prompt_line(scope: RegionScope, memory_items: list[dict]) -> str:
    crumbs = " › ".join(p["name"] for p in scope.path) or scope.name
    sub = len(scope.descendant_ids) - 1
    head = (
        f"\n\nRegion scope: the user is working inside the region \"{scope.name}\" "
        f"({crumbs}; {len(scope.note_ids_extended)} notes, {sub} sub-regions). Your sources "
        "have been restricted to this region. If the question is about something outside "
        "it, say so plainly rather than guessing."
    )
    if not memory_items:
        return head
    lines = [
        "\nRegion memory (facts the user chose to keep; treat as trusted context and cite "
        "as [memory]):"
    ]
    used = 0
    for item in memory_items[:_MEMORY_MAX_ITEMS]:
        body = " ".join((item.get("body") or "").split())
        if len(body) > _MEMORY_BODY_CHARS:
            body = body[: _MEMORY_BODY_CHARS - 1] + "…"
        line = f"- {item.get('title') or 'Untitled'}: {body}"
        if used + len(line) > _MEMORY_MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    return head + "\n".join(lines)
