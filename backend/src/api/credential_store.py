"""Atomic per-key writes to ``.env``.

The UI wizard calls ``save_secret(name, value)`` after a token validates.
We never rewrite the whole file from memory — instead we patch one key
at a time, preserving any unrelated lines (comments, other sources,
user-hand-edited config) exactly as the user left them.

Atomicity: write to a sibling temp file, then ``os.replace`` it into
place. That avoids the race where a concurrent reader sees half a file.

Permissions: the temp file is chmod'ed ``0600`` *before* the replace, so
the file is never briefly world-readable and the mode survives the rename.
On Windows ``os.chmod`` can't express POSIX modes — the call is best-effort
there and ``%LOCALAPPDATA%`` is already per-user.

Freshness: uvicorn loads ``.env`` once at startup, so a value the UI saves
is on disk but not in ``os.environ`` until :func:`refresh` runs. Every write
path here calls it; endpoints that read env-sourced tokens call it too.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from src import paths

ENV_PATH_ENV = paths.ENV_FILE_ENV  # kept for callers that import the name


def resolve_env_path() -> Path:
    """The ``.env`` file — ``MNEMIFY_ENV_FILE`` override, else ``<home>/.env``.

    Same resolver ``src.config.load_config`` reads from, so a token the
    wizard saves is always the token the harvester loads.
    """
    return paths.env_file()


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


def refresh() -> None:
    """Re-sync ``os.environ`` from the on-disk ``.env``.

    ``override=True`` because the point is to let a value the user just saved
    win over whatever the process picked up at startup.
    """
    load_dotenv(resolve_env_path(), override=True)


def get_secret(name: str) -> str | None:
    """The effective value of one secret: ``.env`` first, then the environment.

    File-first so a value saved through the UI is authoritative even if the
    process was started with a stale export. Returns ``None`` when neither
    source has a non-empty value.

    Surrounding quotes are stripped here (and only here): ``read_secrets``
    returns raw file text — ``has_secret`` and the wizards depend on that —
    while ``load_dotenv`` unquotes, so without this a ``KEY="sk-…"`` line
    would hand the provider a key wrapped in literal quote characters.
    """
    raw = read_secrets().get(name, "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1].strip()
    if raw:
        return raw
    env = (os.environ.get(name) or "").strip()
    return env or None


def mask(value: str) -> str:
    """``"…k3Fq"`` — enough to recognise a key, never enough to use it."""
    return f"…{value[-4:]}" if len(value) > 8 else "…"


def save_secret(name: str, value: str) -> None:
    """Upsert one env key. Preserves unrelated lines + comment order."""
    _validate_key(name)
    write_secrets({name: value})


def write_secrets(pairs: dict[str, str]) -> None:
    """Upsert a batch of env keys in a single atomic rewrite."""
    for k, v in pairs.items():
        _validate_key(k)
        _validate_value(v)
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

    _atomic_write(path, new_lines)
    refresh()


def delete_secrets(names: Iterable[str]) -> None:
    """Remove named keys from .env. Other lines are preserved verbatim.

    Also drops them from ``os.environ``. ``load_dotenv`` only ever *sets*
    names, so without this a key deleted in the UI would stay live in the
    running process — the server would keep authenticating with a credential
    the user just told it to forget, and ``get_secret``'s environment
    fallback would still report it as set.
    """
    names = set(names)
    for name in names:
        os.environ.pop(name, None)
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
    _atomic_write(path, lines)
    refresh()


def _atomic_write(path: Path, lines: list[str]) -> None:
    """Write ``lines`` to ``path`` atomically, owner-only (0600).

    The chmod happens on the temp file so the secrets are never readable by
    anyone else, not even for the instant between create and rename. Windows
    (and exotic filesystems) can reject the call — the mode is a hardening
    measure, not a correctness requirement, so a failure is not fatal there.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # no POSIX modes here (Windows, some network mounts)
        pass
    os.replace(tmp, path)


def _validate_key(name: str) -> None:
    if not _KEY_RE.match(f"{name}="):
        raise ValueError(f"invalid env key name: {name!r}")


def _validate_value(value: str) -> None:
    """One value is one line. A line break would smuggle in a second ``KEY=``."""
    if "\n" in value or "\r" in value:
        raise ValueError("secret values must not contain line breaks")
