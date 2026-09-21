"""Mnemify — source connectors for Mnemify knowledge infrastructure."""

from __future__ import annotations


def _version_from_pyproject() -> str:
    """``project.version`` read straight out of ``backend/pyproject.toml``."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, ValueError):
        return "0.0.0+unknown"


def _read_version() -> str:
    """The installed distribution's version, else ``pyproject.toml``'s.

    ``importlib.metadata`` is the source of truth: a normal (even editable)
    install carries the dist metadata. The ``pyproject.toml`` fallback covers
    running straight from a checkout that was never installed — a plain
    ``PYTHONPATH=backend python -m src …``.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mnemify")
    except PackageNotFoundError:
        return _version_from_pyproject()


__version__ = _read_version()


def build_commit() -> str | None:
    """Short HEAD sha of this checkout, or ``None`` outside a git repo.

    Resolved once (cached) — ``/api/health`` and the compile log both stamp
    it so a user can tell which build a running server actually is. The
    explicit ``cwd`` matters: the server (and every test that ``chdir``s
    into a tmp dir) must not report some neighbouring repository's sha.
    """
    global _BUILD_COMMIT
    if _BUILD_COMMIT is not _UNSET:
        return _BUILD_COMMIT  # type: ignore[return-value]
    import subprocess

    from src import paths

    sha: str | None = None
    root = paths.repo_root()
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(root), capture_output=True, text=True, timeout=2, check=False,
            )
            sha = out.stdout.strip() or None
        except Exception:  # noqa: BLE001 — no git on PATH, sandboxed exec, timeout
            sha = None
    _BUILD_COMMIT = sha
    return sha


_UNSET = object()
_BUILD_COMMIT: object = _UNSET
