from __future__ import annotations

import json
from pathlib import Path

from src.terrain.utils.models import KnowledgeMap, KnowledgeMapNotes


def _strip_vector_fields(obj: object) -> None:
    """Recursively drop ``embedding`` / ``context_embedding`` from a
    model_dump dict. They were ~98% of terrain.json's size; raw vectors live
    in terrain.db (``graph_node_vectors``) and context embeddings are
    recomputed at load time. Only these two keys — ``compiled_note`` /
    ``compiled_note_extractive`` stay, because
    ``_products_from_prior_compile`` reads them from the prior artifact."""
    if isinstance(obj, dict):
        obj.pop("embedding", None)
        obj.pop("context_embedding", None)
        for value in obj.values():
            _strip_vector_fields(value)
    elif isinstance(obj, list):
        for item in obj:
            _strip_vector_fields(item)


class KnowledgeMapEmitter:
    def emit(
        self,
        knowledge_map: KnowledgeMap,
        map_notes: KnowledgeMapNotes,
        data_dir: Path,
    ) -> tuple[Path, Path]:
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Pydantic ``by_alias=True`` so RegionEdge.from_ / TagEdge.from_
        # serialize back as the JSON key "from".
        terrain_dict = knowledge_map.model_dump(by_alias=True, mode="json")
        _strip_vector_fields(terrain_dict)
        terrain_json = json.dumps(terrain_dict, indent=2)
        notes_json = map_notes.model_dump_json(indent=2, by_alias=True)

        terrain_path = data_dir / "terrain.json"
        notes_path = data_dir / "mocknotes.json"

        self._atomic_write(terrain_path, terrain_json)
        self._atomic_write(notes_path, notes_json)
        return terrain_path, notes_path

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
