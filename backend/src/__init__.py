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
