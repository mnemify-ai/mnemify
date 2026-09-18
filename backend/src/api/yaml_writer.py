"""Round-trip writer for ``mnemify.yaml``.

Uses ``ruamel.yaml`` in round-trip mode so comments, ordering, and
formatting survive. The UI only touches one ``sources.<name>`` block
at a time; the rest of the file is returned to disk byte-identical.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


from src import paths

YAML_PATH_ENV = paths.YAML_FILE_ENV  # kept for callers that import the name


def resolve_yaml_path() -> Path:
    """``mnemify.yaml`` — ``MNEMIFY_YAML_FILE`` override, else ``<home>/mnemify.yaml``.

    Same resolver ``src.config_file.load_config_file`` reads from.
    """
    return paths.yaml_file()


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def read_config() -> dict[str, Any]:
    path = resolve_yaml_path()
    if not path.exists():
        return {"sources": {}}
    y = _yaml()
    with path.open("r", encoding="utf-8") as f:
        data = y.load(f) or {}
    if "sources" not in data:
        data["sources"] = {}
    return data


def upsert_source(name: str, block: dict[str, Any]) -> None:
    """Replace ``sources.<name>`` with ``block``. Atomic file replace."""
    path = resolve_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    y = _yaml()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {"raw_root": ".mnemify/raw", "converter_version": "0.1.0", "sources": {}}

    data.setdefault("sources", {})
    data["sources"][name] = block

    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def upsert_schedule(source: str, body: dict[str, Any] | None) -> None:
    """Set ``schedules.<source>`` to ``body`` (or remove it when ``body`` is None).
    Atomic file replace. Preserves the rest of the file via ruamel round-trip."""
    path = resolve_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    y = _yaml()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {"raw_root": ".mnemify/raw", "converter_version": "0.1.0", "sources": {}}

    schedules = data.get("schedules")
    if schedules is None:
        data["schedules"] = {}
        schedules = data["schedules"]

    if body is None:
        schedules.pop(source, None)
    else:
        schedules[source] = body

    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def upsert_retention(body: dict[str, Any]) -> None:
    """Set the top-level ``data_retention`` block. Atomic file replace.

    Body keys: ``on_source_delete`` ("keep" | "purge"), ``purge_grace_days``
    (non-negative int). Round-trip preserves the rest of the file via ruamel.
    """
    path = resolve_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    y = _yaml()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {"raw_root": ".mnemify/raw", "converter_version": "0.1.0", "sources": {}}

    data["data_retention"] = body

    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def upsert_compile(body: dict[str, Any]) -> None:
    """Set the top-level ``compile`` block (saved compile-settings defaults).
    Atomic file replace. Round-trip preserves the rest of the file via ruamel."""
    path = resolve_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    y = _yaml()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {"raw_root": ".mnemify/raw", "converter_version": "0.1.0", "sources": {}}

    data["compile"] = body

    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def upsert_server(block: dict[str, Any]) -> None:
    """Set the top-level ``server`` block (lifecycle settings — idle shutdown).
    Atomic file replace. Round-trip preserves the rest of the file via ruamel."""
    path = resolve_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    y = _yaml()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = y.load(f) or {}
    else:
        data = {"raw_root": ".mnemify/raw", "converter_version": "0.1.0", "sources": {}}

    data["server"] = block

    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def disable_source(name: str) -> None:
    """Flip ``sources.<name>.enabled`` to False without touching other keys."""
    path = resolve_yaml_path()
    if not path.exists():
        return
    y = _yaml()
    with path.open("r", encoding="utf-8") as f:
        data = y.load(f) or {}
    src = data.get("sources", {}).get(name)
    if not src:
        return
    src["enabled"] = False
    buffer = StringIO()
    y.dump(data, buffer)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(tmp, path)
