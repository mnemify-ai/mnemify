"""Per-compile LLM usage ledger.

Every transport (OpenAI SDK, Anthropic SDK, `claude` CLI) records the token
counts of each call here, tagged with the pipeline stage the compiler is
currently running. The compiler resets the ledger at the start of ``build()``
and folds ``snapshot()`` into the run's counts + compile report, so the cost
of a compile is visible per stage instead of guessed.

Stage tagging is a process-wide value set by the build thread before each
stage's fan-out. Stages never overlap (each fan-out is joined before the
next stage starts), so worker threads inherit the right tag without any
per-thread plumbing.

Effort levels: the user-facing setting is one vocabulary
(:data:`EFFORT_LEVELS`) mapped per backend by :func:`effort_for`.
"""

from __future__ import annotations

import threading
from typing import Any

# User-facing effort vocabulary (settings + UI). ``""`` / None = provider default.
EFFORT_LEVELS = ("low", "medium", "high")

# Per-backend spelling. All three providers accept these three levels verbatim
# today; the indirection exists so a provider rename is a one-line change.
_EFFORT_BY_BACKEND: dict[str, dict[str, str]] = {
    "openai": {"low": "low", "medium": "medium", "high": "high"},
    "anthropic": {"low": "low", "medium": "medium", "high": "high"},
    "claude_cli": {"low": "low", "medium": "medium", "high": "high"},
}


def effort_for(backend: str, effort: str | None) -> str | None:
    """Provider spelling of a user-facing effort level, or None for default."""
    if not effort:
        return None
    return _EFFORT_BY_BACKEND.get(backend, {}).get(str(effort).lower())


_FIELDS = (
    "calls",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "duration_ms",
    "cost_usd",
)


class UsageLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage = "other"
        self._by_stage: dict[str, dict[str, Any]] = {}
        self._models: dict[str, set[str]] = {}

    # ── stage tagging ─────────────────────────────────────────────

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage or "other"

    @property
    def stage(self) -> str:
        return self._stage

    def reset(self) -> None:
        with self._lock:
            self._stage = "other"
            self._by_stage = {}
            self._models = {}

    # ── recording ─────────────────────────────────────────────────

    def record(
        self,
        provider: str,
        model: str | None,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        cache_write_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        duration_ms: int = 0,
        cost_usd: float = 0.0,
        stage: str | None = None,
    ) -> None:
        with self._lock:
            key = stage or self._stage
            row = self._by_stage.setdefault(key, {f: 0 for f in _FIELDS})
            row["calls"] += 1
            row["input_tokens"] += int(input_tokens or 0)
            row["cached_input_tokens"] += int(cached_input_tokens or 0)
            row["cache_write_tokens"] += int(cache_write_tokens or 0)
            row["output_tokens"] += int(output_tokens or 0)
            row["reasoning_tokens"] += int(reasoning_tokens or 0)
            row["duration_ms"] += int(duration_ms or 0)
            row["cost_usd"] = float(row["cost_usd"]) + float(cost_usd or 0.0)
            if model:
                self._models.setdefault(key, set()).add(f"{provider}:{model}")

    def record_openai(self, usage: Any, *, model: str | None, duration_ms: int = 0) -> None:
        """Record an OpenAI Responses/Chat/Embeddings ``usage`` object."""
        if usage is None:
            return
        g = _getter(usage)
        in_details = g("input_tokens_details") or g("prompt_tokens_details")
        out_details = g("output_tokens_details") or g("completion_tokens_details")
        gi, go = _getter(in_details), _getter(out_details)
        input_tokens = g("input_tokens") or g("prompt_tokens") or g("total_tokens") or 0
        self.record(
            "openai", model,
            input_tokens=input_tokens,
            cached_input_tokens=gi("cached_tokens") or 0,
            cache_write_tokens=gi("cache_write_tokens") or 0,
            output_tokens=g("output_tokens") or g("completion_tokens") or 0,
            reasoning_tokens=go("reasoning_tokens") or 0,
            duration_ms=duration_ms,
        )

    def record_anthropic(self, usage: Any, *, model: str | None, duration_ms: int = 0) -> None:
        """Record an Anthropic Messages ``usage`` object."""
        if usage is None:
            return
        g = _getter(usage)
        self.record(
            "anthropic", model,
            input_tokens=g("input_tokens") or 0,
            cached_input_tokens=g("cache_read_input_tokens") or 0,
            cache_write_tokens=g("cache_creation_input_tokens") or 0,
            output_tokens=g("output_tokens") or 0,
            duration_ms=duration_ms,
        )

    def record_claude_cli(self, envelope: dict | None, *, model: str | None) -> None:
        """Record a `claude -p --output-format json` envelope."""
        if not isinstance(envelope, dict):
            return
        u = envelope.get("usage") or {}
        if not isinstance(u, dict):
            u = {}
        self.record(
            "claude_cli", envelope.get("model") or model,
            input_tokens=u.get("input_tokens") or 0,
            cached_input_tokens=u.get("cache_read_input_tokens") or 0,
            cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
            output_tokens=u.get("output_tokens") or 0,
            duration_ms=envelope.get("duration_ms") or 0,
            cost_usd=envelope.get("total_cost_usd") or 0.0,
        )

    # ── reporting ─────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """``{"stages": {stage: {...counts, "models": [...]}}, "total": {...}}``.
        Zero-call stages are omitted; an empty ledger returns empty dicts."""
        with self._lock:
            stages: dict[str, Any] = {}
            total = {f: 0 for f in _FIELDS}
            for stage, row in self._by_stage.items():
                if not row["calls"]:
                    continue
                out = dict(row)
                out["cost_usd"] = round(float(out["cost_usd"]), 6)
                out["models"] = sorted(self._models.get(stage, ()))
                stages[stage] = out
                for f in _FIELDS:
                    total[f] += row[f]
            total["cost_usd"] = round(float(total["cost_usd"]), 6)
            return {"stages": stages, "total": total}

    def summary_line(self) -> str:
        """One human line for logs / the compile report."""
        snap = self.snapshot()
        t = snap["total"]
        if not t["calls"]:
            return "LLM usage: no calls"
        parts = [
            f"{t['calls']} calls",
            f"{t['input_tokens']:,} in",
        ]
        if t["cached_input_tokens"]:
            parts.append(f"{t['cached_input_tokens']:,} cached")
        parts.append(f"{t['output_tokens']:,} out")
        if t["reasoning_tokens"]:
            parts.append(f"{t['reasoning_tokens']:,} reasoning")
        if t["cost_usd"]:
            parts.append(f"${t['cost_usd']:.2f}")
        per_stage = ", ".join(
            f"{s}={r['calls']}" for s, r in snap["stages"].items()
        )
        return f"LLM usage: {' · '.join(parts)} ({per_stage})"


def _getter(obj: Any):
    """Uniform attribute/key access for SDK objects and plain dicts."""
    if obj is None:
        return lambda _k: None
    if isinstance(obj, dict):
        return obj.get
    return lambda k: getattr(obj, k, None)


# Process-wide ledger. The compiler is the single writer of ``set_stage`` /
# ``reset``; transports only ``record``.
ledger = UsageLedger()
