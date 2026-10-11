"""Tiny client for a local Mnemify server running on a scratch home.

Base URL comes from ``MNEMIFY_SAMPLE_URL``, else ``$MNEMIFY_HOME/server.port``.
Only ever talks to 127.0.0.1.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_guard import local_url, scratch_home

HEADERS = {"X-Mnemify-Client": "sample-data"}


def home() -> Path:
    return scratch_home()


def base_url() -> str:
    url = os.environ.get("MNEMIFY_SAMPLE_URL")
    if url:
        return local_url(url)
    port_file = home() / "server.port"
    if not port_file.is_file():
        sys.exit(f"No {port_file}; start the server first (mnemify up) or set MNEMIFY_SAMPLE_URL.")
    return f"http://127.0.0.1:{port_file.read_text().strip()}"


def client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(base_url=base_url(), headers=HEADERS, timeout=timeout)


def get_json(c: httpx.Client, path: str, **params):
    r = c.get(path, params=params or None)
    r.raise_for_status()
    return r.json()


def sse(c: httpx.Client, path: str, body: dict, *, timeout: float = 900.0) -> Iterator[tuple[float, str, object]]:
    """POST and yield ``(ms_since_start, event, data)`` for each SSE event.
    ``data`` is parsed JSON when it parses, else the raw string."""
    start = time.monotonic()
    with c.stream("POST", path, json=body, timeout=timeout) as r:
        r.raise_for_status()
        event, data_lines = "message", []
        for line in r.iter_lines():
            if line == "":
                if data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        data: object = json.loads(raw)
                    except json.JSONDecodeError:
                        data = raw
                    yield (round((time.monotonic() - start) * 1000), event, data)
                event, data_lines = "message", []
                continue
            if line.startswith(":"):
                continue  # keep-alive comment
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data_lines.append(value)


def walk_regions(regions_index: dict, detail_for) -> list[str]:
    """Every region id reachable from the index roots (depth-first), using
    ``detail_for(id)`` to read children."""
    out: list[str] = []
    stack = [r["id"] for r in regions_index.get("regions", [])][::-1]
    while stack:
        rid = stack.pop()
        if rid in out:
            continue
        out.append(rid)
        detail = detail_for(rid)
        stack.extend([ch["id"] for ch in detail.get("children", [])][::-1])
    return out
