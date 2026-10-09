"""On-demand "Refresh overview" for a region workspace.

The default brief is the compiler's ``compiled_note``. This module writes a
fresher one on request with the user's BYOK chat provider, folding in what
the compiler cannot know: the memory items the user kept, the signals they
confirmed or dismissed, and what changed in the sources since the compile.
The result is stored in ``workspace.db`` and shown until the next refresh or
the next compile (``terrain_generated_at`` stamps which map it describes).
No retrieval runs — everything in the prompt is deterministic workspace state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator

from . import ask_providers, region_scope
from .workspace_store import WorkspaceStore

SYSTEM_PROMPT = (
    "You write the overview brief for one region of the user's personal knowledge map. "
    "Use ONLY the material provided; never invent facts, names or dates. Write markdown "
    "of at most 250 words with these headings, in this order: **What this region covers**, "
    "**Recent changes**, **Decisions**, **Open questions**, **Suggested next steps**. Omit a "
    "heading when there is nothing for it. When the user's memory items disagree with the "
    "compiled summary, prefer the memory items. No preamble, no closing remarks."
)

_MAX_MEMORY = 20
_MAX_SIGNALS = 10
_MAX_TODOS = 10
_MAX_CHANGES = 15
_BODY_CHARS = 600


def _clip(text: object, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build_prompt(
    scope: region_scope.RegionScope,
    *,
    memory_items: list[dict],
    decisions: list[dict],
    open_questions: list[dict],
    todos: list[dict],
    changes: list[dict],
    sources: dict[str, int],
) -> str:
    node = scope.node
    lines: list[str] = []
    crumbs = " › ".join(p["name"] for p in scope.path) or scope.name
    lines.append(f"# Region: {scope.name}")
    lines.append(f"Path: {crumbs}")
    lines.append(
        f"Notes: {len(scope.note_ids_extended)} · Sub-regions: {len(scope.descendant_ids) - 1}"
    )
    if sources:
        lines.append("Sources: " + ", ".join(f"{k} ({v})" for k, v in sorted(sources.items())))
    children = node.get("children", []) or []
    if children:
        lines.append("\n## Sub-regions")
        for c in children:
            cnt = (c.get("aggregateCounts") or {}).get("notes")
            lines.append(f"- {c.get('name')}" + (f" ({cnt} notes)" if cnt else ""))
    lines.append("\n## Compiled summary")
    lines.append(_clip(node.get("compiled_note") or node.get("summary") or "", 3000))
    if memory_items:
        lines.append("\n## User memory (trusted; prefer over the compiled summary)")
        for m in memory_items[:_MAX_MEMORY]:
            lines.append(f"- {m.get('title')}: {_clip(m.get('body'), _BODY_CHARS)}")
    if decisions:
        lines.append("\n## Decisions found in the sources")
        for s in decisions[:_MAX_SIGNALS]:
            lines.append(f"- {s.get('title')}: {_clip(s.get('summary'), 300)}")
    if open_questions:
        lines.append("\n## Open questions found in the sources")
        for s in open_questions[:_MAX_SIGNALS]:
            lines.append(f"- {s.get('title')}: {_clip(s.get('summary'), 300)}")
    if todos:
        lines.append("\n## Open action items")
        for t in todos[:_MAX_TODOS]:
            due = f" (due {t['due_date']}, {t['bucket']})" if t.get("due_date") else ""
            flag = " [confirmed by user]" if t.get("user_status") == "confirmed" else ""
            lines.append(f"- {t.get('title')}{due}{flag}")
    if changes:
        lines.append("\n## Source changes since the last compile")
        for c in changes[:_MAX_CHANGES]:
            lines.append(f"- {c.get('change')}: {c.get('title')} ({c.get('source')})")
    return "\n".join(lines)


async def stream_brief(
    *,
    provider: str,
    model: str,
    key: str | None,
    prompt: str,
    store: WorkspaceStore,
    region_key: str,
    terrain_generated_at: str,
) -> AsyncIterator[dict]:
    """SSE dicts: ``delta`` chunks then ``done {text, created_at}``; the brief
    is persisted before ``done`` is emitted."""
    parts: list[str] = []
    try:
        async for chunk in ask_providers.stream_chat(
            provider, model, key or "", [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT, max_tokens=800,
        ):
            parts.append(chunk)
            yield {"event": "delta", "data": json.dumps({"text": chunk})}
    except Exception as e:  # noqa: BLE001
        yield {"event": "error", "data": json.dumps({"message": str(e)[:200]})}
        return
    text = "".join(parts).strip()
    if not text:
        yield {"event": "error", "data": json.dumps({"message": "the model returned nothing"})}
        return
    row = store.put_brief(
        region_key, text=text, provider=provider, model=model,
        terrain_generated_at=terrain_generated_at,
    )
    yield {
        "event": "done",
        "data": json.dumps({
            "text": text,
            "created_at": row["created_at"] if row else datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
        }),
    }
