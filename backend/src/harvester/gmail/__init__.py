"""Gmail source plugin — public API and registry self-registration.

Phase-2 alpha source per ``backend/docs/planning/phase-2-roadmap.md`` M4
("proof that API sources beyond Notion work"). Mirrors the shape of the
Jira plugin (``src/harvester/jira/__init__.py``) — a factory that reads
config from the YAML dict, resolves the OAuth credentials path from the
env var named by ``credentials_env``, and constructs a
:class:`GmailHarvesterPlugin` with a pre-configured :class:`GmailClient`.

Auth model decisions (recorded for later reference):

- OAuth 2.0 with the ``gmail.readonly`` scope only. No write-back, no
  modify, no send.
- The OAuth client-secret JSON path comes from ``GMAIL_CREDENTIALS_PATH``
  (overridable via ``credentials_env``). Refresh-token cache JSON lives
  at ``~/.mnemify/gmail/token.json`` (overridable via ``token_path``).
- The factory **does not** run the consent flow — that lives in the
  ``mnemify login --source gmail`` CLI subcommand. If the cached
  token is missing the factory raises :class:`EnvironmentError` with a
  remediation pointer.

Output-format contract: pure-body markdown (Confluence/Notion pattern,
not Jira). All metadata flows through :attr:`RawDocument.metadata` to
the manifest's ``documents.metadata`` JSON column.
"""

from __future__ import annotations

from .client import GmailAPIError, GmailAuthError, GmailClient
from .models import GmailConfig
from .plugin import GmailHarvesterPlugin
from .threads import ThreadExtractor

__all__ = [
    # Models
    "GmailConfig",
    # Client + extractors
    "GmailClient",
    "GmailAPIError",
    "GmailAuthError",
    "ThreadExtractor",
    # Plugin
    "GmailHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_gmail_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.gmail`` sub-dict from mnemify.yaml
    (or a programmatic dict matching :class:`GmailConfig`). Returns
    ``(plugin, None)`` — ``googleapiclient`` is synchronous and has no
    async resource to pump; teardown lives in ``plugin.aclose()``.

    OAuth client resolution (delegated to
    :func:`src.harvester._google.oauth.resolve_client_secrets_path`):

    1. ``credentials_path`` directly in the YAML config (test / advanced).
    2. The env var named by ``credentials_env`` — the power-user override
       that lets a user point at their own Google Cloud project.
    3. The bundled Mnemify OAuth client at
       ``src/harvester/_google/oauth_client.json``. This is the path
       every normal user takes — they don't even know it exists.

    Raises :class:`EnvironmentError` only when *all three* sources are
    absent, in which case the message names the bundle path so the
    operator knows where to drop the file.
    """
    from src.harvester._google.oauth import resolve_client_secrets_path

    cfg = GmailConfig(
        credentials_env=config.get("credentials_env", "GMAIL_CREDENTIALS_PATH"),
        token_path=config.get("token_path", "~/.mnemify/google/gmail-token.json"),
        label_filter=list(config.get("label_filter", []) or []),
        label_exclude=list(
            config.get("label_exclude", ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"])
            or []
        ),
        sender_allowlist=list(config.get("sender_allowlist", []) or []),
        max_threads_per_run=config.get("max_threads_per_run"),
        concurrency=config.get("concurrency", 3),
        user_id=config.get("user_id", "me"),
    )

    explicit_path = config.get("credentials_path")
    resolved = resolve_client_secrets_path(
        client_secrets_path=explicit_path,
        client_secrets_env=cfg.credentials_env,
    )

    client = GmailClient(
        credentials_path=str(resolved),
        token_path=cfg.token_path,
        user_id=cfg.user_id,
    )
    plugin = GmailHarvesterPlugin(cfg, client=client)
    return plugin, None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("gmail", _create_gmail_plugin)
