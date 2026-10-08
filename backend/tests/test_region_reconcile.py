"""Anchors follow their documents across recompiles."""

from __future__ import annotations

from src.api import region_reconcile, region_scope
from src.api.workspace_store import WorkspaceStore


def _bm(gen: str, regions: list[tuple[str, str, int, list[str]]], parents: dict | None = None):
    parents = parents or {}
    nodes = {}
    for rid, name, level, _ in regions:
        nodes[rid] = {"id": rid, "name": name, "level": level, "children": [], "tags": [], "signals": []}
    roots = []
    for rid, *_ in regions:
        p = parents.get(rid)
        (nodes[p]["children"] if p else roots).append(nodes[rid])
    for rid, *_r in regions:
        if not nodes[rid]["children"]:
            nodes[rid]["tags"] = [{"id": f"tag.{rid}", "label": rid, "signals": []}]
    notes = [
        {"id": nid, "regionId": rid, "tagIds": [f"tag.{rid}"]}
        for rid, _n, _l, nids in regions for nid in nids
    ]
    return region_scope.build_index({"generatedAt": gen, "tree": roots}, {"notes": notes})


def test_kept_remapped_and_orphaned(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    v1 = _bm("g1", [
        ("node_stable", "Stable", 0, ["n-1", "n-2"]),
        ("node_moving", "Moving", 0, ["n-3", "n-4", "n-5"]),
        ("node_gone", "Gone", 0, ["n-9"]),
    ])
    for rid in ("node_stable", "node_moving", "node_gone"):
        s = region_scope.resolve_region(v1, rid)
        store.get_or_create_anchor(rid, name=s.name, level=0, note_ids=s.note_ids, generated_at="g1")
    moving_key = store.anchor_by_region_id("node_moving")["key"]
    gone_key = store.anchor_by_region_id("node_gone")["key"]
    store.create_memory(moving_key, title="keep me", body="…")

    region_reconcile.ensure_reconciled(store, v1)
    assert store.meta_get("last_reconciled_generated_at") == "g1"
    region_reconcile.ensure_reconciled(store, v1)
    assert len(store.reconcile_log()) == 1

    v2 = _bm("g2", [
        ("node_stable", "Stable", 0, ["n-1", "n-2"]),
        ("node_moved", "Moving (renamed)", 0, ["n-3", "n-4", "n-6"]),
        ("node_new", "Brand new", 0, ["n-7"]),
    ])
    region_reconcile.ensure_reconciled(store, v2)
    moved = store.anchor_by_key(moving_key)
    assert moved["region_id"] == "node_moved" and moved["status"] == "attached"
    assert moved["region_id_history"] == ["node_moving"]
    assert sorted(moved["member_note_ids"]) == ["n-3", "n-4", "n-6"]
    assert store.anchor_for_history_id("node_moving")["key"] == moving_key
    assert store.list_memory([moving_key])[0]["title"] == "keep me"
    gone = store.anchor_by_key(gone_key)
    assert gone["status"] == "orphaned" and gone["region_id"] is None
    report = store.reconcile_log()[-1]["report"]
    assert report["remapped"][0]["to"] == "node_moved" and report["orphaned"] == [gone_key]

    # An orphan re-attaches when its documents come back.
    v3 = _bm("g3", [
        ("node_stable", "Stable", 0, ["n-1", "n-2"]),
        ("node_moved", "Moving (renamed)", 0, ["n-3", "n-4", "n-6"]),
        ("node_back", "Gone", 0, ["n-9", "n-10"]),
    ])
    region_reconcile.ensure_reconciled(store, v3)
    assert store.anchor_by_key(gone_key)["region_id"] == "node_back"
    store.close()


def test_parent_and_child_do_not_claim_the_same_node(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    v1 = _bm("g1", [
        ("node_p", "Parent", 0, []),
        ("node_c", "Child", 1, ["n-1", "n-2", "n-3"]),
        ("node_d", "Sibling", 1, ["n-4"]),
    ], parents={"node_c": "node_p", "node_d": "node_p"})
    for rid in ("node_p", "node_c"):
        s = region_scope.resolve_region(v1, rid)
        store.get_or_create_anchor(rid, name=s.name, level=s.level, note_ids=s.note_ids, generated_at="g1")
    region_reconcile.ensure_reconciled(store, v1)
    # The sibling vanished; parent and child both overlap the single new node.
    v2 = _bm("g2", [("node_x", "Child", 0, ["n-1", "n-2", "n-3"])])
    region_reconcile.ensure_reconciled(store, v2)
    attached = [a for a in store.anchors_all() if a["region_id"] == "node_x"]
    assert len(attached) == 1 and attached[0]["region_name"] == "Child"
    store.close()
