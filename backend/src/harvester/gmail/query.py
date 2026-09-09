"""Gmail search-query string builder.

Gmail accepts a search syntax very similar to (but distinct from) the
web UI search bar: ``after:<epoch>``, ``label:Name``, ``-label:Name``,
``-category:Promotions``, ``from:(a@x OR b@y)``. This builder isolates
the small format brittlenesses (system labels live under ``category:``,
not ``label:``; ``after:`` takes seconds-since-epoch as an integer; the
``from:`` clause must wrap multi-sender alternatives in parentheses)
so the rest of the plugin doesn't have to know the syntax.

Analogous to :mod:`src.harvester.jira.jql`.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Gmail's built-in system labels are addressed via ``category:`` rather
# than ``label:`` in the search syntax. Filter them at the prefix level
# so users can list ``CATEGORY_PROMOTIONS`` in their config and have the
# right operator selected automatically.
_SYSTEM_CATEGORY_PREFIX = "CATEGORY_"


def _label_clause(label: str, *, exclude: bool) -> str:
    """Render a single label include / exclude clause.

    System category labels (``CATEGORY_PROMOTIONS``) become
    ``category:promotions``; user labels stay as ``label:Name``.
    """
    sign = "-" if exclude else ""
    if label.startswith(_SYSTEM_CATEGORY_PREFIX):
        category = label[len(_SYSTEM_CATEGORY_PREFIX):].lower()
        return f"{sign}category:{category}"
    return f"{sign}label:{label}"


def build_query(
    *,
    since: datetime | None = None,
    label_filter: list[str] | None = None,
    label_exclude: list[str] | None = None,
    sender_allowlist: list[str] | None = None,
) -> str:
    """Build a Gmail ``q`` string for ``users.threads.list``.

    Components are space-joined; Gmail treats space as a logical AND.

    - ``since`` → ``after:{epoch_seconds}``. Naive datetimes are assumed
      UTC. Timezone-aware datetimes are converted to UTC before
      conversion to seconds-since-epoch.
    - ``label_filter`` → ``label:X label:Y`` (AND between labels).
      Empty list omits the clause entirely.
    - ``label_exclude`` → ``-label:X`` / ``-category:Y`` per element,
      depending on whether the name is a Gmail system category.
    - ``sender_allowlist`` → ``from:(a@x OR b@y)``. Single sender renders
      as ``from:a@x`` (no parentheses). Empty list omits the clause.

    An empty result string is valid — Gmail interprets it as "every
    thread the account has access to". Callers that need a safety cap
    should rely on :class:`GmailConfig.max_threads_per_run`, not on
    pruning the query here.
    """
    label_filter = label_filter or []
    label_exclude = label_exclude or []
    sender_allowlist = sender_allowlist or []

    parts: list[str] = []

    if since is not None:
        anchor = since
        if anchor.tzinfo is not None:
            anchor = anchor.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            # Naive — treat as already-UTC.
            pass
        epoch = int(anchor.replace(tzinfo=timezone.utc).timestamp())
        parts.append(f"after:{epoch}")

    for label in label_exclude:
        parts.append(_label_clause(label, exclude=True))

    for label in label_filter:
        parts.append(_label_clause(label, exclude=False))

    if sender_allowlist:
        if len(sender_allowlist) == 1:
            parts.append(f"from:{sender_allowlist[0]}")
        else:
            joined = " OR ".join(sender_allowlist)
            parts.append(f"from:({joined})")

    return " ".join(parts)
