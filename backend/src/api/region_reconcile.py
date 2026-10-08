"""Re-attach workspace anchors after a recompile.

Region ids are content hashes (``clusterer._node_id_from_ids``: path plus
sorted chunk ids), so any membership change gives a region a new id. Memory,
threads and visits reference an *anchor* (``region_anchors.key``), and this
module moves each anchor's ``region_id`` to the node that holds the same
documents today.

Algorithm
---------
1. Anchors whose id still exists are kept and their snapshot refreshed
   (an identical id means identical path and chunk membership).
2. Every other attached-or-orphaned anchor is matched against the unclaimed
   nodes by Jaccard overlap of primary note ids. Candidate pairs are sorted
   globally (best overlap, then same name, then same level, then the smaller
   subtree) and taken greedily, so a parent and its old child never claim the
   same node.
3. Whatever is left becomes ``orphaned`` — the UI shows it as "Unassigned",
   and the next compile tries again.

The lazy path (``ensure_reconciled`` on every workspace request) is the source
of truth; the compile-complete hook (``reconcile_now``) is only a warm-up.
"""

from __future__ import annotations

import json
import logging

from . import region_scope
from .workspace_store import WorkspaceStore

logger = logging.getLogger(__name__)

MIN_OVERLAP = 0.3
_META_KEY = "last_reconciled_generated_at"


def _jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def reconcile(store: WorkspaceStore, index: region_scope.RegionIndex) -> dict:
    anchors = store.anchors_all()
    current = set(index.nodes)
    claimed: set[str] = set()
    report: dict = {"kept": [], "remapped": [], "orphaned": []}

    stale: list[dict] = []
    for a in anchors:
        rid = a.get("region_id")
        if a.get("status") == "attached" and rid in current:
            node = index.nodes[rid]
            store.remap_anchor(
                a["key"], region_id=rid, name=node.get("name") or rid,
                level=node.get("level"),
                note_ids=region_scope.subtree_note_ids(index, rid),
                generated_at=index.generated_at,
            )
            claimed.add(rid)
            report["kept"].append(a["key"])
        else:
            stale.append(a)

    pairs: list[tuple[float, int, int, int, str, str]] = []
    for a in stale:
        snapshot = set(a.get("member_note_ids") or [])
        if not snapshot:
            continue
        for rid in current - claimed:
            members = region_scope.subtree_note_ids(index, rid)
            j = _jaccard(snapshot, members)
            if j < MIN_OVERLAP:
                continue
            node = index.nodes[rid]
            name_eq = 1 if (node.get("name") or "") == (a.get("region_name") or "") else 0
            level_pen = -abs(int(node.get("level") or 0) - int(a.get("level") or 0))
            pairs.append((j, name_eq, level_pen, -len(members), a["key"], rid))
    pairs.sort(reverse=True)

    assigned: set[str] = set()
    for j, _ne, _lp, _sz, key, rid in pairs:
        if key in assigned or rid in claimed:
            continue
        node = index.nodes[rid]
        anchor = store.anchor_by_key(key)
        store.remap_anchor(
            key, region_id=rid, name=node.get("name") or rid, level=node.get("level"),
            note_ids=region_scope.subtree_note_ids(index, rid),
            generated_at=index.generated_at,
        )
        assigned.add(key)
        claimed.add(rid)
        report["remapped"].append({
            "key": key, "from": (anchor or {}).get("region_id"), "to": rid, "jaccard": round(j, 3),
        })

    for a in stale:
        if a["key"] in assigned:
            continue
        if a.get("status") != "orphaned":
            store.orphan_anchor(a["key"])
        report["orphaned"].append(a["key"])
    return report


def ensure_reconciled(store: WorkspaceStore, index: region_scope.RegionIndex | None) -> None:
    """Idempotent per ``generatedAt``: runs the pass once per compile."""
    if index is None or not index.generated_at:
        return
    if store.meta_get(_META_KEY) == index.generated_at:
        return
    report = reconcile(store, index)
    store.meta_set(_META_KEY, index.generated_at)
    store.log_reconcile(index.generated_at, report)
    if report["remapped"] or report["orphaned"]:
        logger.info("workspace reconcile: %s", json.dumps(report))


def reconcile_now() -> None:
    """Best-effort hook for the compile orchestrator. Opens the store only
    when it already exists — a user who never opened a workspace gets no file."""
    store = WorkspaceStore.open_if_exists()
    if store is None:
        return
    try:
        ensure_reconciled(store, region_scope.region_index())
    finally:
        store.close()
