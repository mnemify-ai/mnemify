"""workspace.db — user-authored region state (memory, threads, statuses)."""

from __future__ import annotations

import sqlite3

from src.api.workspace_store import WorkspaceStore


def test_fresh_db_is_stamped_and_open_if_exists_never_creates(tmp_path):
    db = tmp_path / "workspace.db"
    assert WorkspaceStore.open_if_exists(db) is None
    assert not db.exists()
    store = WorkspaceStore(db)
    store.close()
    conn = sqlite3.connect(str(db))
    assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 1
    conn.close()
    reopened = WorkspaceStore.open_if_exists(db)
    assert reopened is not None
    reopened.close()


def test_memory_crud_and_cascade(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    a = store.get_or_create_anchor("node_1", name="Ops", level=0, note_ids={"n-1"}, generated_at="g1")
    again = store.get_or_create_anchor("node_1", name="Ops", level=0, note_ids={"n-1"}, generated_at="g1")
    assert again["key"] == a["key"]

    item = store.create_memory(a["key"], title="T", body="B", kind="answer", citations=[{"x": 1}])
    assert item["citations"] == [{"x": 1}]
    assert store.list_memory([a["key"]])[0]["id"] == item["id"]

    updated = store.update_memory(item["id"], title="T2")
    assert updated["title"] == "T2" and updated["body"] == "B"

    counts = store.anchor_counts([a["key"]])
    assert counts[a["key"]] == {"memory": 1, "threads": 0}

    store._conn.execute("DELETE FROM region_anchors WHERE key = ?", (a["key"],))
    store._conn.commit()
    assert store.get_memory(item["id"]) is None  # ON DELETE CASCADE
    store.close()


def test_threads_messages_seq_and_import_idempotent(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    t = store.ensure_thread("abcdef1234", region_key=None, title="New thread")
    assert t["id"] == "abcdef1234"
    store.append_messages(t["id"], [
        {"id": "m1", "role": "user", "text": "hello world"},
        {"id": "m2", "role": "assistant", "text": "hi", "payload": {"citations": []}},
    ])
    store.append_messages(t["id"], [{"id": "m2", "role": "assistant", "text": "dup"}])
    msgs = store.thread_messages(t["id"])
    assert [m["seq"] for m in msgs] == [0, 1]
    assert msgs[1]["text"] == "hi"
    assert store.get_thread(t["id"])["title"] == "hello world"

    imported, skipped = store.import_threads([
        {"id": "abcdef1234", "title": "x", "createdAt": 1, "updatedAt": 2, "messages": []},
        {"id": "zzzzzz9999", "title": "Legacy", "createdAt": 1_700_000_000_000,
         "updatedAt": 1_700_000_001_000,
         "messages": [{"id": "lm1", "role": "user", "text": "q", "asOf": "2026-01-01"}]},
    ])
    assert (imported, skipped) == (1, 1)
    legacy = store.get_thread("zzzzzz9999")
    assert legacy["title"] == "Legacy" and legacy["updated_at"].startswith("2023-11-14")
    assert store.thread_messages("zzzzzz9999")[0]["payload"] == {"asOf": "2026-01-01"}
    listed = store.list_threads(None)
    assert {x["id"] for x in listed} == {"abcdef1234", "zzzzzz9999"}
    assert next(x for x in listed if x["id"] == "abcdef1234")["message_count"] == 2
    assert store.delete_thread("zzzzzz9999") and store.thread_messages("zzzzzz9999") == []
    store.close()


def test_statuses_never_downgrade_on_import(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.set_status("signal.todo.a", "confirmed")
    imported, skipped = store.import_dismissals(["signal.todo.a", "signal.todo.b", ""])
    assert (imported, skipped) == (1, 2)
    assert store.statuses() == {"signal.todo.a": "confirmed", "signal.todo.b": "dismissed"}
    store.close()


def test_visit_and_brief(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    a = store.get_or_create_anchor("node_1", name="Ops", level=0, note_ids=set(), generated_at="g1")
    prev, now = store.touch_visit(a["key"])
    assert prev is None and now
    prev2, _ = store.touch_visit(a["key"])
    assert prev2 == now
    row = store.put_brief(a["key"], text="brief", provider="openai", model="m", terrain_generated_at="g1")
    assert row["text"] == "brief"
    assert store.get_brief(a["key"])["terrain_generated_at"] == "g1"
    store.close()
