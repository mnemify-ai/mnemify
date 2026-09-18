"""``/api/secrets`` — set, clear and test the keys the server itself uses.

Everything Mnemify needs must be settable from the UI, so no user ever has to
find and edit a dotfile. This router is that surface for the *server-side*
credentials: the AI keys and the two connector tokens whose wizards already
write to the same place.

Three rules hold everywhere below:

* **Allowlist only.** ``SECRET_ALLOWLIST`` is the complete set of names this
  endpoint will read or write. An arbitrary ``PUT /api/secrets/PATH`` cannot
  turn the config file into a general-purpose environment editor.
* **Values go in, never out.** ``GET`` returns ``set`` plus a masked
  ``hint`` (``"…k3Fq"``). No response body, log line or error message here
  ever contains a key.
* **Storage is delegated.** ``credential_store`` owns the atomic ``0600``
  write and the ``os.environ`` refresh, so a key saved here is live for the
  running compile/harvest without a restart — and an OS-keychain backend
  later swaps in behind the same functions.

Mounted by ``src/api/__init__.py`` with ``prefix="/api"``; the router itself
carries no prefix, matching every other ``routes_*`` module.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import credential_store

router = APIRouter()
logger = logging.getLogger(__name__)

# How long a validation call may take before we call it a network failure.
# Short on purpose: this runs while a user watches a spinner in Settings.
_TEST_TIMEOUT_S = 10.0


class SecretSpec(BaseModel):
    label: str
    #: Shapes the input the frontend renders and the copy around it.
    kind: str  # "api_key" | "email" | "token"
    #: Who the value authenticates against. ``None`` for values that aren't
    #: provider credentials on their own (the Confluence account email).
    provider: str | None = None
    #: Whether POST /secrets/{name}/test can actually check this one.
    testable: bool = False


#: The complete set of names this endpoint will touch. Adding a row here is
#: the only way to expose a new key in the UI.
SECRET_ALLOWLIST: dict[str, SecretSpec] = {
    "OPENAI_API_KEY": SecretSpec(
        label="OpenAI API key",
        kind="api_key",
        provider="openai",
        testable=True,
    ),
    "ANTHROPIC_API_KEY": SecretSpec(
        label="Anthropic API key",
        kind="api_key",
        provider="anthropic",
        testable=True,
    ),
    "NOTION_TOKEN": SecretSpec(
        label="Notion integration token",
        kind="token",
        provider="notion",
    ),
    "CONFLUENCE_EMAIL": SecretSpec(
        label="Confluence account email",
        kind="email",
        provider="confluence",
    ),
    "CONFLUENCE_API_TOKEN": SecretSpec(
        label="Confluence API token",
        kind="token",
        provider="confluence",
    ),
}


class SecretValue(BaseModel):
    value: str = ""


def _spec_or_404(name: str) -> SecretSpec:
    spec = SECRET_ALLOWLIST.get(name)
    if spec is None:
        raise HTTPException(404, f"unknown secret: {name}")
    return spec


def _row(name: str) -> dict:
    """One ``GET /secrets`` row. The value never leaves this function."""
    spec = SECRET_ALLOWLIST[name]
    value = credential_store.get_secret(name)
    return {
        "name": name,
        "label": spec.label,
        "kind": spec.kind,
        "provider": spec.provider,
        "testable": spec.testable,
        "set": value is not None,
        "hint": credential_store.mask(value) if value else None,
    }


def _clean(value: str) -> str:
    """Validate a pasted secret, or raise the 400 that explains why not.

    The non-ASCII check is the same bug class ``routes_connections``
    documents on ``_OUTBOUND_ERRORS``: copying a key out of a styled document
    can substitute smart quotes or slip in a zero-width space, and httpx then
    raises ``UnicodeEncodeError`` deep inside the request. Catching it here
    turns a 500 into "re-copy your key".
    """
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(400, "value must not be empty")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in cleaned):
        # A newline here would let ``PUT /secrets/OPENAI_API_KEY`` write a
        # second ``KEY=value`` line into .env — MNEMIFY_HOME, say — and
        # ``refresh()`` would load it into the running process. That is the
        # exact thing the allowlist exists to prevent.
        raise HTTPException(
            400, "Value contains a control character (newline?) — re-copy it."
        )
    if not cleaned.isascii():
        raise HTTPException(
            400,
            "Value contains a non-ASCII character — re-copy it "
            "(watch for smart quotes / hidden whitespace).",
        )
    return cleaned


# ─── read ───────────────────────────────────────────────────────────

@router.get("/secrets")
async def list_secrets() -> list[dict]:
    """GET /api/secrets — allowlist status. Never includes a value."""
    credential_store.refresh()
    return [_row(name) for name in SECRET_ALLOWLIST]


# ─── write ──────────────────────────────────────────────────────────

@router.put("/secrets/{name}")
async def put_secret(name: str, body: SecretValue) -> dict:
    """PUT /api/secrets/{name} — save one key, return its (masked) row."""
    if name not in SECRET_ALLOWLIST:
        # 400, not 404: the path is well-formed, the *name* is not something
        # this endpoint is willing to write.
        raise HTTPException(400, f"not a settable secret: {name}")
    value = _clean(body.value)
    credential_store.save_secret(name, value)
    logger.info("secret saved: %s", name)  # name only — never the value
    return _row(name)


@router.delete("/secrets/{name}", status_code=204)
async def delete_secret(name: str) -> None:
    """DELETE /api/secrets/{name} — forget one key. Idempotent."""
    _spec_or_404(name)
    credential_store.delete_secrets([name])
    logger.info("secret deleted: %s", name)


# ─── test ───────────────────────────────────────────────────────────

@router.post("/secrets/{name}/test")
async def test_secret(name: str, body: SecretValue | None = None) -> dict:
    """POST /api/secrets/{name}/test — is this key actually usable?

    Body may carry ``{value}`` to check a key the user has typed but not
    saved; otherwise the stored key is used. The cheapest authenticated call
    each provider offers is a model list.

    A bad key is a **200 with ``ok: false``**, never a 500 — "your key was
    rejected" is a normal answer to this question, and surfacing it as a
    server error would make the UI show a crash where it should show a
    reason. Only a bug in Mnemify should 500 here.
    """
    spec = _spec_or_404(name)
    if not spec.testable:
        raise HTTPException(400, f"{name} is not testable")

    candidate = (body.value if body else "") or ""
    key = _clean(candidate) if candidate.strip() else credential_store.get_secret(name)
    if not key:
        return {"ok": False, "reason": "No key saved yet — paste one and save it first."}

    try:
        if name == "OPENAI_API_KEY":
            await asyncio.to_thread(_probe_openai, key)
        else:
            await asyncio.to_thread(_probe_anthropic, key)
    except _AuthRejected as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — every failure is a reason string
        logger.warning("secret test failed for %s: %s", name, exc.__class__.__name__)
        return {"ok": False, "reason": _outbound_reason(exc)}
    return {"ok": True}


class _AuthRejected(Exception):
    """The provider answered, and said no. Carries a user-facing reason."""


def _probe_openai(key: str) -> None:
    """One authenticated GET /v1/models. Runs in a worker thread.

    The OpenAI SDK is synchronous; calling it inline in an async route would
    block the event loop for up to ``_TEST_TIMEOUT_S``, stalling the harvest
    and compile SSE streams that share it.
    """
    import openai

    client = openai.OpenAI(api_key=key, timeout=_TEST_TIMEOUT_S, max_retries=0)
    try:
        client.models.list()
    except openai.AuthenticationError as exc:
        raise _AuthRejected("OpenAI rejected this key (401 unauthorized).") from exc
    except openai.PermissionDeniedError as exc:
        raise _AuthRejected(
            "OpenAI accepted the key but denied access — check the key's "
            "project and permissions."
        ) from exc
    except openai.RateLimitError as exc:
        raise _AuthRejected(
            "OpenAI rate-limited the check. The key looks valid; try again "
            "in a moment."
        ) from exc


def _probe_anthropic(key: str) -> None:
    """One authenticated GET /v1/models?limit=1. Runs in a worker thread."""
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=_TEST_TIMEOUT_S, max_retries=0)
    try:
        client.models.list(limit=1)
    except anthropic.AuthenticationError as exc:
        raise _AuthRejected("Anthropic rejected this key (401 unauthorized).") from exc
    except anthropic.PermissionDeniedError as exc:
        raise _AuthRejected(
            "Anthropic accepted the key but denied access — check the key's "
            "workspace and permissions."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise _AuthRejected(
            "Anthropic rate-limited the check. The key looks valid; try "
            "again in a moment."
        ) from exc


def _outbound_reason(exc: Exception) -> str:
    """Readable cause for a failed provider call.

    Same vocabulary as ``routes_connections._outbound_reason`` — the wizard
    and this panel should not describe the same network failure two ways.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "The provider didn't answer in time — check your network and retry."
    if isinstance(exc, httpx.TransportError):
        return f"Couldn't reach the provider: {exc.__class__.__name__}."
    if isinstance(exc, UnicodeError):
        return (
            "Key contains an unexpected character — re-copy it "
            "(watch for smart quotes / hidden whitespace)."
        )
    status = getattr(exc, "status_code", None)
    if status:
        return f"The provider returned HTTP {status}."
    return f"Couldn't verify the key: {exc.__class__.__name__}."
