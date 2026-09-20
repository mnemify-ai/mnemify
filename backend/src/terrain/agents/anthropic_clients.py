"""Anthropic API backends for terrain (``ai_mode="anthropic"``).

Mirrors :mod:`claude_clients`: the OpenAI extractor/namer *prompt building and
logic* are reused wholesale and only the transport is swapped — a small shim
fulfils the one contract the OpenAI classes call
(``self._client().responses.parse(model=, input=, text_format=)`` returning
``.output_parsed``, plus ``responses.create`` returning ``.output_text``) with
Anthropic Messages API calls (``client.messages.parse`` structured outputs).

Unlike ``ai_mode="claude"`` (the locally-installed `claude` CLI, subscription
auth), this is a metered API path keyed by ``ANTHROPIC_API_KEY`` — the right
choice for servers with no CLI login (Windows boxes, headless deploys, CI).

Embeddings are OpenAI (``OpenAIEmbeddingClient``, needs ``OPENAI_API_KEY``) or
the on-device bge-small (``utils/local_embedder.py``, no key) — Anthropic has
no embeddings API.
Caches are kept separate from the OpenAI/claude paths via a backend tag in the
feature cache key and an ``an_`` prefix on name fingerprints.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from types import SimpleNamespace

from src.terrain.agents.openai_clients import (
    OpenAIClusterNamer,
    OpenAIFeatureExtractor,
)
from src.terrain.agents.usage import effort_for, ledger
from src.terrain.preprocessing.extractor import (
    SCHEMA_VERSION,
    products_schema_suffix,
)

logger = logging.getLogger(__name__)


# Per-step model aliases shared with claude (CLI) mode — the settings UI offers
# the same opus/sonnet/haiku split for both transports. The CLI resolves the
# aliases itself; the API needs exact model ids, mapped here.
ALIAS_TO_MODEL = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}

# Same split rationale as claude mode: Sonnet for the high-volume per-chunk
# extraction step, Opus for the user-facing region/topic naming + notes.
DEFAULT_ANTHROPIC_EXTRACT_MODEL = "sonnet"
DEFAULT_ANTHROPIC_NAMER_MODEL = "opus"

# Non-streaming ceiling — large enough for a full extraction batch, small
# enough to stay under SDK HTTP timeouts without streaming.
_MAX_TOKENS = 16000


# Reverse map so a full id and its alias share one cache namespace — the UI
# now stores full ids ("claude-sonnet-5") where it used to store "sonnet", and
# that switch must not invalidate every cached chunk feature.
MODEL_TO_ALIAS = {v: k for k, v in ALIAS_TO_MODEL.items()}

# What the settings/build APIs accept for a Claude model: a known alias or an
# Anthropic model id (``claude-…``). Both the CLI and the API path take either.
CLAUDE_MODEL_PATTERN = r"^(opus|sonnet|haiku|claude-[a-z0-9][a-z0-9.-]*)$"
_CLAUDE_MODEL_RE = re.compile(CLAUDE_MODEL_PATTERN)


def is_claude_model_ref(value: object) -> bool:
    """True for an alias or ``claude-…`` id short enough for the settings file."""
    return isinstance(value, str) and len(value) <= 100 and bool(_CLAUDE_MODEL_RE.match(value))


def resolve_model(model: str | None, default: str) -> str:
    """Alias → concrete Anthropic model id; a concrete id passes through."""
    alias = model or default
    return ALIAS_TO_MODEL.get(alias, alias)


def cache_model_tag(model: str | None, default: str) -> str:
    """Cache namespace for the claude-CLI path, whose existing entries are keyed
    by alias: map a full id back to its alias so ``"claude-sonnet-5"`` keeps
    hitting the features ``"sonnet"`` already extracted."""
    resolved = resolve_model(model, default)
    return MODEL_TO_ALIAS.get(resolved, resolved)


# One process-wide client: the SDK client is thread-safe and pools connections,
# so sharing it across the enrich/derive thread pools mirrors OpenAIClientMixin.
_client = None
_client_lock = threading.Lock()


def _anthropic_client():
    global _client
    if _client is not None:
        return _client
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required for terrain anthropic mode.")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError(
            "Install backend dependencies (anthropic) to use terrain anthropic mode."
        ) from e
    with _client_lock:
        if _client is None:
            _client = Anthropic()
    return _client


def _split_messages(input) -> tuple[str | None, str]:  # noqa: A002 (mirror OpenAI kw)
    system = next((m["content"] for m in input if m.get("role") == "system"), None)
    user = next((m["content"] for m in input if m.get("role") == "user"), "")
    return system, user


def _effort_kwargs(reasoning) -> dict:
    """OpenAI-style ``reasoning={"effort": ...}`` → Anthropic ``output_config``.
    Omitted when unset so the provider default (adaptive thinking) applies."""
    e = effort_for("anthropic", (reasoning or {}).get("effort") if isinstance(reasoning, dict) else None)
    return {"output_config": {"effort": e}} if e else {}


class _AnthropicResponsesShim:
    """Fulfils the OpenAI ``responses.parse(...)`` + ``responses.create(...)``
    contract via the Anthropic Messages API. Errors propagate — the compile is
    fail-loud by design (no silent heuristic fallback; see compiler._name_jobs
    and the extractor's skip-then-abort threshold)."""

    def parse(self, *, model, input, text_format, reasoning=None, **_kwargs):  # noqa: A002
        system, user = _split_messages(input)
        extra = {"system": system} if system else {}
        extra.update(_effort_kwargs(reasoning))
        resolved = resolve_model(model, DEFAULT_ANTHROPIC_NAMER_MODEL)
        started = time.monotonic()
        response = _anthropic_client().messages.parse(
            model=resolved,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": user}],
            output_format=text_format,
            **extra,
        )
        ledger.record_anthropic(
            getattr(response, "usage", None), model=resolved,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return SimpleNamespace(output_parsed=response.parsed_output)

    def create(self, *, input, model=None, reasoning=None, **_kwargs):  # noqa: A002
        """Plain-text completion (used by the region merger via ``output_text``)."""
        system, user = _split_messages(input)
        extra = {"system": system} if system else {}
        extra.update(_effort_kwargs(reasoning))
        resolved = resolve_model(model, DEFAULT_ANTHROPIC_NAMER_MODEL)
        started = time.monotonic()
        response = _anthropic_client().messages.create(
            model=resolved,
            max_tokens=2048,
            messages=[{"role": "user", "content": user}],
            **extra,
        )
        ledger.record_anthropic(
            getattr(response, "usage", None), model=resolved,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return SimpleNamespace(output_text=text)


class _AnthropicClientShim:
    responses = _AnthropicResponsesShim()


class AnthropicFeatureExtractor(OpenAIFeatureExtractor):
    """Feature extraction via the Anthropic API. Inherits the OpenAI prompt +
    ``ChunkFeatures`` mapping; only the transport and cache tag change."""

    def __init__(
        self,
        model: str = DEFAULT_ANTHROPIC_EXTRACT_MODEL,
        products=(),
        *,
        cache_products=(),
        effort: str | None = None,
    ):
        super().__init__(
            model=model, products=products, cache_products=cache_products, effort=effort
        )

    def _client(self):
        return _AnthropicClientShim()

    @property
    def schema_version(self) -> str:
        # Backend + model tag so anthropic-extracted features never collide with
        # the OpenAI or claude-CLI entries in the per-chunk feature cache.
        # Keyed by the resolved id, so "sonnet" and "claude-sonnet-5" share it.
        resolved = resolve_model(self.model, DEFAULT_ANTHROPIC_EXTRACT_MODEL)
        return f"anthropic-{resolved}:{SCHEMA_VERSION}{products_schema_suffix(self.cache_products)}"


class AnthropicClusterNamer(OpenAIClusterNamer):
    """Naming + compiled-note synthesis via the Anthropic API. Inherits the
    OpenAI prompts; routes the model call through the shim. Name caches are
    namespaced away from the OpenAI and claude-CLI ones."""

    def __init__(
        self, store, model: str = DEFAULT_ANTHROPIC_NAMER_MODEL, *, effort: str | None = None
    ):
        super().__init__(store, model=model, effort=effort)

    def _client(self):
        return _AnthropicClientShim()

    def _fingerprint(self, *args, **kwargs) -> str:
        return "an_" + super()._fingerprint(*args, **kwargs)
