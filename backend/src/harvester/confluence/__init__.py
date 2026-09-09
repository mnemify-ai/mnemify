"""Confluence source plugin — models and public API.

Exposes the public names (config dataclass, client, page extractor,
``html_to_plain_text`` XHTML→text utility, plugin) and self-registers with
the plugin registry at import time, so the CLI/UI can instantiate it via
``create_plugin("confluence", config)``. The registry imports this package
in ``registry._ensure_plugins_registered``; tests that need it before that
can ``import src.harvester.confluence`` directly to trigger registration.

``html_to_plain_text`` (in :mod:`.extractor`) flattens the XHTML
``body.storage`` payload to plain text — used for lossy filter snippets and
as a baseline indexable body; it has fixture-backed coverage in
``tests/test_confluence_extractor.py`` / ``test_confluence_parser.py``.
"""

from __future__ import annotations

from .models import ConfluenceConfig, ConfluencePage
from .client import ConfluenceClient
from .extractor import html_to_plain_text
from .pages import PageExtractor
from .plugin import ConfluenceHarvesterPlugin

__all__ = [
    # Models
    "ConfluenceConfig",
    "ConfluencePage",
    # Client + extractors
    "ConfluenceClient",
    "PageExtractor",
    "html_to_plain_text",
    # Plugin
    "ConfluenceHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_confluence_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.confluence`` sub-dict from mnemify.yaml
    (or a programmatic dict matching :class:`ConfluenceConfig`).

    Returns ``(plugin, None)`` — ``atlassian-python-api`` is synchronous and
    has no ``aclose`` to pump; teardown lives in ``plugin.aclose()``.

    Env-var resolution mirrors ``notion/__init__.py:_create_notion_plugin``:
    the factory reads ``email`` / ``token`` from the env var names given
    by ``email_env`` / ``token_env`` (defaults: ``CONFLUENCE_EMAIL`` and
    ``CONFLUENCE_API_TOKEN``).  Missing or empty values raise
    :class:`EnvironmentError` with a remediation hint that names the
    offending env var so the CLI can surface it verbatim.
    """
    import os

    base_url = config["base_url"]  # required — KeyError on miss is fine
    email_env = config.get("email_env", "CONFLUENCE_EMAIL")
    token_env = config.get("token_env", "CONFLUENCE_API_TOKEN")

    email = config.get("email") or os.getenv(email_env, "")
    token = config.get("token") or os.getenv(token_env, "")

    if not email:
        raise EnvironmentError(
            f"Confluence email not found. Set the {email_env!r} environment "
            "variable or provide 'email' directly in the source config."
        )
    if not token:
        raise EnvironmentError(
            f"Confluence API token not found. Set the {token_env!r} "
            "environment variable or provide 'token' directly in the "
            "source config."
        )

    # ``space_keys`` holds Confluence space keys (alphanumeric, e.g. "ENG",
    # "~accountId"); ``page_ids`` holds numeric page ids harvested as
    # subtrees. Earlier versions of Manage Scope wrote page ids into
    # ``space_keys`` — the Atlassian client then 404s with "No space with
    # key : <page_id>". Migrate any such stragglers into ``page_ids`` so an
    # old config gets the subtree behaviour the user originally asked for.
    raw_space_keys = config.get("space_keys", []) or []
    space_keys = [k for k in raw_space_keys if not (isinstance(k, str) and k.isdigit())]
    migrated_page_ids = [k for k in raw_space_keys if isinstance(k, str) and k.isdigit()]
    if migrated_page_ids:
        import logging
        logging.getLogger(__name__).info(
            "Confluence space_keys contained %d page-id-shaped entries; "
            "treating them as page-subtree scope. Re-save Manage Scope to "
            "persist them under 'page_ids'. (migrated=%r)",
            len(migrated_page_ids),
            migrated_page_ids[:5],
        )
    page_ids: list[str] = []
    for p in list(config.get("page_ids") or []) + migrated_page_ids:
        s = str(p)
        if s and s not in page_ids:
            page_ids.append(s)

    confluence_cfg = ConfluenceConfig(
        base_url=base_url,
        email_env=email_env,
        token_env=token_env,
        space_keys=space_keys,
        page_ids=page_ids,
        include_archived=config.get("include_archived", False),
        concurrency=config.get("concurrency", 3),
    )
    plugin = ConfluenceHarvesterPlugin(
        confluence_cfg,
        email=email,
        token=token,
    )
    return plugin, None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("confluence", _create_confluence_plugin)
