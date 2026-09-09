"""Atomic per-key writes to ``.env``.

The UI wizard calls ``save_secret(name, value)`` after a token validates.
We never rewrite the whole file from memory — instead we patch one key
at a time, preserving any unrelated lines (comments, other sources,
user-hand-edited config) exactly as the user left them.

Atomicity: write to a sibling temp file, then ``os.replace`` it into
place. That avoids the race where a concurrent reader sees half a file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


ENV_PATH_ENV = "MNEMIFY_ENV_FILE"
DEFAULT_ENV_PATH = Path(".env")


def resolve_env_path() -> Path:
    override = os.environ.get(ENV_PATH_ENV)
    if override:
        return Path(override).resolve()
    # Anchor to the project root (parent of src/).
    here = Path(__file__).resolve()
    return here.parents[2] / ".env"


_KEY_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=")


def read_secrets() -> dict[str, str]:
    """Return a dict of the current ``KEY=VALUE`` entries (ignores blanks/comments)."""
    path = resolve_env_path()
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def has_secret(name: str) -> bool:
    return name in read_secrets()


def save_secret(name: str, value: str) -> None:
    """Upsert one env key. Preserves unrelated lines + comment order."""
    _validate_key(name)
    write_secrets({name: value})


def write_secrets(pairs: dict[str, str]) -> None:
    """Upsert a batch of env keys in a single atomic rewrite."""
    for k in pairs:
        _validate_key(k)
    path = resolve_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    written: set[str] = set()
    for line in existing_lines:
        m = _KEY_RE.match(line.strip())
        if m and m.group(1) in pairs:
            key = m.group(1)
            new_lines.append(f"{key}={pairs[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    for key, value in pairs.items():
        if key in written:
            continue
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"{key}={value}")

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def delete_secrets(names: Iterable[str]) -> None:
    """Remove named keys from .env. Other lines are preserved verbatim."""
    names = set(names)
    path = resolve_env_path()
    if not path.exists():
        return
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _KEY_RE.match(line.strip())
        if m and m.group(1) in names:
            continue
        lines.append(line)
    # Collapse multiple trailing blanks.
    while lines and lines[-1].strip() == "":
        lines.pop()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validate_key(name: str) -> None:
    if not _KEY_RE.match(f"{name}="):
        raise ValueError(f"invalid env key name: {name!r}")
