"""GET every endpoint the sample workspace shows and save the responses.

    MNEMIFY_HOME=... uv run --project backend python scripts/sample-data/snapshot.py

Writes ``$MNEMIFY_HOME/sample/snap/``. export.py turns that into the app's
``public/demo`` fixtures; nothing here is reshaped yet.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_api import client, get_json, home, walk_regions


def main() -> None:
    out = home() / "sample" / "snap"
    # Validate everything (home, server URL) before clearing the old snapshot.
    c = client(timeout=120)
    if out.exists():
        shutil.rmtree(out)
    (out / "docs").mkdir(parents=True)
    (out / "regions").mkdir()
    (out / "threads").mkdir()

    def save(rel: str, payload) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    with c:
        for name in ("render-data", "notes", "attention", "report"):
            save(f"terrain-{name}.json", get_json(c, f"/api/terrain/{name}"))
        save("documents-stats.json", get_json(c, "/api/documents/stats"))
        save("changes.json", get_json(c, "/api/changes"))
        save("action-items.json", get_json(c, "/api/action-items"))

        rows: list[dict] = []
        page = 0
        while True:
            batch = get_json(c, "/api/documents", page=page, limit=500)
            rows.extend(batch["rows"])
            if len(rows) >= batch["total"] or not batch["rows"]:
                break
            page += 1
        save("documents.json", rows)
        for row in rows:
            did = row["id"]
            save(f"docs/{did}.json", {
                "row": get_json(c, f"/api/documents/{did}"),
                "content": get_json(c, f"/api/documents/{did}/content"),
            })
        print(f"documents: {len(rows)}")

        index = get_json(c, "/api/regions")
        save("regions.json", index)
        details: dict[str, dict] = {}

        def detail(rid: str) -> dict:
            if rid not in details:
                details[rid] = get_json(c, f"/api/regions/{rid}")
            return details[rid]

        region_ids = walk_regions(index, detail)
        thread_ids: set[str] = set()
        for rid in region_ids:
            threads = get_json(c, f"/api/regions/{rid}/threads")
            thread_ids.update(t["id"] for t in threads.get("threads", []))
            save(f"regions/{rid}.json", {
                "detail": detail(rid),
                "changes": get_json(c, f"/api/regions/{rid}/changes"),
                "memory": get_json(c, f"/api/regions/{rid}/memory"),
                "threads": threads,
                "action_items": get_json(c, "/api/action-items", region_id=rid),
            })
        print(f"regions: {len(region_ids)}")
        for tid in sorted(thread_ids):
            save(f"threads/{tid}.json", get_json(c, f"/api/regions/threads/{tid}"))
        print(f"threads: {len(thread_ids)}")


if __name__ == "__main__":
    main()
