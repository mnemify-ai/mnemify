"""Claude-subscription backends for terrain (``ai_mode="claude"``).

These reuse the OpenAI extractor/namer *prompt building and logic wholesale* and
only swap the transport: instead of an OpenAI ``responses.parse`` round-trip,
they route through the locally-installed `claude` CLI (subscription auth, see
:mod:`claude_cli`).

The trick is a small shim that mimics the one method the OpenAI classes call —
``self._client().responses.parse(model=, input=[messages], text_format=Schema)``
returning ``.output_parsed`` — but fulfils it with a `claude` completion +
JSON-validate. So we touch none of the (tested) OpenAI prompt code.

Failure policy: fail LOUD. There is deliberately no fallback to the local
heuristic extractor/namer here — a compile where the CLI is broken must abort
with a clear error (surfaced to the UI), not silently ship a heuristic-quality
map that looks compiled. Users who want a no-LLM build switch ``ai_mode`` to
``local`` explicitly. Transient single-call failures are still tolerated by the
caller (extract-batch bisect + the compiler's failure threshold); systemic ones
(:class:`~claude_cli.ClaudeCLIUnavailableError`) abort immediately.

Embeddings stay on OpenAI (`OpenAIEmbeddingClient`) — Claude has no embeddings
API, and embeddings are pennies. Caches are kept separate from the OpenAI path
via a backend tag in the feature cache key and a prefix on name fingerprints.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from pydantic import ValidationError

from src.terrain.agents.claude_cli import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CLAUDE_NAMER_MODEL,
    DEFAULT_TIMEOUT_S,
    ClaudeCLIError,
    ClaudeCLIUnavailableError,
    claude_json,
    claude_text,
    schema_hint,
)
from src.terrain.agents.openai_clients import (
    OpenAIClusterNamer,
    OpenAIFeatureExtractor,
)
from src.terrain.agents.usage import effort_for
from src.terrain.preprocessing.extractor import (
    SCHEMA_VERSION,
    products_schema_suffix,
)

logger = logging.getLogger(__name__)


class _ClaudeResponsesShim:
    """Fulfils the OpenAI ``responses.parse(...)`` + ``responses.create(...)``
    contract via the `claude` CLI. Errors propagate to the caller — the compile
    pipeline decides whether to skip a piece, abort, or surface the failure."""

    @staticmethod
    def _effort(reasoning) -> str | None:
        e = (reasoning or {}).get("effort") if isinstance(reasoning, dict) else None
        return effort_for("claude_cli", e)

    def create(self, *, input, model=None, reasoning=None, **_kwargs):  # noqa: A002
        """Plain-text completion mirroring OpenAI ``responses.create``. Used by
        the region merger, which reads ``.output_text``."""
        system = next((m["content"] for m in input if m.get("role") == "system"), "")
        user = next((m["content"] for m in input if m.get("role") == "user"), "")
        text = claude_text(
            user, system=system or None, model=model or DEFAULT_CLAUDE_MODEL,
            effort=self._effort(reasoning),
        )
        return SimpleNamespace(output_text=text)

    def parse(self, *, model, input, text_format, reasoning=None, **_kwargs):  # noqa: A002
        system = next((m["content"] for m in input if m.get("role") == "system"), "")
        user = next((m["content"] for m in input if m.get("role") == "user"), "")
        sys_with_hint = (system or "") + schema_hint(text_format)
        effort = self._effort(reasoning)

        # A batched extraction prompt is many chunks long and the model emits one
        # object per chunk, so generation runs proportionally longer. Scale the
        # CLI timeout off the prompt size (≈4 chars/token) so a big batch isn't
        # guillotined at the single-call default — the batch caller bisects on
        # failure, but a timeout should be a last resort, not the common case.
        timeout = max(DEFAULT_TIMEOUT_S, 60 + len(user) // 200)

        last_err: Exception | None = None
        for attempt in range(2):  # one retry; sonnet's JSON is reliable but not infallible
            try:
                obj = claude_json(
                    user, system=sys_with_hint, model=model, timeout=timeout, effort=effort
                )
                parsed = text_format.model_validate(obj)
                return SimpleNamespace(output_parsed=parsed)
            except ClaudeCLIUnavailableError:
                raise  # systemic — retrying cannot help, abort the build fast
            except (ClaudeCLIError, ValidationError) as e:
                last_err = e
                sys_with_hint = (
                    (system or "")
                    + "\n\nYour previous reply was invalid. "
                    + schema_hint(text_format)
                )
        raise ClaudeCLIError(f"claude structured parse failed: {last_err}")


class _ClaudeClientShim:
    responses = _ClaudeResponsesShim()


class ClaudeFeatureExtractor(OpenAIFeatureExtractor):
    """Feature extraction via Claude subscription. Inherits the OpenAI prompt +
    ``ChunkFeatures`` mapping; only the transport and cache tag change. No
    heuristic fallback: a failed chunk is skipped (and counted) by the caller,
    and a systemic CLI failure aborts the build."""

    def __init__(
        self, model: str = DEFAULT_CLAUDE_MODEL, products=(), *,
        cache_products=(), effort: str | None = None,
    ):
        super().__init__(
            model=model, products=products, cache_products=cache_products, effort=effort
        )

    def _client(self):
        return _ClaudeClientShim()

    @property
    def schema_version(self) -> str:
        # Backend + model tag so Claude- and OpenAI-extracted features never
        # collide in the per-chunk feature cache.
        from src.terrain.agents.anthropic_clients import cache_model_tag

        tag = cache_model_tag(self.model, DEFAULT_CLAUDE_MODEL)
        return f"claude-{tag}:{SCHEMA_VERSION}{products_schema_suffix(self.cache_products)}"


class ClaudeClusterNamer(OpenAIClusterNamer):
    """Naming + compiled-note synthesis via Claude subscription. Inherits the
    OpenAI prompts; routes the model call through the shim. No heuristic
    fallback: a naming failure aborts the compile with a clear error (see
    compiler._name_jobs). Name caches are namespaced away from OpenAI's."""

    def __init__(
        self, store, model: str = DEFAULT_CLAUDE_NAMER_MODEL, *, effort: str | None = None
    ):
        super().__init__(store, model=model, effort=effort)

    def _client(self):
        return _ClaudeClientShim()

    def _fingerprint(self, *args, **kwargs) -> str:
        # Separate the name cache from the OpenAI-mode cache.
        return "cl_" + super()._fingerprint(*args, **kwargs)
