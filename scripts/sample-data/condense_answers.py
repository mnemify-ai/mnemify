"""Shorten the recorded answers for the sample chat, keeping their citations.

    MNEMIFY_HOME=... uv run --project backend python scripts/sample-data/condense_answers.py [--ratio 0.6]

The agent's real answers run 4,000-6,500 characters: thorough, but long for
a preview. This asks Claude (the `claude` CLI, your subscription) to rewrite
each one at about `--ratio` of its length, keeping its structure and its
[cN] markers on the claims they support, then checks the result:

* every marker is one the original answer used (no invented citations);
* the length lands within TOLERANCE of the target ratio;
* the answer still cites at least half as many sources as before.

A failed check retries, then gives up loudly. Writes
``$MNEMIFY_HOME/sample/chat-condensed/<id>.json`` in the recorded format:
same agent steps and citations, the new text re-streamed over the original
text window, and ``citations_used`` narrowed to what the short answer cites
(so the map lights exactly those). export.py prefers these files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
sys.path.insert(0, str(HERE))

from export import strip_narration
from sample_api import home

from src.terrain.agents.claude_cli import claude_text

MARKER = re.compile(r"\[(c\d+)\]")
TOLERANCE = 0.07
SYSTEM = (
    "You edit answers produced by a research assistant over a person's notes. "
    "Shorten the answer you are given. Rules:\n"
    "- Target about {target} characters (the original is {orig}). Keep the "
    "markdown structure (headings, bullets, bold) but merge or drop the least "
    "important points.\n"
    "- Keep the citation markers like [c3] exactly as written, attached to the "
    "claims they support. Never invent a marker, never renumber one. Drop a "
    "marker only together with the claim it supported.\n"
    "- Do not add facts, dates, names or numbers that aren't in the original.\n"
    "- Keep the same voice: direct, second person to the reader where the "
    "original uses it.\n"
    "Output only the shortened answer, nothing before or after it."
)


def answer_text(events: list[dict]) -> str:
    return "".join(e["data"].get("text", "") for e in events if e["event"] == "delta" and isinstance(e["data"], dict))


def condense(text: str, ratio: float, model: str, attempts: int = 4) -> str:
    # Models overshoot a length target; aim a little under it.
    target = int(len(text) * (ratio - 0.07))
    allowed = set(MARKER.findall(text))
    problems = ""
    for attempt in range(1, attempts + 1):
        prompt = text if not problems else f"{text}\n\n(Your previous attempt was rejected: {problems}. Try again.)"
        out = claude_text(prompt, system=SYSTEM.format(target=target, orig=len(text)), model=model, effort="low").strip()
        used = set(MARKER.findall(out))
        issues = []
        if not used <= allowed:
            issues.append(f"invented markers {sorted(used - allowed)}")
        r = len(out) / len(text)
        if abs(r - ratio) > TOLERANCE:
            issues.append(f"length {len(out)} is {r:.0%} of the original, wanted about {ratio:.0%}")
        if len(used) < max(1, len(allowed) // 2):
            issues.append(f"kept only {len(used)} of {len(allowed)} citations")
        if not issues:
            return out
        problems = "; ".join(issues)
        print(f"      attempt {attempt}: {problems}")
    sys.exit(f"could not condense within the rules: {problems}")


def rebuild_events(events: list[dict], short: str) -> list[dict]:
    """The recorded events with `short` streamed over the original text window
    and citations_used narrowed to the markers it keeps."""
    deltas = [e for e in events if e["event"] == "delta"]
    t0, t1 = deltas[0]["t"], deltas[-1]["t"]
    pieces = re.findall(r"\S+\s*|\s+", short)
    step = max(1, len(pieces) // max(1, len(deltas)))
    chunks = ["".join(pieces[i : i + step]) for i in range(0, len(pieces), step)]
    span = max(1, t1 - t0)
    new_deltas = [
        {"t": t0 + round(span * i / max(1, len(chunks) - 1)), "event": "delta", "data": {"text": c}}
        for i, c in enumerate(chunks)
    ]
    cited: set[str] = set()
    for e in events:
        if e["event"] == "citations":
            cited = {c["citation_id"] for c in e["data"].get("citations") or []}
    used = [m for m in dict.fromkeys(MARKER.findall(short)) if m in cited]

    out: list[dict] = []
    placed = False
    for e in events:
        if e["event"] == "delta":
            if not placed:
                out.extend(new_deltas)
                placed = True
            continue
        if e["event"] == "citations_used":
            out.append({**e, "data": {"used": used, "fallback": False}})
            continue
        out.append(e)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.6)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--only", nargs="*", help="question ids to (re)condense")
    args = ap.parse_args()

    src = home() / "sample" / "chat"
    dst = home() / "sample" / "chat-condensed"
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if args.only and rec["id"] not in args.only:
            continue
        events, _ = strip_narration(rec["events"])
        text = answer_text(events)
        print(f"[{rec['id']}] {len(text)} chars, {len(set(MARKER.findall(text)))} citations")
        short = condense(text, args.ratio, args.model)
        rec = {**rec, "events": rebuild_events(events, short), "condensedFrom": len(text)}
        (dst / path.name).write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"      → {len(short)} chars ({len(short) / len(text):.0%}), {len(set(MARKER.findall(short)))} citations")


if __name__ == "__main__":
    main()
