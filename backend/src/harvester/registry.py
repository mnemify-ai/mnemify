"""Plugin registry — factory pattern for source plugins.

Each plugin package registers itself at import time by calling
``register_plugin()``.  The CLI calls ``create_plugin()`` to instantiate
the correct plugin from a source-type string without knowing the concrete
class.

Registration happens in each plugin's ``__init__.py``, e.g.::

    # src/harvester/notion/__init__.py
    from src.harvester.registry import register_plugin
    register_plugin("notion", _create_notion_plugin)

The factory callable signature is::

    factory(config: dict) -> tuple[SourcePlugin, object | None]

The second return value is an optional "closeable resource" that the CLI
must close in its ``finally`` block (e.g. the Notion HTTP client).  Plugins
with no long-lived resources return ``None`` as the second element.

Which plugins get imported (and therefore registered) is decided by
``src.sources.enabled_sources()`` — this build ships Notion, Confluence and
Obsidian. The other plugin packages remain importable by hand; they just
aren't auto-registered. See ``src/sources.py``.
"""

from __future__ import annotations

from typing import Callable

from src.harvester import SourcePlugin
from src.sources import enabled_sources

# source_type → factory(config: dict) -> (plugin, closeable | None)
_PLUGIN_FACTORIES: dict[str, Callable[[dict], tuple[SourcePlugin, object | None]]] = {}


def register_plugin(
    source_type: str,
    factory: Callable[[dict], tuple[SourcePlugin, object | None]],
) -> None:
    """Register a plugin factory for a source type.

    Calling this with an already-registered source_type silently overwrites
    the previous registration (last write wins — useful in tests).
    """
    _PLUGIN_FACTORIES[source_type] = factory


def create_plugin(
    source_type: str,
    config: dict,
) -> tuple[SourcePlugin, object | None]:
    """Instantiate a plugin from its registered factory.

    Args:
        source_type: E.g. ``"notion"`` or ``"obsidian"``.
        config: Source-specific configuration dict (from the YAML config
                file's ``sources.<source_type>`` block).

    Returns:
        ``(plugin, closeable_or_None)`` — the caller is responsible for
        closing the second element if it is not ``None``.

    Raises:
        ValueError: If ``source_type`` is not registered.
    """
    # Lazy-import plugin packages so registration side-effects run on demand.
    _ensure_plugins_registered()

    if source_type not in _PLUGIN_FACTORIES:
        available = sorted(_PLUGIN_FACTORIES.keys())
        raise ValueError(
            f"Unknown source type: {source_type!r}. "
            f"Available: {available}"
        )
    return _PLUGIN_FACTORIES[source_type](config)


def registered_source_types() -> list[str]:
    """Return sorted list of all registered source type names."""
    _ensure_plugins_registered()
    return sorted(_PLUGIN_FACTORIES.keys())


def _ensure_plugins_registered() -> None:
    """Trigger registration side-effects by importing plugin packages.

    Only the connectors this build ships are imported — see
    ``src/sources.py`` for why and for the ``MNEMIFY_SOURCES`` dev override.
    Each import is still guarded so a missing optional dependency in one
    plugin does not block the others from registering.
    """
    for name in enabled_sources():
        _try_import(f"src.harvester.{name}")

    # Present in the tree, not enabled in this build — see src/sources.py.
    # Re-enable by name via MNEMIFY_SOURCES rather than by uncommenting:
    #   _try_import("src.harvester.jira")
    #   _try_import("src.harvester.gmail")
    #   _try_import("src.harvester.calendar")
    #   _try_import("src.harvester.slack")
    #   _try_import("src.harvester.github")


def _try_import(module: str) -> None:
    try:
        import importlib
        importlib.import_module(module)
    except ImportError:
        pass
