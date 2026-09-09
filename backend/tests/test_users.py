"""Unit tests for UserResolver (src/harvester/notion/users.py)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock


from src.harvester.notion.client import NotionClient
from src.harvester.notion.users import NotionUser, UserResolver

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────


def make_resolver() -> tuple[UserResolver, MagicMock]:
    mock_client = MagicMock(spec=NotionClient)
    resolver = UserResolver(mock_client)
    return resolver, mock_client


def make_raw_user(
    user_id: str = "user-1",
    name: str = "Alice Smith",
    email: str = "alice@example.com",
    user_type: str = "person",
) -> dict:
    raw: dict = {
        "id": user_id,
        "name": name,
        "type": user_type,
        "avatar_url": None,
    }
    if user_type == "person":
        raw["person"] = {"email": email}
    return raw


# ── load_users ─────────────────────────────────────────────────────


async def test_load_users_populates_cache_from_api_response():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(
        return_value=[
            make_raw_user("u-1", "Alice"),
            make_raw_user("u-2", "Bob"),
        ]
    )

    await resolver.load_users()

    assert len(resolver._cache) == 2
    assert "u-1" in resolver._cache
    assert resolver._cache["u-1"].name == "Alice"
    assert resolver._loaded is True


async def test_load_users_calls_paginate_with_users_endpoint():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(return_value=[])

    await resolver.load_users()

    mock_client.paginate.assert_called_once_with("GET", "/users")


# ── resolve ────────────────────────────────────────────────────────


async def test_resolve_returns_name_for_known_user():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(return_value=[make_raw_user("u-1", "Alice")])

    name = await resolver.resolve("u-1")

    assert name == "Alice"


async def test_resolve_returns_id_string_for_unknown_user():
    resolver, mock_client = make_resolver()
    # load_users returns empty list
    mock_client.paginate = AsyncMock(return_value=[])
    # individual lookup also fails
    mock_client.get = AsyncMock(side_effect=Exception("404 Not Found"))

    name = await resolver.resolve("unknown-id")

    assert name == "unknown-id"


async def test_individual_lookup_on_cache_miss():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(return_value=[])  # no users in bulk load
    mock_client.get = AsyncMock(return_value=make_raw_user("u-99", "Late User"))

    resolver._loaded = True  # skip load_users to test individual lookup path
    name = await resolver.resolve("u-99")

    assert name == "Late User"
    mock_client.get.assert_called_once_with("/users/u-99")


async def test_resolve_triggers_load_when_not_loaded():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(return_value=[make_raw_user("u-1", "Alice")])

    assert resolver._loaded is False
    await resolver.resolve("u-1")

    assert resolver._loaded is True
    mock_client.paginate.assert_called_once()


# ── resolve_sync ───────────────────────────────────────────────────


def test_resolve_sync_returns_from_cache_without_api_call():
    resolver, mock_client = make_resolver()
    resolver._cache["u-1"] = NotionUser(
        user_id="u-1", name="Alice", email="alice@example.com"
    )

    result = resolver.resolve_sync("u-1")

    assert result == "Alice"
    mock_client.paginate.assert_not_called()
    mock_client.get.assert_not_called()


def test_resolve_sync_returns_id_when_not_in_cache():
    resolver, _ = make_resolver()
    result = resolver.resolve_sync("nonexistent-id")
    assert result == "nonexistent-id"


# ── get_all_users / parse_user ─────────────────────────────────────


async def test_get_all_users_returns_list_from_cache():
    resolver, mock_client = make_resolver()
    mock_client.paginate = AsyncMock(
        return_value=[make_raw_user("u-1", "Alice"), make_raw_user("u-2", "Bob")]
    )

    await resolver.load_users()
    users = resolver.get_all_users()

    assert len(users) == 2
    names = {u.name for u in users}
    assert names == {"Alice", "Bob"}


def test_parse_user_handles_person_and_bot_types():
    resolver, _ = make_resolver()

    person_raw = make_raw_user("p-1", "Alice", "alice@example.com", "person")
    bot_raw = {"id": "b-1", "name": "My Bot", "type": "bot", "avatar_url": None}

    person = resolver._parse_user(person_raw)
    assert person.user_type == "person"
    assert person.email == "alice@example.com"

    bot = resolver._parse_user(bot_raw)
    assert bot.user_type == "bot"
    assert bot.email is None
    assert bot.name == "My Bot"
