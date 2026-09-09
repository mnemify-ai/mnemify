"""Calendar-specific wrappers over the shared Google OAuth helpers.

Mirrors :mod:`src.harvester.gmail.auth`. Bakes in Calendar's scope list
and credentials env-var name; the actual OAuth plumbing —
bundled-client resolution, token refresh, mode-0600 atomic writes —
lives in :mod:`src.harvester._google.oauth` and is shared with every
other Google-source plugin.
"""

from __future__ import annotations

from src.harvester._google import oauth as _google_oauth

# Read-only access is sufficient for harvesting; the minimum scope keeps
# the consent-screen friction low and shrinks the blast radius of a
# leaked refresh token.
CALENDAR_SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar.readonly"]

# Power-user override: set this env var to point at your own Google
# Cloud project's OAuth client JSON instead of using the bundled
# Mnemify client. Most users do not need to touch it.
CALENDAR_CREDENTIALS_ENV = "CALENDAR_CREDENTIALS_PATH"


def load_credentials(token_path: str, *, client_secrets_path: str | None = None):
    """Load (and refresh) cached Google Calendar OAuth credentials."""
    return _google_oauth.load_credentials(
        scopes=CALENDAR_SCOPES,
        token_path=token_path,
        client_secrets_path=client_secrets_path,
        client_secrets_env=CALENDAR_CREDENTIALS_ENV,
    )


def run_consent_flow(
    token_path: str,
    *,
    client_secrets_path: str | None = None,
) -> None:
    """Run the interactive Calendar OAuth consent flow and persist the refresh token."""
    _google_oauth.run_consent_flow(
        scopes=CALENDAR_SCOPES,
        token_path=token_path,
        client_secrets_path=client_secrets_path,
        client_secrets_env=CALENDAR_CREDENTIALS_ENV,
    )
