from __future__ import annotations

from datetime import date

from src.terrain.utils.attention import (
    _deadline_boost,
    aggregate_attention,
    attention_score,
    calibrate_attention,
    extract_attention_signals,
)
from src.terrain.utils.models import (
    ChunkFeatures,
    ChunkSignalDraft,
    EnrichedChunk,
    SourceDocument,
    TerrainChunk,
)


def _chunk(text: str, *, signals: list[ChunkSignalDraft] = ()) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id="c1",
            doc_id="d1",
            source_type="notion",
            source_id="n1",
            doc_title="Sitelens Review",
            content=text,
            content_hash="h1",
        ),
        features=ChunkFeatures(
            summary="Sitelens has review risks and follow-up actions.",
            products=["Sitelens"],
            customers=["Terna"],
            entities=["Giorgi"],
            tags=["review interface"],
            signals=list(signals),
        ),
        embedding=[1.0, 0.0],
    )


def test_attention_extracts_source_grounded_operational_signals():
    item = _chunk(
        "\n".join(
            [
                "- Giorgi to clarify the Terna renewal risk before Friday",
                "- Risk: review interface issues may cause losing the contract renewal",
                "- Should we expose severity score explanations to engineers?",
                "- Decision: do not use the experimental v2.4 branch",
            ]
        )
    )
    doc = SourceDocument(
        id="d1",
        source_type="notion",
        source_id="n1",
        title="Sitelens Review",
        source_modified="2026-06-10T08:00:00+00:00",
    )

    signals = extract_attention_signals(item, note_id="n-d1", document=doc)
    kinds = {s.kind for s in signals}

    assert {"todo", "risk", "open_question", "decision"} <= kinds
    assert all(s.source_note_ids == ["n-d1"] for s in signals)
    assert all(s.source_chunk_ids == ["c1"] for s in signals)
    assert any(s.owner == "Giorgi" for s in signals)


def test_attention_scoring_prioritizes_open_risks_and_todos():
    item = _chunk(
        "\n".join(
            [
                "- Risk: legal sign-off delay could block the customer contract",
                "- Erekle to send the data residency confirmation by end of week",
            ]
        )
    )
    signals = extract_attention_signals(item, note_id="n-d1")

    aggregated, score, level = aggregate_attention(signals)

    assert len(aggregated) >= 2
    assert score >= 50
    assert level in {"high", "critical"}


def test_attention_scoring_accounts_for_sparse_large_regions():
    item = _chunk(
        "\n".join(
            [
                "- Risk: legal sign-off delay could block the customer contract",
                "- Erekle to send the data residency confirmation by end of week",
            ]
        )
    )
    signals = extract_attention_signals(item, note_id="n-d1")

    _aggregated, score, level = aggregate_attention(signals, context_count=50)

    assert score < 75
    assert level != "critical"


def test_attention_score_uncapped_recovers_saturated_values():
    # A signal-dense chunk whose capped score pins at 100 must expose a larger
    # raw value when cap=False, so corpus calibration can tell regions apart.
    item = _chunk(
        "\n".join(
            [
                "- Risk: legal sign-off delay could block the customer contract",
                "- Risk: the renewal is contingent on the SLA regression being fixed",
                "- Risk: procurement is slow and the contract may be losing momentum",
                "- Erekle to send the data residency confirmation by end of week",
                "- Nino to finalize the customer onboarding before the renewal",
                "- Should we expose severity score explanations to engineers?",
            ]
        )
    )
    signals = extract_attention_signals(item, note_id="n-d1")

    capped = attention_score(signals)
    raw = attention_score(signals, cap=False)

    assert capped == 100.0
    assert raw > 100.0


def test_calibrate_attention_spreads_distribution():
    # Mirrors the saturating corpus: many regions whose raw scores all exceed
    # 100. Calibration must spread them low→critical, not leave all critical.
    raw = {
        "r1": 410.0,
        "r2": 300.0,
        "r3": 220.0,
        "r4": 180.0,
        "r5": 130.0,
        "r6": 95.0,
        "r7": 70.0,
        "r8": 60.0,
        "r9": 55.0,
        "r10": 50.0,
    }

    result = calibrate_attention(raw)

    levels = [level for _score, level in result.values()]
    critical = sum(1 for level in levels if level == "critical")
    # critical is a top slice, not the majority.
    assert critical <= len(raw) // 2
    assert len(set(levels)) >= 3  # genuine spread across the ramp
    # Order is preserved: the busiest region scores highest.
    assert result["r1"][0] >= result["r10"][0]
    assert result["r1"][1] == "critical"


def test_calibrate_attention_handles_all_zero():
    assert calibrate_attention({"a": 0.0, "b": 0.0}) == {
        "a": (0.0, "none"),
        "b": (0.0, "none"),
    }


def test_llm_drafted_signals_are_preferred_over_regex():
    # A line the regex would misclassify as a risk ("problem" bare-matches
    # even inside "Not a problem") — but when the LLM extractor has already
    # drafted a negation-aware signal for this chunk, that draft wins outright
    # and the regex pass never runs.
    item = _chunk(
        "Postgres write load increases. Modest. Calculated. Not a problem.",
        signals=[
            ChunkSignalDraft(
                kind="decision",
                title="Accept modest Postgres write load increase",
                summary="Write load increase is modest and calculated; not a problem.",
                severity=20,
                status="resolved",
                owner=None,
            )
        ],
    )

    signals = extract_attention_signals(item, note_id="n-d1")

    assert len(signals) == 1
    signal = signals[0]
    assert signal.kind == "decision"
    assert signal.status == "resolved"
    assert signal.severity == 20
    assert signal.source_note_ids == ["n-d1"]
    assert signal.source_chunk_ids == ["c1"]


def test_empty_llm_signals_falls_back_to_regex():
    # features.signals == [] (the default for local mode, and for any chunk
    # where LLM extraction failed and fell back to the local heuristic
    # extractor) must still exercise the deterministic regex path.
    item = _chunk("- Risk: legal sign-off delay could block the customer contract")

    signals = extract_attention_signals(item, note_id="n-d1")

    assert any(s.kind == "risk" for s in signals)


def test_draft_relative_due_text_resolves_against_anchor_date():
    item = _chunk(
        "Ship the harvester by end of April.",
        signals=[
            ChunkSignalDraft(
                kind="todo",
                title="Ship the harvester",
                summary="Ship the Obsidian harvester by end of April.",
                severity=50,
                due_text="by end of April",
            )
        ],
    )

    signals = extract_attention_signals(
        item, note_id="n-d1", anchor_date="2026-04-10"
    )

    assert signals[0].due_text == "by end of April"
    assert signals[0].due_date == "2026-04-30"


def test_draft_absolute_due_date_passes_through_untouched():
    item = _chunk(
        "Renewal due 2099-01-15.",
        signals=[
            ChunkSignalDraft(
                kind="todo",
                title="Handle renewal",
                summary="Renewal due 2099-01-15.",
                severity=50,
                due_text="due 2099-01-15",
                due_date="2099-01-15",
            )
        ],
    )

    signals = extract_attention_signals(item, note_id="n-d1", anchor_date="2026-04-10")

    assert signals[0].due_date == "2099-01-15"
    # Far-future deadline earns no proximity boost.
    assert signals[0].severity == 50


def test_overdue_deadline_boosts_severity():
    # 2026-04-30 is permanently in the past relative to any test run → +25.
    item = _chunk(
        "Ship it by end of April.",
        signals=[
            ChunkSignalDraft(
                kind="todo",
                title="Ship it",
                summary="Ship it by end of April.",
                severity=50,
                due_text="by end of April",
            )
        ],
    )

    signals = extract_attention_signals(item, note_id="n-d1", anchor_date="2026-04-10")

    assert signals[0].due_date == "2026-04-30"
    assert signals[0].severity == 75


def test_regex_tier_extracts_deadline_for_todo_lines():
    item = _chunk("- Need to send the renewal packet to Terna by 2026-04-30")

    signals = extract_attention_signals(item, note_id="n-d1", anchor_date="2026-04-10")

    todos = [s for s in signals if s.kind == "todo"]
    assert todos and todos[0].due_date == "2026-04-30"


def test_deadline_boost_tiers():
    today = date(2026, 8, 10)
    assert _deadline_boost(None, today=today) == 0
    assert _deadline_boost("2026-08-01", today=today) == 25
    assert _deadline_boost("2026-08-15", today=today) == 15
    assert _deadline_boost("2026-08-17", today=today) == 15
    assert _deadline_boost("2026-09-15", today=today) == 0
    assert _deadline_boost("not-a-date", today=today) == 0


def test_aggregate_keeps_earliest_due_date():
    base = dict(
        kind="todo",
        title="Todo: ship the harvester",
        summary="Ship the harvester.",
        severity=50,
        status="open",
    )
    item_late = _chunk(
        "x",
        signals=[ChunkSignalDraft(**base, due_text="by 2099-06-30", due_date="2099-06-30")],
    )
    item_early = _chunk(
        "x",
        signals=[ChunkSignalDraft(**base, due_text="by 2099-05-01", due_date="2099-05-01")],
    )
    signals = extract_attention_signals(
        item_late, note_id="n-d1"
    ) + extract_attention_signals(item_early, note_id="n-d2")

    aggregated, _score, _level = aggregate_attention(signals)

    assert len(aggregated) == 1
    assert aggregated[0].due_date == "2099-05-01"
    assert aggregated[0].due_text == "by 2099-05-01"
