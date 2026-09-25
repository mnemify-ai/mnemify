"""Local files source plugin — harvest any folders of .md / .txt / .pdf files.

Registers itself with the plugin registry at import time so the CLI can
instantiate it via ``create_plugin("localfiles", config)``.
"""

from .models import LocalFilesConfig, LocalRoot, root_key, roots_from_scope_ids, split_scope_id
from .plugin import LocalFilesHarvesterPlugin
from .scanner import SUPPORTED_EXTENSIONS

__all__ = [
    "LocalFilesConfig",
    "LocalRoot",
    "LocalFilesHarvesterPlugin",
    "SUPPORTED_EXTENSIONS",
    "root_key",
    "roots_from_scope_ids",
    "split_scope_id",
]


def _create_localfiles_plugin(config: dict):
    """Factory used by the plugin registry. ``config`` is the
    ``sources.localfiles`` sub-dict from mnemify.yaml (``roots:`` list, or
    the older single ``root_path:``)."""
    return LocalFilesHarvesterPlugin(LocalFilesConfig.from_yaml(config)), None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("localfiles", _create_localfiles_plugin)
