from __future__ import annotations

import json
import re
from pathlib import Path

from src.harvester.manifest import HarvestManifest
from src.terrain.utils.models import SourceDocument


class TerrainReader:
    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path)

    def load(self, source: str | None = None) -> list[SourceDocument]:
        manifest = HarvestManifest(self.manifest_path)
        try:
            rows = manifest.get_documents(source_type=source, status="active")
        finally:
            manifest.close()
        return [doc for row in rows if (doc := self._document_from_row(row))]

    def _document_from_row(self, row: dict) -> SourceDocument | None:
        path = row.get("normalized_path")
        if not path and (row.get("raw_format") or "").lower() in {"md", "markdown", "txt", "text"}:
            path = row.get("raw_path")
        if path:
            # A manifest written on Windows stores backslash separators; forward
            # slashes work on every OS, so normalize before touching the FS.
            path = path.replace("\\", "/")
        if not path or not Path(path).is_file():
            return None
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        metadata = self._metadata(row.get("metadata"), text)
        return SourceDocument(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            title=row.get("title") or "Untitled",
            source_url=row.get("source_url") or metadata.get("url"),
            source_modified=row.get("source_modified"),
            normalized_path=row.get("normalized_path"),
            metadata=metadata,
            content=self._strip_frontmatter(text),
        )

    def _metadata(self, raw_metadata: str | dict | None, text: str) -> dict:
        if isinstance(raw_metadata, dict):
            metadata = dict(raw_metadata)
        else:
            try:
                metadata = json.loads(raw_metadata or "{}")
            except json.JSONDecodeError:
                metadata = {}
        metadata.update({k: v for k, v in self._frontmatter(text).items() if k not in metadata})
        return metadata

    def _frontmatter(self, text: str) -> dict:
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if not match:
            return {}
        try:
            import yaml

            parsed = yaml.safe_load(match.group(1)) or {}
            if not isinstance(parsed, dict):
                return {}
            return parsed
        except (ImportError, yaml.YAMLError):
            # Defensive line-by-line fallback. List-typed values (tags: in
            # block form) won't survive this — by design, that's the case
            # the YAML path was added to handle.
            data = {}
            for line in match.group(1).splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip("'\"")
            return data

    def _strip_frontmatter(self, text: str) -> str:
        return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL).strip()
