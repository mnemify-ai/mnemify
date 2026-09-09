"""Gmail-specific wrappers over the shared Google OAuth helpers.

The actual OAuth plumbing — bundled-client resolution, token refresh,
mode-0600 atomic writes — lives in :mod:`src.harvester._google.oauth`
because Drive, Calendar, Docs, etc. will reuse it. This module just
bakes in Gmail's scope list and credentials env-var name and forwards
the call.
"""

from __future__ import annotations

from src.harvester._google import oauth as _google_oauth

# Read-only access is sufficient for harvesting; the minimum scope keeps
# the consent-screen friction low and shrinks the blast radius of a
# leaked refresh token.
GMAIL_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]

# Power-user override: set this env var to point at your own Google
# Cloud project's OAuth client JSON instead of using the bundled
# Mnemify client. Most users do not need to touch it.
GMAIL_CREDENTIALS_ENV = "GMAIL_CREDENTIALS_PATH"


def load_credentials(token_path: str, *, client_secrets_path: str | None = None):
    """Load (and refresh) cached Gmail OAuth credentials."""
    return _google_oauth.load_credentials(
        scopes=GMAIL_SCOPES,
        token_path=token_path,
        client_secrets_path=client_secrets_path,
        client_secrets_env=GMAIL_CREDENTIALS_ENV,
    )


def run_consent_flow(
    token_path: str,
    *,
    client_secrets_path: str | None = None,
) -> None:
    """Run the interactive Gmail OAuth consent flow and persist the refresh token."""
    _google_oauth.run_consent_flow(
        scopes=GMAIL_SCOPES,
        token_path=token_path,
        client_secrets_path=client_secrets_path,
        client_secrets_env=GMAIL_CREDENTIALS_ENV,
    )
