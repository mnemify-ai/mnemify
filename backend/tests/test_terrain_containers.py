from __future__ import annotations

from src.terrain.utils.containers import container_path
from src.terrain.utils.models import SourceDocument


def _doc(source_type: str, metadata: dict) -> SourceDocument:
    return SourceDocument(
        id="d1",
        source_type=source_type,
        source_id="s1",
        title="Doc",
        metadata=metadata,
    )


def test_container_path_splits_obsidian_folder():
    doc = _doc("obsidian", {"folder": "01-Architecture-Decisions"})
    assert container_path(doc) == ["01-Architecture-Decisions"]


def test_container_path_nested_folder_becomes_segments():
    doc = _doc("obsidian", {"folder": "Projects/Alpha/Specs"})
    assert container_path(doc) == ["Projects", "Alpha", "Specs"]


def test_container_path_preserves_ordering_prefix_uniqueness():
    # 01-Foo and 02-Foo must NOT collapse to the same segment.
    a = container_path(_doc("obsidian", {"folder": "01-Foo"}))
    b = container_path(_doc("obsidian", {"folder": "02-Foo"}))
    assert a != b


def test_container_path_root_note_is_empty():
    assert container_path(_doc("obsidian", {"folder": ""})) == []


def test_container_path_handles_backslashes():
    doc = _doc("obsidian", {"folder": "Projects\\Alpha"})
    assert container_path(doc) == ["Projects", "Alpha"]


def test_container_path_no_folder_metadata_is_empty():
    assert container_path(_doc("notion", {})) == []
    assert container_path(_doc("notion", {"folder": None})) == []
    assert container_path(_doc("notion", {"folder": {"title": "DB"}})) == []
