"""Single source of truth for where Mnemify keeps state on disk.

Everything the app persists — harvested data, ``mnemify.yaml``, ``.env``,
logs, the running server's pid/port — lives under one *home* directory.

Home precedence:

1. ``MNEMIFY_HOME`` env var (absolute or ``~``-relative).
2. Legacy dev layout: if ``<repo>/backend/`` already holds a ``.mnemify/``,
   ``mnemify.yaml`` or ``.env``, ``backend/`` is home. This keeps every
   existing checkout — including the team's real data — working untouched.
3. Platform per-user app-data dir:
   macOS   ``~/Library/Application Support/Mnemify``
   Windows ``%LOCALAPPDATA%\\Mnemify``
   Linux   ``$XDG_DATA_HOME/mnemify`` (default ``~/.local/share/mnemify``)

Two files keep their pre-existing per-file overrides, which win over
``home()``: ``MNEMIFY_ENV_FILE`` and ``MNEMIFY_YAML_FILE``.

Nothing here is cached and no module exports a path *constant*: call the
functions at use time so tests (and ``MNEMIFY_HOME``) can redirect state
without import-order surprises.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_ENV = "MNEMIFY_HOME"
ENV_FILE_ENV = "MNEMIFY_ENV_FILE"
YAML_FILE_ENV = "MNEMIFY_YAML_FILE"
WEB_DIST_ENV = "MNEMIFY_WEB_DIST"

# src/paths.py → parents[0] = src/, parents[1] = backend/, parents[2] = repo root
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

_LEGACY_MARKERS = (".mnemify", "mnemify.yaml", ".env")


def backend_dir() -> Path:
    """``<repo>/backend`` — where ``pyproject.toml`` lives."""
    return _BACKEND_DIR


def repo_root() -> Path:
    return _REPO_ROOT


def _platform_default() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Mnemify"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Mnemify"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "mnemify"


def platform_default() -> Path:
    """The per-user app-data home, ignoring ``MNEMIFY_HOME`` and the legacy
    layout. This is where ``mnemify migrate-home`` moves state to."""
    return _platform_default()


def _legacy_home() -> Path | None:
    for name in _LEGACY_MARKERS:
        if (_BACKEND_DIR / name).exists():
            return _BACKEND_DIR
    return None


def layout() -> str:
    """Which rule picked ``home()``: ``"env"``, ``"legacy"`` or ``"platform"``."""
    if os.environ.get(HOME_ENV):
        return "env"
    if _legacy_home() is not None:
        return "legacy"
    return "platform"


def home() -> Path:
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    legacy = _legacy_home()
    if legacy is not None:
        return legacy
    return _platform_default()


def ensure_home() -> Path:
    """``home()``, created if missing. Call before the first write."""
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    return h


def data_dir() -> Path:
    """The ``.mnemify/`` tree: raw/, normalized/, manifest + terrain DBs, artifacts."""
    return home() / ".mnemify"


def yaml_file() -> Path:
    override = os.environ.get(YAML_FILE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return home() / "mnemify.yaml"


def env_file() -> Path:
    override = os.environ.get(ENV_FILE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return home() / ".env"


def logs_dir() -> Path:
    return home() / "logs"


def server_pid_file() -> Path:
    return home() / "server.pid"


def server_port_file() -> Path:
    return home() / "server.port"


def resolve_under_data_dir(value: str | Path) -> Path:
    """Resolve a YAML path setting (``raw_root``, ``normalized_root``…).

    Absolute paths pass through; relative ones are anchored to ``home()``
    (not the process cwd) so ``raw_root: .mnemify/raw`` means the same thing
    no matter where the process was started from.
    """
    p = Path(value).expanduser()
    return p if p.is_absolute() else home() / p


def web_dist_dir() -> Path | None:
    """Built frontend to serve, or ``None`` if no build exists.

    ``MNEMIFY_WEB_DIST`` overrides; otherwise ``frontend/web/dist`` in the
    repo (older layouts used ``frontend/dist`` — accept either).
    """
    override = os.environ.get(WEB_DIST_ENV)
    if override:
        p = Path(override).expanduser().resolve()
        return p if p.is_dir() else None
    for cand in (
        _REPO_ROOT / "frontend" / "web" / "dist",
        _REPO_ROOT / "frontend" / "dist",
    ):
        if cand.is_dir():
            return cand
    return None


def describe() -> dict[str, str]:
    """Human-readable snapshot for ``/api/health`` and ``mnemify status``."""
    return {
        "layout": layout(),
        "home": str(home()),
        "data_dir": str(data_dir()),
        "yaml_file": str(yaml_file()),
        "env_file": str(env_file()),
    }
