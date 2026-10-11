"""Notes carry their container path (docPath) and the source's created date."""

from __future__ import annotations

from src.terrain import TerrainCompiler
from src.terrain.utils.models import Offset, SourceDocument, Tag


def _tag(tid: str) -> Tag:
    return Tag(
        id=tid, label=tid, type="concept", frequency=0, recencyScore=0.5,
        degree=0, elevation=10, offset=Offset(dx=0.0, dz=0.0), noteIds=[],
    )


def _notes_for(tmp_path, documents: list[SourceDocument]):
    compiler = TerrainCompiler(data_dir=tmp_path, ai_mode="local")
    tag = _tag("tag.t1")
    notes = compiler._build_notes(
        documents=documents,
        enriched=[],
        doc_to_tags={d.id: {tag.id} for d in documents},
        tags_by_id={tag.id: tag},
        tag_to_leaf={tag.id: "node_leaf"},
        surviving_leaves={"node_leaf"},
    )
    return {n.title: n for n in notes}


def test_doc_path_per_source(tmp_path):
    docs = [
        SourceDocument(
            id="d-root", source_type="notion", source_id="p-root", title="Leadership",
            metadata={"parent_type": "workspace", "created_at": "2026-05-01T09:00:00Z"},
        ),
        SourceDocument(
            id="d-child", source_type="notion", source_id="p-child", title="Board Update",
            metadata={"parent_type": "page_id", "parent_id": "p-root"},
        ),
        SourceDocument(
            id="d-conf", source_type="confluence", source_id="c1", title="ADR-024",
            metadata={"space_key": "ENG", "ancestors": [{"id": "x", "title": "Decisions"}]},
        ),
        SourceDocument(
            id="d-obs", source_type="obsidian", source_id="o1", title="2026-10-09",
            metadata={"folder": "Daily"},
        ),
        SourceDocument(
            id="d-loc", source_type="localfiles", source_id="l1", title="Running TODO",
            metadata={"folder": "scratch/todo"},
        ),
    ]
    notes = _notes_for(tmp_path, docs)
    # A top-level Notion page has no container (not the generic "Workspace"),
    # so the tree can fold it together with its children.
    assert notes["Leadership"].docPath == []
    assert notes["Board Update"].docPath == ["Leadership"]
    assert notes["ADR-024"].docPath == ["ENG", "Decisions"]
    assert notes["2026-10-09"].docPath == ["Daily"]
    assert notes["Running TODO"].docPath == ["scratch", "todo"]


def test_created_at_from_notion_and_confluence_metadata(tmp_path):
    docs = [
        SourceDocument(
            id="d1", source_type="confluence", source_id="c1", title="Runbook",
            source_modified="2026-09-30T00:00:00Z",
            metadata={"space_key": "PLAT", "created_at": "2026-06-02T10:00:00Z"},
        ),
    ]
    note = _notes_for(tmp_path, docs)["Runbook"]
    assert note.createdAt == "2026-06-02T10:00:00Z"
    assert note.updatedAt == "2026-09-30T00:00:00Z"
