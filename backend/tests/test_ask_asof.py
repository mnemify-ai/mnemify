"""ask_asof — the "ask as of a date" view over the knowledge map."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.api import ask_asof
from src.terrain.utils.models import GraphEdge, GraphNode, GraphView, SurprisingEdge


def _graph() -> GraphView:
    return GraphView(
        nodes=[
            GraphNode(id="tag.a", type="tag", label="Alpha", layer=2),
            GraphNode(id="n-old", type="note", label="Old note", layer=0),
            GraphNode(id="n-new", type="note", label="New note", layer=0),
            GraphNode(id="sig.only-new", type="signal", label="Risk", layer=0,
                      sourceNoteIds=["n-new"]),
            GraphNode(id="sig.mixed", type="signal", label="Todo", layer=0,
                      sourceNoteIds=["n-old", "n-new"]),
        ],
        edges=[
            GraphEdge.model_validate({"from": "tag.a", "to": "n-old", "type": "contains",
                                      "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
            GraphEdge.model_validate({"from": "tag.a", "to": "n-new", "type": "contains",
                                      "weight": 1.0, "provenance": "extracted", "confidence": 1.0}),
        ],
        surprisingConnections=[
            SurprisingEdge.model_validate({"from": "n-new", "to": "tag.a", "score": 0.5}),
        ],
    )


def test_parse_as_of_date_is_end_of_day_utc():
    dt = ask_asof.parse_as_of("2025-03-14")
    assert dt.tzinfo is not None
    assert (dt.year, dt.month, dt.day, dt.hour) == (2025, 3, 14, 23)


def test_parse_as_of_accepts_iso_datetime_and_rejects_junk():
    dt = ask_asof.parse_as_of("2025-03-14T10:00:00Z")
    assert dt == datetime(2025, 3, 14, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        ask_asof.parse_as_of("yesterday")


def test_note_created_index_uses_earliest_stamp_and_keeps_undated(tmp_path):
    p = tmp_path / "mocknotes.json"
    p.write_text(json.dumps({"notes": [
        {"id": "n-a", "createdAt": "2025-06-01T00:00:00Z", "updatedAt": "2025-01-01T00:00:00Z"},
        {"id": "n-b", "createdAt": "", "updatedAt": ""},
        {"id": "n-c", "createdAt": "not a date", "updatedAt": "2025-02-01"},
    ]}), encoding="utf-8")
    idx = ask_asof.note_created_index(p)
    assert idx["n-a"] == datetime(2025, 1, 1, tzinfo=timezone.utc)  # min(created, updated)
    assert idx["n-b"] is None
    assert idx["n-c"] == datetime(2025, 2, 1, tzinfo=timezone.utc)

    cutoff = datetime(2025, 1, 15, tzinfo=timezone.utc)
    assert ask_asof.excluded_note_ids(cutoff, idx) == {"n-c"}  # undated n-b stays


def test_restrict_graph_drops_late_notes_their_edges_and_orphaned_signals():
    g = ask_asof.restrict_graph(_graph(), {"n-new"})
    ids = {n.id for n in g.nodes}
    assert ids == {"tag.a", "n-old", "sig.mixed"}
    assert [(e.from_, e.to) for e in g.edges] == [("tag.a", "n-old")]
    assert g.surprisingConnections == []


def test_restrict_graph_is_identity_without_exclusions():
    g = _graph()
    assert ask_asof.restrict_graph(g, set()) is g
    assert ask_asof.restrict_graph(g, {"n-unknown"}) is g


def test_prompt_line_names_the_day_and_the_hidden_count():
    line = ask_asof.prompt_line(datetime(2025, 3, 14, 23, tzinfo=timezone.utc), 3)
    assert "AS OF 14 March 2025" in line
    assert "3 later documents" in line
    assert "later document" not in ask_asof.prompt_line(
        datetime(2025, 3, 14, tzinfo=timezone.utc), 0
    )
