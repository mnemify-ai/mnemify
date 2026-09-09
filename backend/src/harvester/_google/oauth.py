"""Shared OAuth helpers for every Google-provider source plugin.

One Mnemify-owned OAuth client (the Google Cloud project the operator
sets up once) backs every Google integration — Gmail, Drive, Calendar,
Docs, etc. Each consumer plugin imports from this module with its own
scope list and its own per-service token cache path.

Resolution order for the OAuth client config (highest priority first):

1. The ``client_secrets_path`` argument — explicit override, used by
   tests and by power-users who pass it through the YAML config.
2. The env var the caller passes via ``client_secrets_env`` (e.g.
   ``GMAIL_CREDENTIALS_PATH``) — kept so a user with their own Google
   Cloud project can bypass the bundled client entirely.
3. The bundled ``oauth_client.json`` next to this file — the
   Mnemify-shipped client. This is what makes the user-facing flow
   "click Allow" instead of "create a Google Cloud project."
4. :class:`EnvironmentError` with a message that names both the env var
   and the bundled-file path, so the operator can fix it either way.

Token storage convention: ``~/.mnemify/google/<service>-token.json``,
with mode 0600. The OAuth client is shared across services, so grouping
the cache by *provider* matches the dependency graph; each scope-set
still gets its own token file because Google issues scope-bound tokens.

Per Google's docs for installed/desktop apps the OAuth ``client_secret``
is not actually a secret — distribution is the documented model. PKCE
plus the localhost-loopback redirect protect the handshake. We still
.gitignore the file by default so rotations don't rewrite history.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The bundled Mnemify OAuth client. Real file is gitignored — operator
# drops it next to this module per the steps in the README. Package
# distribution will include it as package_data when we ship binaries.
DEFAULT_BUNDLED_CLIENT: Path = Path(__file__).parent / "oauth_client.json"


def _expand(path: str | os.PathLike) -> Path:
    """Expand ``~`` and environment variables in *path*."""
    raw = os.fspath(path)
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def resolve_client_secrets_path(
    *,
    client_secrets_path: str | None = None,
    client_secrets_env: str | None = None,
) -> Path:
    """Pick the OAuth client config file using the documented resolution order.

    Returns the resolved :class:`pathlib.Path` (which exists on disk).
    Raises :class:`EnvironmentError` when no candidate exists.
    """
    candidate: Path | None = None
    source_description: str | None = None

    if client_secrets_path:
        candidate = _expand(client_secrets_path)
        source_description = "argument"
    elif client_secrets_env:
        env_value = os.getenv(client_secrets_env, "")
        if env_value:
            candidate = _expand(env_value)
            source_description = f"env var {client_secrets_env!r}"

    if candidate is not None:
        if not candidate.exists():
            raise EnvironmentError(
                f"Google OAuth client config not found at {candidate!s} "
                f"(specified via {source_description}). Either correct the "
                f"path or unset it to fall back to the bundled Mnemify "
                f"OAuth client at {DEFAULT_BUNDLED_CLIENT!s}."
            )
        return candidate

    if DEFAULT_BUNDLED_CLIENT.exists():
        return DEFAULT_BUNDLED_CLIENT

    env_hint = (
        f" Or set {client_secrets_env!r} to point at your own client config."
        if client_secrets_env
        else ""
    )
    raise EnvironmentError(
        f"No Google OAuth client config available. Drop your downloaded "
        f"OAuth client JSON at {DEFAULT_BUNDLED_CLIENT!s} (see "
        f"{DEFAULT_BUNDLED_CLIENT.with_suffix('.json.template')!s} for the "
        f"shape and the operator setup steps).{env_hint}"
    )


def load_credentials(
    *,
    scopes: list[str],
    token_path: str,
    client_secrets_path: str | None = None,
    client_secrets_env: str | None = None,
):
    """Load (and silently refresh) cached OAuth credentials for *scopes*.

    Raises :class:`EnvironmentError` when:

    - the OAuth client config can't be resolved (see
      :func:`resolve_client_secrets_path`), or
    - the cached token file at ``token_path`` doesn't exist — the user
      has not yet run ``mnemify login`` for this provider, or
    - the cached token is invalid and lacks a refresh-token (typically
      means consent was revoked at Google's end).

    Network refresh failures surface with a remediation message pointing
    at ``mnemify login`` for the relevant source.
    """
    # Validate the OAuth client config before doing anything else — gives
    # the operator the clearest possible error if they haven't dropped
    # the bundle in yet.
    resolve_client_secrets_path(
        client_secrets_path=client_secrets_path,
        client_secrets_env=client_secrets_env,
    )

    token_p = _expand(token_path)
    if not token_p.exists():
        raise EnvironmentError(
            f"Google OAuth token cache not found at {token_p!s}. "
            "Run `mnemify login --source <name>` once to mint it."
        )

    # Imports deferred so importing this module never requires
    # google-auth to be installed (e.g. on systems where every Google
    # source is disabled in mnemify.yaml).
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_p), scopes)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _write_token(token_p, creds)
        except Exception as exc:  # noqa: BLE001 — surface auth failure cleanly
            raise EnvironmentError(
                f"Google OAuth token refresh failed: {exc}. "
                "Re-run `mnemify login --source <name>` to re-authorise."
            ) from exc

    if not creds or not creds.valid:
        raise EnvironmentError(
            "Google OAuth credentials are invalid or expired without a "
            "refresh token. Re-run `mnemify login --source <name>`."
        )
    return creds


def run_consent_flow(
    *,
    scopes: list[str],
    token_path: str,
    client_secrets_path: str | None = None,
    client_secrets_env: str | None = None,
) -> None:
    """Run the interactive OAuth consent flow and persist the refresh token.

    Opens the user's browser via :class:`InstalledAppFlow.run_local_server`,
    walks them through Google's consent screen for the requested
    ``scopes``, and writes the resulting credentials to ``token_path``
    with mode 0600. Idempotent — running twice just produces a fresh
    refresh token.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_path = resolve_client_secrets_path(
        client_secrets_path=client_secrets_path,
        client_secrets_env=client_secrets_env,
    )
    token_p = _expand(token_path)

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
    creds = flow.run_local_server(port=0)
    _write_token(token_p, creds)
    logger.info("Google OAuth token written to %s", token_p)


def _write_token(token_path: Path, creds) -> None:
    """Persist credentials to ``token_path`` with mode 0600 (atomic).

    The directory is created on demand. The file is written via a
    sibling tmp-file rename so a partial write can never replace a
    good token. Mode is set on the tmp file before the rename so the
    final file is never world-readable, even briefly.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = token_path.with_suffix(token_path.suffix + ".tmp")
    tmp_path.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, token_path)
