"""Tests for GET /api/action-items — read-time urgency bucketing."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient

TODAY = date(2026, 8, 10)


def _signal(sid: str, *, kind="todo", status="open", due=None, severity=50, **extra):
    return {
        "id": sid,
        "kind": kind,
        "title": f"Todo: {sid}",
        "summary": f"summary for {sid}",
        "severity": severity,
        "status": status,
        "due_date": due,
        "source_note_ids": ["n-d1"],
        "source_chunk_ids": ["c1"],
        **extra,
    }


def _terrain(tree: list[dict]) -> dict:
    return {"generatedAt": "2026-08-08T10:00:00+00:00", "tree": tree}


def _client(tmp_path, monkeypatch, terrain: dict | None) -> TestClient:
    from src.api import create_app
    from src.api import routes_action_items

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(routes_action_items, "_today", lambda: TODAY)
    if terrain is not None:
        data_dir = tmp_path / ".mnemify"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "terrain.json").write_text(json.dumps(terrain), encoding="utf-8")
    return TestClient(create_app())


def test_404_when_no_compile(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, None)
    assert client.get("/api/action-items").status_code == 404


def test_buckets_sorting_and_filtering(tmp_path, monkeypatch):
    tree = [
        {
            "id": "region.1",
            "name": "Ops",
            "signals": [
                _signal("s-upcoming", due="2026-09-01"),
                _signal("s-resolved", status="resolved", due="2026-08-01"),
                _signal("s-risk", kind="risk", due="2026-08-01"),
            ],
            "tags": [
                {
                    "id": "tag.1",
                    "label": "Renewals",
                    "signals": [
                        _signal("s-overdue", due="2026-08-01", due_text="by August 1"),
                        _signal("s-soon", due="2026-08-14", owner="Sarah"),
                        _signal("s-nodate", severity=80),
                    ],
                }
            ],
            "children": [],
        }
    ]
    client = _client(tmp_path, monkeypatch, _terrain(tree))
    resp = client.get("/api/action-items")
    assert resp.status_code == 200
    data = resp.json()

    assert data["today"] == "2026-08-10"
    assert data["counts"] == {"overdue": 1, "due_soon": 1, "upcoming": 1, "no_date": 1}
    ids = [item["id"] for item in data["items"]]
    # resolved todo and non-todo kinds are excluded; buckets order the rest.
    assert ids == ["s-overdue", "s-soon", "s-upcoming", "s-nodate"]

    overdue = data["items"][0]
    assert overdue["bucket"] == "overdue"
    assert overdue["days_until_due"] == -9
    assert overdue["due_text"] == "by August 1"
    assert overdue["tag_id"] == "tag.1"
    assert overdue["tag_label"] == "Renewals"
    assert overdue["region_id"] == "region.1"
    assert overdue["region_label"] == "Ops"

    soon = data["items"][1]
    assert soon["bucket"] == "due_soon"
    assert soon["days_until_due"] == 4
    assert soon["owner"] == "Sarah"

    assert data["items"][3]["bucket"] == "no_date"
    assert data["items"][3]["days_until_due"] is None


def test_tag_attribution_wins_over_region_duplicate(tmp_path, monkeypatch):
    dup = _signal("s-dup", due="2026-08-20")
    tree = [
        {
            "id": "region.1",
            "name": "Ops",
            "signals": [dup],
            "tags": [{"id": "tag.1", "label": "Renewals", "signals": [dup]}],
            "children": [],
        }
    ]
    client = _client(tmp_path, monkeypatch, _terrain(tree))
    data = client.get("/api/action-items").json()
    assert len(data["items"]) == 1
    assert data["items"][0]["tag_id"] == "tag.1"


def test_walks_nested_children(tmp_path, monkeypatch):
    tree = [
        {
            "id": "region.1",
            "name": "Top",
            "signals": [],
            "tags": [],
            "children": [
                {
                    "id": "region.1.1",
                    "name": "Sub",
                    "signals": [_signal("s-nested", due="2026-08-11")],
                    "tags": [],
                    "children": [],
                }
            ],
        }
    ]
    client = _client(tmp_path, monkeypatch, _terrain(tree))
    data = client.get("/api/action-items").json()
    assert [item["id"] for item in data["items"]] == ["s-nested"]
    assert data["items"][0]["region_label"] == "Sub"
    assert data["items"][0]["bucket"] == "due_soon"
