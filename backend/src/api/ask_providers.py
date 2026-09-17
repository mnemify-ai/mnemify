"""LLM provider abstraction for /api/ask (Stage 5).

Anthropic streaming uses the Messages API directly via :mod:`httpx`
(no SDK dependency added). OpenAI uses the existing async client from
the ``openai`` package. Both expose the same coroutine shape:

    async def stream_chat(provider, model, key, messages, system) ->
        AsyncIterator[str]

so the route doesn't care which provider is selected.

BYOK is end-to-end: the route forwards the user's key from the
``Authorization: Bearer …`` header into this module and never persists
or logs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from src.terrain.agents.claude_cli import DEFAULT_CLAUDE_MODEL, claude_text

logger = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

_QUERY_UNDERSTANDING_SYSTEM = (
    "You convert a user's question into a compact JSON object for retrieval "
    "over a knowledge graph. Respond with ONLY a JSON object, no prose, of the "
    "exact shape:\n"
    '{"nodeTypes": string[], "mentions": string[], "topicIntent": string}\n'
    "- nodeTypes: subset of [\"entity\",\"tag\",\"region\",\"note\",\"signal\"] the question "
    "is about; [] if unsure.\n"
    "- mentions: specific named things in the question (people, products, "
    "projects, customers). Resolve paraphrases to likely proper names where "
    "obvious; [] if none.\n"
    "- topicIntent: a short (<=12 word) paraphrase of the topic, suitable for "
    "embedding-based search."
)


async def understand_query(
    provider: str,
    model: str,
    key: str,
    query: str,
    *,
    history: list[dict] | None = None,
    timeout: float = 7.0,
) -> dict | None:
    """Best-effort structured query understanding (one cheap, non-streaming
    call). Returns ``{nodeTypes, mentions, topicIntent}`` or ``None`` on any
    failure so the caller can fall back to the regex heuristic. Never raises.

    ``history`` (the last couple of chat turns) lets topicIntent resolve
    elliptical follow-ups ("what about error handling?") against the prior
    topic instead of embedding the bare pronoun."""
    user = ""
    if history:
        turns = []
        for turn in history:
            role = str(turn.get("role", "user"))
            content = str(turn.get("content", ""))[:300]
            if content:
                turns.append(f"{role}: {content}")
        if turns:
            user = "Recent conversation (for resolving follow-ups):\n" + "\n".join(turns) + "\n\n"
    user += f"Question: {query}\nReturn the JSON object."
    try:
        if provider == "anthropic":
            text = await _complete_anthropic(model, key, _QUERY_UNDERSTANDING_SYSTEM, user, timeout)
        elif provider == "openai":
            text = await _complete_openai(model, key, _QUERY_UNDERSTANDING_SYSTEM, user, timeout)
        elif provider == "claude":
            text = await asyncio.to_thread(
                claude_text, user, system=_QUERY_UNDERSTANDING_SYSTEM,
                model=model or DEFAULT_CLAUDE_MODEL, timeout=timeout,
            )
        else:
            return None
    except Exception:  # noqa: BLE001
        logger.info("ask: query understanding failed; using regex fallback", exc_info=True)
        return None

    obj = _parse_json_object(text)
    if not isinstance(obj, dict):
        return None
    return {
        "nodeTypes": [str(t) for t in obj.get("nodeTypes", []) if isinstance(t, str)],
        "mentions": [str(m) for m in obj.get("mentions", []) if str(m).strip()],
        "topicIntent": str(obj.get("topicIntent") or "").strip(),
    }


def _parse_json_object(text: str | None) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip a ```json … ``` fence if the model added one.
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _complete_anthropic(
    model: str, key: str, system: str, user: str, timeout: float
) -> str:
    payload = {
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 400,
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        resp = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


async def _complete_openai(
    model: str, key: str, system: str, user: str, timeout: float
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, timeout=timeout)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_completion_tokens=400,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


async def stream_chat(
    provider: str,
    model: str,
    key: str,
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """Stream LLM output as raw text chunks. Provider-specific transport,
    same async-iterator contract. Errors bubble as exceptions."""
    if provider == "anthropic":
        async for chunk in _stream_anthropic(model, key, messages, system, max_tokens):
            yield chunk
    elif provider == "openai":
        async for chunk in _stream_openai(model, key, messages, system, max_tokens):
            yield chunk
    elif provider == "claude":
        async for chunk in _stream_claude_cli(model, messages, system):
            yield chunk
    else:
        raise ValueError(f"unknown provider: {provider!r}")


async def _stream_claude_cli(
    model: str,
    messages: list[dict],
    system: str | None,
) -> AsyncIterator[str]:
    """Chat via the local `claude` CLI on the user's subscription (no API key).

    `claude -p` is single-shot, so we flatten the conversation into one prompt
    and yield the full answer in one chunk. (Token-level streaming via
    `--output-format stream-json` is a future upgrade; correctness first.)"""
    convo = "\n\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in messages
    )
    text = await asyncio.to_thread(
        claude_text, convo, system=system, model=model or DEFAULT_CLAUDE_MODEL
    )
    yield text


async def _stream_anthropic(
    model: str,
    key: str,
    messages: list[dict],
    system: str | None,
    max_tokens: int,
) -> AsyncIterator[str]:
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    timeout = httpx.Timeout(60.0, read=60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", ANTHROPIC_URL, headers=headers, json=payload
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"anthropic stream failed: status={response.status_code} "
                    f"body={body!r}"
                )
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    return
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    text = delta.get("text") or ""
                    if text:
                        yield text
                elif kind == "message_stop":
                    return


async def _stream_openai(
    model: str,
    key: str,
    messages: list[dict],
    system: str | None,
    max_tokens: int,
) -> AsyncIterator[str]:
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai package is required for OpenAI provider") from e

    chat_messages: list[dict] = []
    if system:
        chat_messages.append({"role": "system", "content": system})
    chat_messages.extend(messages)

    client = AsyncOpenAI(api_key=key)
    stream = await client.chat.completions.create(
        model=model,
        messages=chat_messages,
        max_completion_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            yield text
