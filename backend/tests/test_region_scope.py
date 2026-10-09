"""region_scope — subtree resolution, signal roll-up, graph restriction."""

from __future__ import annotations

import json

from src.api import region_scope
from src.terrain.utils.models import GraphEdge, GraphNode, GraphView


def _sig(sid, kind="todo", **extra):
    return {"id": sid, "kind": kind, "title": sid, "summary": "", "severity": 10,
            "status": "open", "source_note_ids": ["n-1"], **extra}


def tree() -> dict:
    return {
        "generatedAt": "2026-08-08T10:00:00+00:00",
        "tree": [
            {
                "id": "node_root", "name": "Root", "level": 0, "parentId": None,
                "signals": [_sig("s-child-rollup"), _sig("s-root", kind="decision")],
                "tags": [],
                "children": [
                    {
                        "id": "node_a", "name": "A", "level": 1, "parentId": "node_root",
                        "signals": [_sig("s-child-rollup")],
                        "tags": [{"id": "tag.node_a", "label": "Alpha",
                                  "signals": [_sig("s-child-rollup"), _sig("s-tag", kind="open_question")]}],
                        "children": [],
                    },
                    {
                        "id": "node_b", "name": "B", "level": 1, "parentId": "node_root",
                        "signals": [], "tags": [{"id": "tag.node_b", "label": "Beta", "signals": []}],
                        "children": [],
                    },
                ],
            },
            {"id": "node_other", "name": "Other", "level": 0, "parentId": None, "signals": [],
             "tags": [{"id": "tag.node_other", "label": "Omega", "signals": []}], "children": []},
        ],
    }


def notes() -> dict:
    return {"notes": [
        {"id": "n-1", "regionId": "node_a", "tagIds": ["tag.node_a"], "source": "notion"},
        {"id": "n-2", "regionId": "node_b", "tagIds": ["tag.node_b"], "source": "confluence"},
        {"id": "n-3", "regionId": "node_other", "tagIds": ["tag.node_other", "tag.node_a"], "source": "notion"},
    ]}


def test_scope_sets_and_path():
    index = region_scope.build_index(tree(), notes())
    scope = region_scope.resolve_region(index, "node_root")
    assert scope.descendant_ids == {"node_root", "node_a", "node_b"}
    assert scope.leaf_ids == {"node_a", "node_b"}
    assert scope.tag_ids == {"tag.node_a", "tag.node_b"}
    assert scope.note_ids == {"n-1", "n-2"}
    assert scope.note_ids_extended == {"n-1", "n-2", "n-3"}  # n-3 via secondary tag
    assert [p["id"] for p in region_scope.resolve_region(index, "node_a").path] == ["node_root", "node_a"]
    assert region_scope.resolve_region(index, "nope") is None


def test_signals_dedupe_with_most_specific_attribution():
    index = region_scope.build_index(tree(), notes())
    sigs = {s["id"]: s for s in region_scope.signals_in_subtree(index, "node_root")}
    assert set(sigs) == {"s-child-rollup", "s-root", "s-tag"}
    assert sigs["s-child-rollup"]["tag_id"] == "tag.node_a"
    assert sigs["s-child-rollup"]["region_id"] == "node_a"
    assert sigs["s-root"]["region_id"] == "node_root" and sigs["s-root"]["tag_id"] is None
    only = region_scope.signals_in_subtree(index, "node_root", kinds={"decision"})
    assert [s["id"] for s in only] == ["s-root"]


def test_index_cache_invalidates_on_mtime(tmp_path):
    tp, np_ = tmp_path / "terrain.json", tmp_path / "mocknotes.json"
    tp.write_text(json.dumps(tree())); np_.write_text(json.dumps(notes()))
    first = region_scope.region_index(tp, np_)
    assert first is region_scope.region_index(tp, np_)
    t2 = tree(); t2["generatedAt"] = "later"
    tp.write_text(json.dumps(t2))
    import os
    os.utime(tp, (tp.stat().st_atime, tp.stat().st_mtime + 5))
    assert region_scope.region_index(tp, np_).generated_at == "later"
    assert region_scope.region_index(tmp_path / "missing.json", np_) is None


def test_restrict_graph_keeps_only_subtree():
    index = region_scope.build_index(tree(), notes())
    scope = region_scope.resolve_region(index, "node_a")
    g = GraphView(
        nodes=[
            GraphNode(id="node_root", type="region", label="Root", layer=3),
            GraphNode(id="node_a", type="region", label="A", layer=3),
            GraphNode(id="node_b", type="region", label="B", layer=3),
            GraphNode(id="tag.node_a", type="tag", label="Alpha", layer=2),
            GraphNode(id="tag.node_b", type="tag", label="Beta", layer=2),
            GraphNode(id="n-1", type="note", label="one", layer=0),
            GraphNode(id="n-2", type="note", label="two", layer=0),
            GraphNode(id="n-3", type="note", label="three", layer=0),
            GraphNode(id="sig.in", type="signal", label="in", layer=2, sourceNoteIds=["n-1"]),
            GraphNode(id="sig.out", type="signal", label="out", layer=2, sourceNoteIds=["n-2"]),
            GraphNode(id="ent.kept", type="entity", label="kept", layer=1),
            GraphNode(id="ent.lost", type="entity", label="lost", layer=1),
        ],
        edges=[
            GraphEdge(**{"from": "ent.kept", "to": "n-1", "type": "mentions", "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
            GraphEdge(**{"from": "ent.lost", "to": "n-2", "type": "mentions", "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
            GraphEdge(**{"from": "node_a", "to": "tag.node_a", "type": "contains", "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
        ],
    )
    out = region_scope.restrict_graph_to_region(g, scope)
    ids = {n.id for n in out.nodes}
    assert ids == {"node_a", "tag.node_a", "n-1", "n-3", "sig.in", "ent.kept"}
    assert all(e.from_ in ids and e.to in ids for e in out.edges)


def test_prompt_line_mentions_region_and_memory():
    index = region_scope.build_index(tree(), notes())
    scope = region_scope.resolve_region(index, "node_a")
    line = region_scope.prompt_line(scope, [{"title": "Keep", "body": "x " * 500}])
    assert 'region "A"' in line and "Root › A" in line
    assert "- Keep: " in line and "…" in line
