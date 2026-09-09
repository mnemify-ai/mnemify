"""JQL string builder — isolates Atlassian's brittle datetime format.

Jira's JQL parser is strict about the ``updated`` clause format:

    ``updated >= "yyyy-MM-dd HH:mm"``   (quoted, space-separated, no
    seconds, no timezone designator)

Building this via ``str(datetime)`` or f-strings with default formatting
silently produces strings that Atlassian rejects with a 400.  Isolating
the builder in its own module (instead of inlining it into
:class:`IssueExtractor`) lets ATL-23's test suite target the format
string directly with a small table of datetime inputs.

Implementation: ATL-23.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Phase 1 accepts only plain Jira project keys ``[A-Z][A-Z0-9]+``.  Real
# Jira instances permit a few other characters (underscore is possible
# historically) but the standard Atlassian Cloud key shape is a letter
# followed by one or more letters/digits.  Hyphens are explicitly
# rejected — in JQL ``PROJ-KEY`` would be parsed as a reference to an
# issue key, not a project key, so silently accepting them would produce
# malformed queries.
_VALID_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9]+$")

# Atlassian's JQL datetime format.  No seconds, no timezone, quoted.
_JQL_DATETIME_FMT = "%Y-%m-%d %H:%M"


def build_jql(
    project_keys: list[str],
    since: datetime | None = None,
) -> str:
    """Build a JQL string that enumerates issues across one or more projects.

    Contract (frozen for ATL-23):

    - Always orders by ``updated DESC`` so paginated walks see the
      freshest issues first.
    - A single project renders as ``project = KEY``; multiple projects
      render as ``project in (KEY1, KEY2, ...)`` preserving input order.
    - When ``since`` is ``None``, no ``updated >= ...`` clause is added.
    - When ``since`` is supplied, appends
      ``AND updated >= "yyyy-MM-dd HH:mm"`` using Atlassian's required
      format.  **Seconds and microseconds are stripped.**  Timezone-aware
      datetimes are converted to UTC and then rendered as naive (no
      ``Z``/``+00:00`` suffix — the JQL parser rejects timezone
      designators and interprets the value in the Jira instance's
      configured timezone).
    - ``project_keys`` must match ``^[A-Z][A-Z0-9]+$`` — hyphens and
      lowercase letters raise :class:`ValueError` rather than risking a
      silently malformed query.
    - Empty ``project_keys`` raises :class:`ValueError`.

    Args:
        project_keys: Non-empty list of Jira project keys.
        since: Optional incremental-filter anchor.  Naive datetimes are
            assumed UTC; aware datetimes are converted to UTC.

    Returns:
        A JQL string ready to pass to
        :meth:`src.harvester.jira.client.JiraClient.jql_search`.

    Raises:
        ValueError: If ``project_keys`` is empty, contains a non-string,
            or contains any key that does not match the expected shape.
    """
    if not project_keys:
        raise ValueError("build_jql requires at least one project key")

    for key in project_keys:
        if not isinstance(key, str) or not _VALID_PROJECT_KEY.match(key):
            raise ValueError(
                f"Invalid Jira project key {key!r}: expected pattern "
                f"{_VALID_PROJECT_KEY.pattern} (hyphens and lowercase "
                f"letters are not accepted by the Phase 1 builder)"
            )

    if len(project_keys) == 1:
        project_clause = f"project = {project_keys[0]}"
    else:
        project_clause = f"project in ({', '.join(project_keys)})"

    if since is None:
        return f"{project_clause} ORDER BY updated DESC"

    # Normalise to naive UTC before formatting — Atlassian's JQL parser
    # rejects timezone suffixes.  Strip sub-minute precision as well
    # (``%M`` drops seconds on format, but we also drop them on the
    # Python datetime so log/debug output is unambiguous).
    anchor = since
    if anchor.tzinfo is not None:
        anchor = anchor.astimezone(timezone.utc).replace(tzinfo=None)
    anchor = anchor.replace(second=0, microsecond=0)
    formatted = anchor.strftime(_JQL_DATETIME_FMT)

    return f'{project_clause} AND updated >= "{formatted}" ORDER BY updated DESC'
