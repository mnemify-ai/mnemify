from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Iterable

from src.terrain.utils.deadlines import parse_anchor, resolve_deadline
from src.terrain.utils.models import (
    AttentionLevel,
    AttentionSignal,
    AttentionSignalKind,
    ChunkSignalDraft,
    EnrichedChunk,
    SourceDocument,
)
from src.utils.hashing import short_hash


_ACTION_RE = re.compile(
    r"\b(action item|next step|todo|follow up|prepare|send|schedule|finali[sz]e|"
    r"address|ensure|need to|must|should|owner|due|by end of|by may|by jun|by q[1-4])\b",
    re.IGNORECASE,
)
_RISK_RE = re.compile(
    r"\b(risk|blocker|blocked|concern|issue|problem|delay|delayed|unsatisfied|"
    r"struggle|fails?|failure|regression|losing|contingent|unacceptable|missing|"
    r"poorly calibrated|not yet confirmed|slow procurement)\b",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(
    r"\b(decision|decided|approved|chosen|selected|will use|we use|do not use|"
    r"must not use|plan is|agreed|committed)\b",
    re.IGNORECASE,
)
_OPEN_Q_RE = re.compile(
    r"\b(open question|question|clarify|confirm|double-check|tbd|unknown|"
    r"need to know|whether|should we|can we|do we)\b",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(
    r"\b(?:owner|action owner|assigned to)\s*[:=-]\s*([A-Z][A-Za-z0-9_.-]+(?:\s+[A-Z][A-Za-z0-9_.-]+){0,2})",
)
_NAME_TO_RE = re.compile(
    r"^\s*(?:[-*]\s*)?([A-Z][A-Za-z0-9_.-]+)\s+to\s+([a-z][^\n]{8,})",
)
_URGENT_RE = re.compile(
    r"\b(critical|urgent|asap|blocker|losing|failed|must|before the end|by end of|"
    r"renewal|contract|customer|legal|sla|regression)\b",
    re.IGNORECASE,
)
_RESOLVED_RE = re.compile(
    r"\b(done|resolved|closed|shipped|deployed|completed|fixed|approved)\b",
    re.IGNORECASE,
)


def extract_attention_signals(
    item: EnrichedChunk,
    *,
    note_id: str,
    document: SourceDocument | None = None,
    anchor_date: str | None = None,
    max_lines: int = 30,
) -> list[AttentionSignal]:
    """Extract source-grounded attention signals from one enriched chunk.

    Prefers signals already drafted by the LLM feature extractor
    (``item.features.signals`` — openai/claude modes; see
    ``ChunkFeatures.signals``), which is negation-aware and judges severity
    in context. Falls back to the original deterministic regex pass when no
    LLM signals are present: local mode (which never populates
    ``features.signals``), or any chunk where LLM extraction failed and fell
    back to the local heuristic extractor.

    ``anchor_date`` is the document's effective authored date — the reference
    point for resolving relative deadline phrases ("Friday", "in 1 week").
    Falls back to the document's ``source_modified`` when not given.
    """
    modified = document.source_modified if document else None
    anchor = parse_anchor(anchor_date or modified)
    if item.features.signals:
        signals: list[AttentionSignal] = [
            _signal_from_draft(
                draft, item, note_id=note_id, modified=modified, anchor=anchor
            )
            for draft in item.features.signals
        ]
    else:
        signals = _extract_regex_signals(
            item, note_id=note_id, modified=modified, anchor=anchor, max_lines=max_lines
        )

    if modified and _is_recent(modified):
        title = f"Recently Updated: {_truncate(item.chunk.doc_title, 80)}"
        signals.append(
            AttentionSignal(
                id=_signal_id("recent_change", item.chunk.id, modified),
                kind="recent_change",
                title=title,
                summary=f"{item.chunk.doc_title} was updated recently.",
                severity=35,
                status="informational",
                source_note_ids=[note_id],
                source_chunk_ids=[item.chunk.id],
                created_or_updated_at=modified,
            )
        )
    return signals


def _signal_from_draft(
    draft: ChunkSignalDraft,
    item: EnrichedChunk,
    *,
    note_id: str,
    modified: str | None,
    anchor: date | None = None,
) -> AttentionSignal:
    due_date = draft.due_date or resolve_deadline(draft.due_text, anchor)
    severity = draft.severity
    if draft.status != "resolved":
        severity = min(100, severity + _deadline_boost(due_date))
    return AttentionSignal(
        id=_signal_id(draft.kind, item.chunk.id, draft.title + draft.summary),
        kind=draft.kind,
        title=_title_for(draft.kind, draft.title),
        summary=_summary_for(draft.summary),
        severity=severity,
        status=draft.status,
        owner=draft.owner,
        due_text=draft.due_text,
        due_date=due_date,
        source_note_ids=[note_id],
        source_chunk_ids=[item.chunk.id],
        created_or_updated_at=modified,
    )


def _deadline_boost(due_date: str | None, *, today: date | None = None) -> int:
    """Compile-time severity bump for deadline proximity. A snapshot — it goes
    stale as wall-clock time passes; read-time urgency buckets live in the
    /api/action-items route, which recomputes against today on every request."""
    if not due_date:
        return 0
    due = parse_anchor(due_date)
    if due is None:
        return 0
    now = today or datetime.now(timezone.utc).date()
    if due < now:
        return 25
    if (due - now).days <= 7:
        return 15
    return 0


def _extract_regex_signals(
    item: EnrichedChunk,
    *,
    note_id: str,
    modified: str | None,
    anchor: date | None = None,
    max_lines: int,
) -> list[AttentionSignal]:
    signals: list[AttentionSignal] = []
    for line in _candidate_lines(item.chunk.content)[:max_lines]:
        owner = _owner_from_line(line)
        kind = _kind_for_line(line)
        if kind is None and owner:
            kind = "owner"
        if kind is None:
            continue
        status = "resolved" if _RESOLVED_RE.search(line) else "open"
        severity = _severity_for(kind, line, status)
        due_date = resolve_deadline(line, anchor) if kind == "todo" else None
        if due_date and status != "resolved":
            severity = min(100, severity + _deadline_boost(due_date))
        title = _title_for(kind, line)
        summary = _summary_for(line)
        signals.append(
            AttentionSignal(
                id=_signal_id(kind, item.chunk.id, line),
                kind=kind,
                title=title,
                summary=summary,
                severity=severity,
                status=status,
                owner=owner,
                due_date=due_date,
                source_note_ids=[note_id],
                source_chunk_ids=[item.chunk.id],
                created_or_updated_at=modified,
            )
        )
    return signals


def aggregate_attention(
    signals: Iterable[AttentionSignal],
    *,
    limit: int = 12,
    context_count: int | None = None,
) -> tuple[list[AttentionSignal], float, AttentionLevel]:
    grouped: dict[tuple[str, str], AttentionSignal] = {}
    for signal in signals:
        key = (signal.kind, _norm(signal.title))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = signal.model_copy(deep=True)
            continue
        existing.severity = max(existing.severity, signal.severity)
        existing.source_note_ids = sorted(
            set(existing.source_note_ids) | set(signal.source_note_ids)
        )
        existing.source_chunk_ids = sorted(
            set(existing.source_chunk_ids) | set(signal.source_chunk_ids)
        )
        if not existing.owner and signal.owner:
            existing.owner = signal.owner
        if signal.due_date and (
            existing.due_date is None or signal.due_date < existing.due_date
        ):
            # Earliest deadline wins — the merged signal is due when its most
            # urgent occurrence is.
            existing.due_date = signal.due_date
            existing.due_text = signal.due_text
        if not existing.created_or_updated_at:
            existing.created_or_updated_at = signal.created_or_updated_at

    ordered = sorted(
        grouped.values(),
        key=lambda s: (
            _kind_rank(s.kind),
            s.status == "resolved",
            -s.severity,
            s.title.lower(),
        ),
    )
    trimmed = _diverse_trim(ordered, limit)
    score = attention_score(trimmed, context_count=context_count)
    return trimmed, score, attention_level(score)


def attention_score(
    signals: Iterable[AttentionSignal],
    *,
    context_count: int | None = None,
    cap: bool = True,
) -> float:
    signal_list = list(signals)
    weights = {
        "risk": 0.48,
        "todo": 0.34,
        "open_question": 0.24,
        "decision": 0.12,
        "recent_change": 0.10,
        "owner": 0.06,
    }
    by_kind: dict[str, list[int]] = defaultdict(list)
    for signal in signal_list:
        if signal.status == "resolved":
            continue
        by_kind[signal.kind].append(signal.severity)
    score = 0.0
    for kind, severities in by_kind.items():
        severities.sort(reverse=True)
        for i, severity in enumerate(severities[:5]):
            score += severity * weights.get(kind, 0.1) / (1 + i * 0.65)
    if context_count and context_count > 0:
        source_chunks = {
            chunk_id
            for signal in signal_list
            if signal.status != "resolved"
            for chunk_id in signal.source_chunk_ids
        }
        density = len(source_chunks) / context_count
        # Keep dense/small regions unchanged. In large regions, a handful of
        # severe signals should surface but not turn the entire area critical.
        density_factor = min(1.0, max(0.35, density ** 0.5))
        score *= density_factor
    if not cap:
        # Raw, uncapped score — for corpus-relative calibration, where the
        # 0–100 clamp would otherwise flatten every busy region to the same
        # value and destroy the very spread the ramp needs.
        return round(score, 2)
    return round(min(100.0, score), 2)


def calibrate_attention(
    raw_by_id: dict[str, float],
) -> dict[str, tuple[float, "AttentionLevel"]]:
    """Normalize a corpus of raw attention scores to 0–100 + levels.

    The per-region ``attention_score`` saturates: a region with a handful of
    risks and todos clears 100 on the raw sum alone, so most regions clamp to
    "critical" and the height/color ramp carries no information. Dividing by a
    single reference is not enough — a corpus where every region is busy stays
    uniformly high. Instead we stretch the corpus's actual range onto 0–100
    using robust bounds (the 10th–90th percentile, so a lone mega-region or a
    dead one doesn't compress everyone else), then bucket with thresholds tuned
    so "critical" is the top slice, not the majority.
    """
    positives = [value for value in raw_by_id.values() if value > 0]
    if not positives:
        return {key: (0.0, "none") for key in raw_by_id}
    low = _percentile(positives, 10.0)
    high = _percentile(positives, 90.0)
    span = high - low
    calibrated: dict[str, tuple[float, AttentionLevel]] = {}
    for key, value in raw_by_id.items():
        if value <= 0:
            calibrated[key] = (0.0, "none")
            continue
        if span < 1e-6:
            # No spread in the corpus — every region is equally busy. Don't
            # manufacture fake differentiation; place them all at "high".
            normalized = 65.0
        else:
            normalized = max(0.0, min(100.0, 100.0 * (value - low) / span))
        calibrated[key] = (round(normalized, 2), attention_level(normalized))
    return calibrated


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (no numpy dependency here)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def attention_level(score: float) -> AttentionLevel:
    if score >= 80:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def signals_digest(signals: Iterable[AttentionSignal], *, limit: int = 5) -> list[str]:
    out: list[str] = []
    for signal in list(signals)[:limit]:
        owner = f" owner={signal.owner}" if signal.owner else ""
        out.append(
            f"{signal.kind}: {signal.title} ({signal.status}, severity {signal.severity}{owner})"
        )
    return out


def signals_cache_lines(signals: Iterable[AttentionSignal], *, limit: int = 5) -> list[str]:
    """Like ``signals_digest`` but without ``severity``. Severity carries the
    compile-time deadline boost (a function of *today*), so keying a cache on
    it would miss whenever a due date crosses the 7-day line — with no change
    to any document. Use this for cache keys; ``signals_digest`` for prompts."""
    out: list[str] = []
    for signal in list(signals)[:limit]:
        owner = f" owner={signal.owner}" if signal.owner else ""
        out.append(f"{signal.kind}: {signal.title} ({signal.status}{owner})")
    return out


def _candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip(" -*\t")
        if len(line) < 10:
            continue
        if line.startswith("|") and line.endswith("|"):
            continue
        if len(line) > 360:
            parts = re.split(r"(?<=[.!?])\s+", line)
            lines.extend(p.strip() for p in parts if len(p.strip()) >= 10)
        else:
            lines.append(line)
    return lines


def _kind_for_line(line: str) -> AttentionSignalKind | None:
    if _NAME_TO_RE.search(line):
        return "todo"
    if line.endswith("?") or _OPEN_Q_RE.search(line):
        return "open_question"
    if _RISK_RE.search(line):
        return "risk"
    if _ACTION_RE.search(line):
        return "todo"
    if _DECISION_RE.search(line):
        return "decision"
    return None


def _owner_from_line(line: str) -> str | None:
    m = _OWNER_RE.search(line)
    if m:
        return m.group(1).strip(" .,:;")
    m = _NAME_TO_RE.search(line)
    if m:
        return m.group(1).strip()
    return None


def _severity_for(kind: AttentionSignalKind, line: str, status: str) -> int:
    base = {
        "risk": 70,
        "todo": 55,
        "open_question": 50,
        "decision": 35,
        "owner": 25,
        "recent_change": 35,
    }[kind]
    if _URGENT_RE.search(line):
        base += 18
    if status == "resolved":
        base -= 25
    if "customer" in line.lower() or "contract" in line.lower():
        base += 6
    return max(0, min(100, base))


def _truncate(text: str, limit: int) -> str:
    """Truncate to `limit` chars on a word boundary, marking cut text with '…'."""
    if len(text) <= limit:
        return text
    head = text[:limit].rstrip(' .,;:')
    # Back off to the last whitespace so we never sever a word mid-token.
    cut = head.rfind(' ')
    if cut > 0:
        head = head[:cut]
    return f"{head}…"


def _title_for(kind: AttentionSignalKind, line: str) -> str:
    clean = re.sub(r"^\s*(?:>+\s*)*(?:[-*]|\d+[.)])?\s*", "", line).strip()
    # Markdown emphasis/code markers read as noise in a one-line label.
    clean = re.sub(r"[*_`]+", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    prefix = {
        "todo": "Todo",
        "risk": "Risk",
        "decision": "Decision",
        "open_question": "Open Question",
        "owner": "Owner",
        "recent_change": "Recent Change",
    }[kind]
    return f"{prefix}: {_truncate(clean, 96)}"


def _summary_for(line: str) -> str:
    clean = re.sub(r"^\s*(?:>+\s*)+", "", line)
    clean = re.sub(r"\s+", " ", clean).strip()
    return _truncate(clean, 300)


def _signal_id(kind: str, chunk_id: str, text: str) -> str:
    return f"signal.{kind}.{short_hash(f'{kind}|{chunk_id}|{text}', 12)}"


def _kind_rank(kind: str) -> int:
    return {
        "risk": 0,
        "todo": 1,
        "open_question": 2,
        "decision": 3,
        "owner": 4,
        "recent_change": 5,
    }.get(kind, 9)


def _diverse_trim(signals: list[AttentionSignal], limit: int) -> list[AttentionSignal]:
    if len(signals) <= limit:
        return signals
    selected: list[AttentionSignal] = []
    selected_ids: set[str] = set()
    per_kind_floor = {
        "risk": 4,
        "todo": 3,
        "open_question": 2,
        "decision": 2,
        "owner": 1,
        "recent_change": 1,
    }
    for kind, count in per_kind_floor.items():
        for signal in [s for s in signals if s.kind == kind][:count]:
            if len(selected) >= limit:
                return selected
            selected.append(signal)
            selected_ids.add(signal.id)
    for signal in signals:
        if len(selected) >= limit:
            break
        if signal.id in selected_ids:
            continue
        selected.append(signal)
        selected_ids.add(signal.id)
    return selected


def _norm(value: str) -> str:
    return re.sub(r"\W+", " ", value.lower()).strip()


def _is_recent(value: str) -> bool:
    try:
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return 0 <= age_days <= 30
