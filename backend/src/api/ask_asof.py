"""Ask "as of" a date — restrict retrieval to documents that existed then.

The map's timeline scrubber sends the cutoff as ``as_of`` on ``POST /api/ask``.
This module turns that into a view of the knowledge map in which every note
created after the cutoff is gone (with its edges and any signal that only it
supported), plus a prompt line telling the model what day it is reasoning
from. Tags, regions and entities stay: they are structure, and their summaries
are the one place later knowledge can still leak — see ``prompt_line``.

Honest limit: Mnemify keeps the latest version of each document, not its
history. A note created before the cutoff and edited after it is kept with its
*current* text. ``restrict_graph`` can't fix that; the prompt tells the model.

Created stamps come from ``mocknotes.json`` (``Note.createdAt`` / ``updatedAt``,
ids equal the graph's note node ids). Notes with no parseable date are kept —
a map with partial dates must never silently lose grounding.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import datetime, time, timezone
from pathlib import Path

from src import paths
from src.terrain.utils.models import GraphView, KnowledgeMap

logger = logging.getLogger(__name__)


def _notes_path() -> Path:
    return paths.data_dir() / "mocknotes.json"


def parse_as_of(raw: str) -> datetime:
    """Accept ``YYYY-MM-DD`` (→ end of that day, UTC) or any ISO datetime.
    Raises ``ValueError`` on anything else."""
    s = raw.strip()
    if not s:
        raise ValueError("empty as_of")
    if len(s) == 10:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        return datetime.combine(d, time.max, tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_stamp(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# mtime-keyed cache of {note_id: created_dt | None}; the file is ~1 MB and the
# scrubber may fire several asks per minute.
_CACHE_LOCK = threading.Lock()
_CREATED_CACHE: dict[str, tuple[float, dict[str, datetime | None]]] = {}


def note_created_index(path: Path | None = None) -> dict[str, datetime | None]:
    """``note id → created datetime`` (``None`` when the note has no usable
    stamp). Empty when the notes file is missing or unreadable."""
    p = path or _notes_path()
    if not p.is_file():
        return {}
    key = str(p.resolve())
    mtime = p.stat().st_mtime
    with _CACHE_LOCK:
        hit = _CREATED_CACHE.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("ask as_of: cannot read %s", p)
        return {}
    out: dict[str, datetime | None] = {}
    for n in payload.get("notes", []) or []:
        nid = n.get("id")
        if not isinstance(nid, str):
            continue
        created = _parse_stamp(n.get("createdAt"))
        updated = _parse_stamp(n.get("updatedAt"))
        # The compiler falls back to the modified time when a source has no
        # creation date, so "created" is the earlier of the two when both exist.
        first = min((d for d in (created, updated) if d is not None), default=None)
        out[nid] = first
    with _CACHE_LOCK:
        _CREATED_CACHE[key] = (mtime, out)
    return out


def excluded_note_ids(as_of: datetime, created: dict[str, datetime | None]) -> set[str]:
    """Note ids born *after* the cutoff. Undated notes are never excluded."""
    return {nid for nid, dt in created.items() if dt is not None and dt > as_of}


def restrict_graph(graph: GraphView, excluded: set[str]) -> GraphView:
    """Copy of ``graph`` without the excluded note nodes, the edges touching
    them, and signal nodes whose every source note was excluded."""
    if not excluded:
        return graph
    dropped: set[str] = set()
    kept_nodes = []
    for n in graph.nodes:
        if n.type == "note" and n.id in excluded:
            dropped.add(n.id)
            continue
        if n.type == "signal" and n.sourceNoteIds and all(
            s in excluded for s in n.sourceNoteIds
        ):
            dropped.add(n.id)
            continue
        kept_nodes.append(n)
    if not dropped:
        return graph
    kept_edges = [
        e for e in graph.edges
        if e.from_ not in dropped and e.to not in dropped
    ]
    kept_surprising = [
        s for s in graph.surprisingConnections
        if s.from_ not in dropped and s.to not in dropped
    ]
    return graph.model_copy(
        update={
            "nodes": kept_nodes,
            "edges": kept_edges,
            "surprisingConnections": kept_surprising,
        }
    )


def restrict_knowledge_map(km: KnowledgeMap, excluded: set[str]) -> KnowledgeMap:
    if km.graph is None or not excluded:
        return km
    graph = restrict_graph(km.graph, excluded)
    if graph is km.graph:
        return km
    if hasattr(km, "model_copy"):
        return km.model_copy(update={"graph": graph})
    # Duck-typed stand-ins (route tests hand in a namespace with a .graph).
    clone = copy.copy(km)
    clone.graph = graph
    return clone


def prompt_line(as_of: datetime, excluded_count: int) -> str:
    utc = as_of.astimezone(timezone.utc)
    day = f"{utc.day} {utc.strftime('%B %Y')}"
    hidden = (
        f" {excluded_count} later document{'s' if excluded_count != 1 else ''} "
        "have been removed from your sources."
        if excluded_count
        else ""
    )
    return (
        f"\n\nTime frame: the user is asking AS OF {day}. Reason only from what "
        f"was known on that date.{hidden} Treat topic and region summaries as "
        "possibly containing later knowledge and prefer the dated source "
        "excerpts. If the question needs information after that date, say so "
        "plainly rather than guessing."
    )
