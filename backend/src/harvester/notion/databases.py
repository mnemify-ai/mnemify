"""Database extraction from Notion.

Handles:
- Discovering all accessible databases
- Fetching database schema (property definitions)
- Querying database rows with their resolved property values

Usage:
    async with NotionClient(token="...") as client:
        extractor = DatabaseExtractor(client)

        # List all databases
        databases = await extractor.list_databases()

        # Get rows from a specific database
        rows = await extractor.query_database("database_id_here")
"""

from __future__ import annotations

import logging
from datetime import datetime

from .client import NotionClient
from .models import NotionDatabase, NotionDatabaseRow

logger = logging.getLogger(__name__)


class DatabaseExtractor:
    """Extracts databases and their rows from Notion."""

    def __init__(self, client: NotionClient):
        """Initialize the database extractor with a Notion client."""
        self.client = client

    # ── Database discovery ─────────────────────────────────────────

    async def list_databases(self) -> list[NotionDatabase]:
        """List accessible data sources visible to the integration.

        Notion API ≥ 2025-09-03 replaced the ``database`` search filter with
        ``data_source``. A database is now a container holding one or more
        data sources; each data source has its own id, schema, and rows. We
        harvest at the data-source granularity, so ``database_id`` on
        :class:`NotionDatabase` stores a data_source_id.
        """
        raw_results = await self.client.paginate(
            "POST",
            "/search",
            body={"filter": {"property": "object", "value": "data_source"}},
        )

        databases = []
        for raw in raw_results:
            if raw.get("archived", False) or raw.get("in_trash", False):
                continue
            databases.append(self._parse_database(raw))

        logger.info(f"Found {len(databases)} data sources")
        return databases

    async def get_database(self, database_id: str) -> NotionDatabase:
        """Fetch metadata and schema for a single data source."""
        raw = await self.client.get(f"/data_sources/{database_id}")
        return self._parse_database(raw)

    # ── Row querying ───────────────────────────────────────────────

    async def query_database(
        self,
        database_id: str,
        filter_obj: dict | None = None,
        sorts: list[dict] | None = None,
    ) -> list[NotionDatabaseRow]:
        """Query rows from a database and return resolved row models."""
        body: dict = {}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        raw_results = await self.client.paginate(
            "POST",
            f"/data_sources/{database_id}/query",
            body=body,
        )

        rows = []
        for raw in raw_results:
            rows.append(self._parse_row(raw))

        logger.info(f"Queried {len(rows)} rows from database {database_id}")
        return rows

    # ── Property resolution ────────────────────────────────────────

    def resolve_properties(self, raw_properties: dict) -> dict:
        """Flatten a Notion property map into simpler Python values."""
        resolved = {}
        for name, prop in raw_properties.items():
            resolved[name] = self._resolve_single_property(prop)
        return resolved

    def _resolve_single_property(self, prop: dict) -> str | list | float | bool | None:
        """Flatten one Notion property object into a simple Python value."""
        prop_type = prop.get("type", "")

        if prop_type == "title":
            return self._extract_text(prop.get("title", []))

        if prop_type == "rich_text":
            return self._extract_text(prop.get("rich_text", []))

        if prop_type == "number":
            return prop.get("number")

        if prop_type == "select":
            select = prop.get("select")
            return select.get("name", "") if select else None

        if prop_type == "multi_select":
            return [s.get("name", "") for s in prop.get("multi_select", [])]

        if prop_type == "status":
            status = prop.get("status")
            return status.get("name", "") if status else None

        if prop_type == "date":
            date = prop.get("date")
            if not date:
                return None
            start = date.get("start", "")
            end = date.get("end")
            return f"{start} → {end}" if end else start

        if prop_type == "checkbox":
            return prop.get("checkbox", False)

        if prop_type == "url":
            return prop.get("url")

        if prop_type == "email":
            return prop.get("email")

        if prop_type == "phone_number":
            return prop.get("phone_number")

        if prop_type == "people":
            people = prop.get("people", [])
            return [p.get("name", p.get("id", "unknown")) for p in people]

        if prop_type == "relation":
            relations = prop.get("relation", [])
            return [r.get("id", "") for r in relations]

        if prop_type == "rollup":
            rollup = prop.get("rollup", {})
            rollup_type = rollup.get("type", "")
            if rollup_type == "number":
                return rollup.get("number")
            if rollup_type == "array":
                return [self._resolve_single_property(item) for item in rollup.get("array", [])]
            return str(rollup)

        if prop_type == "formula":
            formula = prop.get("formula", {})
            formula_type = formula.get("type", "")
            return formula.get(formula_type)

        if prop_type in ("created_time", "last_edited_time"):
            return prop.get(prop_type, "")

        if prop_type in ("created_by", "last_edited_by"):
            user = prop.get(prop_type, {})
            return user.get("name", user.get("id", ""))

        if prop_type == "files":
            files = prop.get("files", [])
            return [f.get("name", f.get("file", {}).get("url", "")) for f in files]

        if prop_type == "unique_id":
            uid = prop.get("unique_id", {})
            prefix = uid.get("prefix", "")
            number = uid.get("number", "")
            return f"{prefix}-{number}" if prefix else str(number)

        # Fallback for unknown types
        return f"[{prop_type}]"

    # ── Serialization ──────────────────────────────────────────────

    def database_to_dict(self, db: NotionDatabase) -> dict:
        """Serialize a database model into a JSON-compatible dictionary."""
        return {
            "database_id": db.database_id,
            "title": db.title,
            "url": db.url,
            "created_at": db.created_at.isoformat() if db.created_at else None,
            "modified_at": db.modified_at.isoformat() if db.modified_at else None,
            "parent_type": db.parent_type,
            "parent_id": db.parent_id,
            "properties_schema": {
                name: {"type": p.get("type", ""), "name": name}
                for name, p in db.properties_schema.items()
            },
        }

    def rows_to_dicts(self, rows: list[NotionDatabaseRow]) -> list[dict]:
        """Serialize row models into JSON-compatible dictionaries."""
        return [
            {
                "page_id": row.page_id,
                "title": row.title,
                "url": row.url,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "modified_at": row.modified_at.isoformat() if row.modified_at else None,
                "properties": row.properties,
            }
            for row in rows
        ]

    # ── Internal parsing ───────────────────────────────────────────

    def _parse_database(self, raw: dict) -> NotionDatabase:
        """Convert a raw Notion database payload into a NotionDatabase model."""
        title_parts = raw.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)

        parent = raw.get("parent", {})
        parent_type = parent.get("type", "")
        parent_id = parent.get(parent_type, "") if parent_type != "workspace" else "workspace"

        return NotionDatabase(
            database_id=raw["id"],
            title=title or "Untitled Database",
            url=raw.get("url", ""),
            created_at=self._parse_dt(raw.get("created_time")),
            modified_at=self._parse_dt(raw.get("last_edited_time")),
            properties_schema=raw.get("properties", {}),
            parent_type=parent_type,
            parent_id=str(parent_id),
        )

    def _parse_row(self, raw: dict) -> NotionDatabaseRow:
        """Convert a raw database query result into a NotionDatabaseRow model."""
        raw_props = raw.get("properties", {})
        title = self._extract_title_from_props(raw_props)
        resolved = self.resolve_properties(raw_props)

        return NotionDatabaseRow(
            page_id=raw["id"],
            title=title,
            url=raw.get("url", ""),
            properties=resolved,
            created_at=self._parse_dt(raw.get("created_time")),
            modified_at=self._parse_dt(raw.get("last_edited_time")),
        )

    @staticmethod
    def _extract_title_from_props(properties: dict) -> str:
        """Extract the title value from a row property map."""
        for prop in properties.values():
            if prop.get("type") == "title":
                return "".join(t.get("plain_text", "") for t in prop.get("title", []))
        return "Untitled"

    @staticmethod
    def _extract_text(rich_text: list[dict]) -> str:
        """Flatten a rich_text array into one plain string."""
        return "".join(t.get("plain_text", "") for t in rich_text)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """Parse a Notion timestamp into a datetime when possible."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
