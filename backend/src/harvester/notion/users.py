"""User resolution for Notion.

Caches the workspace user list and provides ID -> name lookup.

Endpoints:
  GET /users         -- list all users in the workspace
  GET /users/{id}    -- get a single user by ID
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .client import NotionClient

logger = logging.getLogger(__name__)


@dataclass
class NotionUser:
    user_id: str
    name: str
    email: str | None = None
    user_type: str = "person"
    avatar_url: str | None = None


class UserResolver:
    """Resolves Notion user IDs to names with in-memory caching."""

    def __init__(self, client: NotionClient):
        self.client = client
        self._cache: dict[str, NotionUser] = {}
        self._loaded = False

    async def load_users(self) -> None:
        raw_results = await self.client.paginate("GET", "/users")
        for raw in raw_results:
            user = self._parse_user(raw)
            self._cache[user.user_id] = user
        self._loaded = True
        logger.info(f"Loaded {len(self._cache)} workspace users")

    async def resolve(self, user_id: str) -> str:
        if not self._loaded:
            await self.load_users()
        user = self._cache.get(user_id)
        if user:
            return user.name
        try:
            raw = await self.client.get(f"/users/{user_id}")
            user = self._parse_user(raw)
            self._cache[user.user_id] = user
            return user.name
        except Exception:
            return user_id

    def resolve_sync(self, user_id: str) -> str:
        user = self._cache.get(user_id)
        return user.name if user else user_id

    def get_all_users(self) -> list[NotionUser]:
        return list(self._cache.values())

    def _parse_user(self, raw: dict) -> NotionUser:
        person = raw.get("person", {})
        return NotionUser(
            user_id=raw.get("id", ""),
            name=raw.get("name", "Unknown"),
            email=person.get("email"),
            user_type=raw.get("type", "person"),
            avatar_url=raw.get("avatar_url"),
        )
