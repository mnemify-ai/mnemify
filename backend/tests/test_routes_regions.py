"""/api/regions — workspace payloads, memory, threads, visits, import."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient

TODAY = date(2026, 8, 10)
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def _sig(sid, kind="todo", **extra):
    return {"id": sid, "kind": kind, "title": f"{kind} {sid}", "summary": "s", "severity": 40,
            "status": "open", "source_note_ids": ["n-1"], "source_chunk_ids": [], **extra}


def _terrain(gen="2026-08-08T10:00:00+00:00") -> dict:
    return {
        "generatedAt": gen,
        "tree": [
            {
                "id": "node_root", "name": "Root", "level": 0, "parentId": None,
                "summary": "root summary", "compiled_note": "root compiled note",
                "aggregateCounts": {"notes": 2, "sources": 2, "tags": 2, "subRegions": 2},
                "signals": [_sig("s-dec", kind="decision"), _sig("s-q", kind="open_question")],
                "tags": [],
                "children": [
                    {"id": "node_a", "name": "A", "level": 1, "parentId": "node_root",
                     "summary": "a", "compiled_note": "a note",
                     "aggregateCounts": {"notes": 1, "sources": 1, "tags": 1, "subRegions": 0},
                     "signals": [], "children": [],
                     "tags": [{"id": "tag.node_a", "label": "Alpha",
                               "signals": [_sig("s-todo", due_date="2026-08-12")]}]},
                    {"id": "node_b", "name": "B", "level": 1, "parentId": "node_root",
                     "summary": "b", "compiled_note": "b note",
                     "aggregateCounts": {"notes": 1, "sources": 1, "tags": 1, "subRegions": 0},
                     "signals": [], "children": [],
                     "tags": [{"id": "tag.node_b", "label": "Beta", "signals": []}]},
                ],
            },
        ],
    }


def _notes() -> dict:
    return {"version": 1, "notes": [
        {"id": "n-1", "title": "Note one", "source": "notion", "sourceUrl": "https://n/1",
         "regionId": "node_a", "primaryTagId": "tag.node_a", "tagIds": ["tag.node_a"],
         "createdAt": "2026-08-01T00:00:00+00:00", "updatedAt": "2026-08-05T00:00:00+00:00"},
        {"id": "n-2", "title": "Note two", "source": "confluence", "sourceUrl": "https://c/2",
         "regionId": "node_b", "primaryTagId": "tag.node_b", "tagIds": ["tag.node_b"],
         "createdAt": "2026-08-02T00:00:00+00:00", "updatedAt": "2026-08-02T00:00:00+00:00"},
    ]}


def _client(tmp_path, monkeypatch, *, terrain: dict | None = None, notes: dict | None = None):
    from src.api import create_app, routes_action_items

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(routes_action_items, "_today", lambda: TODAY)
    data_dir = tmp_path / ".mnemify"
    data_dir.mkdir(parents=True, exist_ok=True)
    if terrain is not None:
        (data_dir / "terrain.json").write_text(json.dumps(terrain), encoding="utf-8")
    if notes is not None:
        (data_dir / "mocknotes.json").write_text(json.dumps(notes), encoding="utf-8")
    return TestClient(create_app())


def test_404_without_compile(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/regions").status_code == 404
    assert client.get("/api/regions/node_root").status_code == 404


def test_index_lists_nested_cards_without_touching_the_store(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    data = client.get("/api/regions").json()
    assert not (tmp_path / ".mnemify" / "workspace.db").exists()
    root = data["regions"][0]
    assert root["id"] == "node_root" and [c["id"] for c in root["children"]] == ["node_a", "node_b"]
    assert root["signal_counts"] == {"decision": 1, "open_question": 1, "todo": 1, "risk": 0}
    assert root["note_count"] == 2 and root["memory_count"] == 0
    assert root["last_touched_at"] == "2026-08-05T00:00:00+00:00"
    assert data["unassigned"] == []


def test_detail_payload_for_parent_and_leaf(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    data = client.get("/api/regions/node_root").json()
    assert data["region"]["name"] == "Root" and data["region"]["note_count"] == 2
    assert [p["id"] for p in data["path"]] == ["node_root"]
    assert [c["id"] for c in data["children"]] == ["node_a", "node_b"]
    assert data["brief"] == {
        "source": "compiled", "text": "root compiled note",
        "created_at": "2026-08-08T10:00:00+00:00", "provider": None, "model": None,
    }
    assert data["decisions"]["items"][0]["source_note_title"] == "Note one"
    assert data["open_questions"]["total"] == 1
    items = data["action_items"]["items"]
    assert [i["id"] for i in items] == ["s-todo"] and items[0]["user_status"] == "unverified"
    assert items[0]["bucket"] == "due_soon" and items[0]["source_note_title"] == "Note one"
    assert data["sources"] == [{"source": "confluence", "count": 1}, {"source": "notion", "count": 1}] or \
        data["sources"] == [{"source": "notion", "count": 1}, {"source": "confluence", "count": 1}]
    assert data["memory_preview"] == [] and data["last_visited_at"] is None

    leaf = client.get("/api/regions/node_a").json()
    assert [p["id"] for p in leaf["path"]] == ["node_root", "node_a"]
    assert leaf["children"] == [] and leaf["action_items"]["items"][0]["id"] == "s-todo"
    assert client.get("/api/regions/node_b").json()["action_items"]["items"] == []
    assert client.get("/api/regions/nope").status_code == 404


def test_memory_roundtrip_grouped_by_subregion(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    created = client.post("/api/regions/node_a/memory", json={
        "title": "Keep", "body": "Body text", "kind": "answer",
        "citations": [{"citation_id": "c1"}], "source_note_ids": ["n-1"],
        "origin": {"thread_id": "abcdef1234", "message_id": "m2"},
    })
    assert created.status_code == 201
    item = created.json()
    assert item["region_id"] == "node_a" and item["region_name"] == "A"

    groups = client.get("/api/regions/node_root/memory").json()["groups"]
    assert [g["region_id"] for g in groups] == ["node_root", "node_a"]
    assert groups[0]["is_self"] and groups[0]["items"] == []
    assert groups[1]["items"][0]["id"] == item["id"] and groups[1]["path"] == ["Root", "A"]

    detail = client.get("/api/regions/node_root").json()
    assert detail["memory_count"] == 1 and detail["memory_preview"][0]["title"] == "Keep"

    patched = client.patch(f"/api/regions/memory/{item['id']}", json={"title": "Keep 2"})
    assert patched.json()["title"] == "Keep 2" and patched.json()["body"] == "Body text"
    assert client.delete(f"/api/regions/memory/{item['id']}").status_code == 204
    assert client.delete(f"/api/regions/memory/{item['id']}").status_code == 404
    assert client.get("/api/regions/node_a/memory").json()["groups"][0]["items"] == []


def test_visit_statuses_and_threads(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    first = client.post("/api/regions/node_a/visit").json()
    assert first["previous_visited_at"] is None
    second = client.post("/api/regions/node_a/visit").json()
    assert second["previous_visited_at"] == first["visited_at"]
    assert client.get("/api/regions/node_a").json()["last_visited_at"] == second["visited_at"]

    assert client.patch("/api/action-items/s-todo/status", json={"status": "nope"}).status_code == 422
    ok = client.patch("/api/action-items/s-todo/status", json={"status": "confirmed"}).json()
    assert ok["status"] == "confirmed"
    detail = client.get("/api/regions/node_root").json()
    assert detail["action_items"]["items"][0]["user_status"] == "confirmed"
    assert detail["action_items"]["counts_by_status"]["confirmed"] == 1

    imp = client.post("/api/workspace/import", json={
        "threads": [{"id": "legacy0001", "title": "Old chat", "createdAt": 1, "updatedAt": 2,
                     "messages": [{"id": "lm1", "role": "user", "text": "hey"}]}],
        "dismissed_action_item_ids": ["s-todo", "signal.todo.other"],
    }).json()
    assert imp["threads_imported"] == 1 and imp["dismissals_imported"] == 1  # confirmed not downgraded
    again = client.post("/api/workspace/import", json={
        "threads": [{"id": "legacy0001", "title": "Old chat", "createdAt": 1, "updatedAt": 2, "messages": []}],
        "dismissed_action_item_ids": [],
    }).json()
    assert again["threads_skipped"] == 1

    all_threads = client.get("/api/regions/threads").json()["threads"]
    assert all_threads[0]["id"] == "legacy0001" and all_threads[0]["region_id"] is None
    assert client.get("/api/regions/node_a/threads").json()["threads"] == []
    moved = client.patch("/api/regions/threads/legacy0001", json={"region_id": "node_a"}).json()
    assert moved["region_id"] == "node_a"
    assert client.get("/api/regions/node_root/threads").json()["threads"][0]["region_name"] == "A"
    detail = client.get("/api/regions/threads/legacy0001").json()
    assert detail["messages"] == [{"id": "lm1", "role": "user", "text": "hey"}]
    assert client.delete("/api/regions/threads/legacy0001").status_code == 204
    assert client.get("/api/regions/threads/legacy0001").status_code == 404


def test_changes_are_mapped_to_subtree_notes(tmp_path, monkeypatch):
    from src.api import routes_changes
    from src.harvester.manifest import HarvestManifest
    from src.utils.hashing import short_hash

    data_dir = tmp_path / ".mnemify"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = HarvestManifest(data_dir / "harvest-manifest.db")
    doc_a, _ = manifest.upsert_document("notion", "p1", "Note one", source_url="https://n/1",
                                        content_hash="h1", raw_path="x")
    doc_b, _ = manifest.upsert_document("confluence", "p2", "Note two", source_url="https://c/2",
                                        content_hash="h2", raw_path="y")
    manifest.close()
    notes = _notes()
    notes["notes"][0]["id"] = f"n-{short_hash(doc_a, 8)}"
    notes["notes"][1]["id"] = f"n-{short_hash(doc_b, 8)}"
    with (data_dir / "harvest-log.jsonl").open("w", encoding="utf-8") as fh:
        for src, sid, title in (("notion", "p1", "Note one"), ("confluence", "p2", "Note two"),
                                ("notion", "p9", "Unmapped")):
            fh.write(json.dumps({"action": "harvested", "run": "r", "source": src, "id": sid,
                                 "title": title, "version": 1, "change": "updated",
                                 "ts": (NOW - timedelta(hours=1)).isoformat()}) + "\n")
    monkeypatch.setattr(routes_changes, "_last_compile_time", lambda: (NOW - timedelta(days=1)).isoformat())
    terrain = _terrain()
    for sig in terrain["tree"][0]["signals"]:
        sig["source_note_ids"] = [notes["notes"][0]["id"]]
    client = _client(tmp_path, monkeypatch, terrain=terrain, notes=notes)

    data = client.get("/api/regions/node_a/changes").json()
    assert [c["title"] for c in data["changes"]] == ["Note one"]
    assert data["changes"][0]["region_name"] == "A" and data["unmapped_count"] == 1
    root = client.get("/api/regions/node_root/changes").json()
    assert {c["title"] for c in root["changes"]} == {"Note one", "Note two"}
    assert client.get("/api/regions/node_root").json()["decisions"]["items"][0]["source_doc_id"] == doc_a


def test_remapped_and_orphaned_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    client.post("/api/regions/node_a/memory", json={"title": "k", "body": "b"})
    client.post("/api/regions/node_b/memory", json={"title": "k2", "body": "b2"})

    # Recompile: A keeps its notes under a new id; B vanishes entirely.
    t2 = _terrain(gen="2026-08-09T10:00:00+00:00")
    root = t2["tree"][0]
    root["children"] = [dict(root["children"][0], id="node_a2", name="A renamed")]
    root["children"][0]["tags"] = [{"id": "tag.node_a2", "label": "Alpha", "signals": []}]
    notes = _notes()
    notes["notes"][0]["regionId"] = "node_a2"
    notes["notes"][0]["tagIds"] = ["tag.node_a2"]
    notes["notes"] = notes["notes"][:1]
    data_dir = tmp_path / ".mnemify"
    (data_dir / "terrain.json").write_text(json.dumps(t2), encoding="utf-8")
    (data_dir / "mocknotes.json").write_text(json.dumps(notes), encoding="utf-8")
    import os
    for name in ("terrain.json", "mocknotes.json"):
        p = data_dir / name
        os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 10))

    moved = client.get("/api/regions/node_a")
    assert moved.status_code == 404 and moved.json()["detail"]["moved_to"] == "node_a2"
    assert client.get("/api/regions/node_a2/memory").json()["groups"][0]["items"][0]["title"] == "k"

    gone = client.get("/api/regions/node_b")
    assert gone.status_code == 410
    key = gone.json()["detail"]["region_key"]
    index = client.get("/api/regions").json()
    assert index["unassigned"][0]["region_key"] == key and index["unassigned"][0]["memory_count"] == 1
    orphan = client.get(f"/api/regions/unassigned/{key}").json()
    assert orphan["items"][0]["title"] == "k2"
    res = client.post(f"/api/regions/unassigned/{key}/reassign", json={"region_id": "node_a2"}).json()
    assert res["moved_memory"] == 1
    titles = {i["title"] for i in client.get("/api/regions/node_a2/memory").json()["groups"][0]["items"]}
    assert titles == {"k", "k2"}
    assert client.get("/api/regions").json()["unassigned"] == []


def test_overview_refresh_streams_and_persists(tmp_path, monkeypatch):
    from src.api import region_overview

    captured = {}

    async def _stream(provider, model, key, messages, system=None, max_tokens=0):
        captured["prompt"] = messages[0]["content"]
        captured["system"] = system
        yield "Fresh "
        yield "brief"

    monkeypatch.setattr(region_overview.ask_providers, "stream_chat", _stream)
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    client.post("/api/regions/node_root/memory", json={"title": "Remember", "body": "the thing"})
    client.patch("/api/action-items/s-todo/status", json={"status": "dismissed"})

    no_key = client.post("/api/regions/node_root/overview/refresh",
                         json={"provider": "openai", "model": "m"})
    assert no_key.status_code == 401

    resp = client.post("/api/regions/node_root/overview/refresh",
                       json={"provider": "openai", "model": "m"},
                       headers={"Authorization": "Bearer k"})
    assert resp.status_code == 200
    assert "event: delta" in resp.text and "event: done" in resp.text
    assert "Remember: the thing" in captured["prompt"]
    assert "decision s-dec" in captured["prompt"]
    assert "todo s-todo" not in captured["prompt"]  # dismissed items stay out
    brief = client.get("/api/regions/node_root").json()["brief"]
    assert brief["source"] == "refreshed" and brief["text"] == "Fresh brief" and brief["model"] == "m"


def test_full_reset_removes_workspace_db_but_harvest_reset_keeps_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, terrain=_terrain(), notes=_notes())
    client.post("/api/regions/node_a/memory", json={"title": "k", "body": "b"})
    db = tmp_path / ".mnemify" / "workspace.db"
    assert db.exists()
    from src.api import routes_harvest, routes_settings
    assert "workspace.db" not in routes_harvest._RESET_FILES
    assert "workspace.db" in routes_settings._RESET_FILES
