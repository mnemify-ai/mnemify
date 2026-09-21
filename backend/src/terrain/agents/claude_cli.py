"""Headless Claude transport via the `claude` CLI — subscription auth.

This is the backbone of ``ai_mode="claude"``: instead of metered OpenAI/Anthropic
API calls, terrain's generation (feature extraction, naming, compiled notes,
and the chatbot) runs one-shot prompts through the locally-installed `claude`
binary, which authenticates against the user's logged-in Claude subscription
(e.g. Claude Max) rather than an API key.

Why the bare CLI and not the Python Agent SDK here: these are one-shot
prompts with no tool use, so the SDK's agent loop adds nothing. (The old
auth objection is stale — the SDK drives this same CLI and inherits the
subscription login; the agentic ``/api/ask`` path in ``src/api/ask_agent.py``
uses it.) We keep the invocation lean — override the system prompt and drop
setting sources, run from a neutral cwd — so each call carries no project
context (verified: ~3 input tokens of overhead vs ~2900 with defaults).

Single-user / local only: this routes *one* logged-in subscription and is not a
multi-tenant path. Production stays on BYOK (see ``ask_providers``).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile

from src.terrain.agents.usage import ledger

logger = logging.getLogger(__name__)


# Default model alias for the high-volume compile work (per-chunk feature
# extraction). Sonnet is the sweet spot here — strong JSON adherence, fast, and
# easy on subscription rate limits when extracting hundreds of chunks 8-way
# parallel. (Aliases resolve via the `claude` CLI: opus → latest Opus, etc.)
DEFAULT_CLAUDE_MODEL = "sonnet"

# Default model alias for naming + compiled-note synthesis — the region/tag
# names and the 2-3 paragraph notes the user actually reads. This is where
# model quality is most visible, so it defaults to the most capable Opus tier.
# Routing per-chunk extraction through Opus too would mostly cost speed and
# subscription rate limits for little visible gain, hence the split.
DEFAULT_CLAUDE_NAMER_MODEL = "opus"

# Generous default; speed is not a concern for batch compiles, and a cold
# `claude` start plus a large chunk can take a while.
DEFAULT_TIMEOUT_S = 300


# Per-call logging toggle. Off by default; the compile orchestrator flips it
# from the saved compile setting once, before the build's worker-thread fan-out
# (read-only during parallel calls — no lock needed). When on, every `claude`
# invocation logs which model ran + timing + token usage, pulled from the CLI's
# JSON envelope (otherwise discarded). Useful for verifying the Opus/Sonnet split.
_LOG_CALLS = False


def set_call_logging(on: bool) -> None:
    """Enable/disable per-call `claude` logging (see :data:`_LOG_CALLS`)."""
    global _LOG_CALLS
    _LOG_CALLS = bool(on)


class ClaudeCLIError(RuntimeError):
    """Raised when the `claude` CLI fails, errors, or returns no result."""


class ClaudeCLIUnavailableError(ClaudeCLIError):
    """A *systemic* CLI failure — the binary is missing, the login is broken,
    or the subscription is out of quota. Retrying other chunks cannot succeed,
    so the compiler treats this as fatal and aborts the build immediately
    instead of grinding through per-chunk failures.

    ``kind`` distinguishes the three causes so the UI can react: a
    ``usage_limit`` is *resumable* (everything extracted so far is cached;
    re-run after the window resets), ``auth`` and ``missing_cli`` need a fix.
    """

    def __init__(self, message: str, *, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind


# CLI failure messages that mean every subsequent call will fail too, and
# what each one means for the user.
_SYSTEMIC_PATTERNS: dict[str, str] = {
    "usage limit": "usage_limit",
    "rate limit": "usage_limit",
    "credit balance": "usage_limit",
    "not logged in": "auth",
    "please run /login": "auth",
    "invalid api key": "auth",
    "authentication": "auth",
    "oauth token": "auth",
}


def classify_cli_failure(detail: str) -> str | None:
    """``usage_limit`` / ``auth`` for a systemic CLI failure message, else None."""
    low = (detail or "").lower()
    for pat, kind in _SYSTEMIC_PATTERNS.items():
        if pat in low:
            return kind
    return None


def find_claude_binary() -> str | None:
    """Absolute path of the `claude` executable on PATH, or None.

    Resolved through :func:`shutil.which` rather than passing the bare name to
    ``subprocess`` so the same lookup works everywhere: on Windows the npm
    install exposes ``claude.cmd`` (which ``CreateProcess`` won't find by
    bare name — only PATHEXT-aware ``which`` does) and the native installer
    ships ``claude.exe``; on macOS/Linux it's a plain ``claude`` symlink.
    """
    return shutil.which("claude")


def claude_text(
    user_prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_CLAUDE_MODEL,
    timeout: float = DEFAULT_TIMEOUT_S,
    effort: str | None = None,
) -> str:
    """Run one headless `claude` prompt and return the assistant's text.

    ``effort`` (low/medium/high/xhigh/max) is passed as ``--effort``; None
    leaves the CLI default (its highest tiers think at length — the single
    biggest subscription-quota lever for bulk extraction).

    Uses subscription auth (whatever the logged-in `claude` CLI is configured
    with). Raises :class:`ClaudeCLIError` on non-zero exit, an error envelope,
    or empty output.
    """
    binary = find_claude_binary()
    if binary is None:
        raise ClaudeCLIUnavailableError(
            "the `claude` CLI is not installed or not on PATH — required for "
            "ai_mode='claude'",
            kind="missing_cli",
        )
    cmd = [
        binary,
        "-p",
        user_prompt,
        "--model",
        model,
        # Drop user/project/local setting sources so no CLAUDE.md, hooks, or
        # MCP config bleeds into the prompt (keeps the call lean + deterministic).
        "--setting-sources",
        "",
        "--output-format",
        "json",
    ]
    if system:
        # Override (not append) the default Claude Code agent system prompt so
        # the model behaves as a pure completion function with our instructions.
        cmd += ["--system-prompt", system]
    if effort:
        cmd += ["--effort", str(effort)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            # Neutral cwd: avoids loading the project's CLAUDE.md / .claude config.
            cwd=tempfile.gettempdir(),
        )
    except FileNotFoundError as e:
        raise ClaudeCLIUnavailableError(
            "the `claude` CLI is not installed or not on PATH — required for "
            "ai_mode='claude'",
            kind="missing_cli",
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude call timed out after {timeout}s") from e

    if proc.returncode != 0:
        # On failure (rate/usage limits, auth) the CLI often writes the reason
        # to stdout, not stderr — surface whichever is non-empty so the cause
        # isn't swallowed into a bare "exited 1".
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        message = f"claude exited {proc.returncode}: {detail[:300]}"
        kind = classify_cli_failure(detail)
        if kind:
            raise ClaudeCLIUnavailableError(message, kind=kind)
        raise ClaudeCLIError(message)

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(
            f"claude returned non-JSON envelope: {(proc.stdout or '')[:300]}"
        ) from e

    ledger.record_claude_cli(envelope, model=model)
    if _LOG_CALLS:
        logger.info(
            "claude call: model=%s duration_ms=%s usage=%s cost_usd=%s",
            envelope.get("model"),
            envelope.get("duration_ms"),
            envelope.get("usage"),
            envelope.get("total_cost_usd"),
        )

    if envelope.get("is_error"):
        raise ClaudeCLIError(f"claude reported an error: {str(envelope.get('result'))[:300]}")

    result = envelope.get("result")
    if not result or not str(result).strip():
        raise ClaudeCLIError("claude returned an empty result")
    return str(result)


def claude_json(
    user_prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_CLAUDE_MODEL,
    timeout: float = DEFAULT_TIMEOUT_S,
    effort: str | None = None,
) -> dict:
    """Run a headless `claude` prompt expected to return a JSON object, and
    parse it. Tolerates stray prose / markdown fences around the object.
    Raises :class:`ClaudeCLIError` if no JSON object can be parsed."""
    text = claude_text(user_prompt, system=system, model=model, timeout=timeout, effort=effort)
    obj = extract_json_object(text)
    if obj is None:
        raise ClaudeCLIError(f"could not parse a JSON object from: {text[:300]}")
    return obj


def extract_json_object(text: str | None) -> dict | None:
    """Best-effort: pull the first JSON object out of a model response,
    stripping ```json fences and surrounding prose."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _annotation_desc(ann, _depth: int = 0) -> str:
    """Describe one field annotation for :func:`schema_hint`, recursing into
    nested pydantic models so a wrapper like ``{items: list[ChunkFeatures]}``
    still spells out the per-item field shape (the OpenAI ``responses.parse``
    path gets this for free; the CLI path needs it spelled out or batch JSON
    quality collapses). ``_depth`` bounds recursion against pathological nesting."""
    import typing

    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        return "one of: " + " | ".join(str(a) for a in typing.get_args(ann))
    if origin in (list, set, tuple):
        inner = typing.get_args(ann)
        inner_ann = inner[0] if inner else None
        if _depth < 3 and hasattr(inner_ann, "model_fields"):
            return "array of objects, each with " + _model_desc(inner_ann, _depth + 1)
        inner_name = getattr(inner_ann, "__name__", "item") if inner_ann else "item"
        return f"array of {inner_name}"
    if _depth < 3 and hasattr(ann, "model_fields"):
        return "object with " + _model_desc(ann, _depth + 1)
    return getattr(ann, "__name__", str(ann))


def _model_desc(model_cls, _depth: int = 0) -> str:
    """Render a model's fields as ``key (desc), key (desc)`` (recursive)."""
    try:
        fields = model_cls.model_fields
    except AttributeError:
        return ""
    parts = [
        f"{name} ({_annotation_desc(field.annotation, _depth)})"
        for name, field in fields.items()
    ]
    return "keys: " + ", ".join(parts)


def schema_hint(model_cls) -> str:
    """Build a terse 'return ONLY this JSON' instruction from a pydantic model's
    fields, so a Claude completion produces output that validates against the
    same schema the OpenAI structured-output path enforces natively. Enumerates
    ``Literal`` options explicitly so constrained fields (e.g. tag_type_hint)
    don't come back out-of-enum, and recurses into nested models so batch
    wrappers carry per-item field guidance."""
    desc = _model_desc(model_cls)
    if not desc:
        return ""
    return (
        "\n\nReturn ONLY a single JSON object with these "
        + desc
        + ". No prose, no markdown fences."
    )
