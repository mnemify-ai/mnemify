"""Story-points field auto-discovery + issue-JSON flattening helpers.

Two concerns live here, both touching Jira's customfield system:

1. :func:`discover_story_points_field` calls ``/rest/api/3/field`` and
   returns the custom-field id whose ``name`` matches (case-insensitive)
   ``"Story point estimate"`` (preferred, modern Jira Cloud) or
   ``"Story Points"`` (legacy).  Jira Cloud has historically used
   ``customfield_10016`` for this, but plenty of sites land on different
   ids (``customfield_10026`` is common on newer sites), so the plugin
   **never** hardcodes an id.  Users whose site restricts field-listing
   permissions can override via ``sources.jira.story_points_field`` in
   mnemify.yaml.

2. :func:`flatten_issue_fields` projects the raw
   ``/rest/api/3/issue/{key}`` JSON into the metadata dict shape
   required by :class:`RawDocument.metadata` per plan doc §3.2
   ("RawDocument.metadata required keys").  Unlike the friend's
   ``_normalize`` projection (see ``friends_code/harvesters/jira.py:179``),
   this is **non-lossy**: the raw ADF description is not dropped — the
   caller keeps the full issue JSON in ``RawDocument.content`` and
   uses this flat dict only for filtering, manifest, and the Phase-2
   compiler's per-document metadata.

Scaffolded in ATL-03; bodies land here in ATL-40 (auto-discovery) and
ATL-22 (flattening).  A small plugin-level lazy cache (ATL-41) memoises
the discovery result on first ``list_documents`` call so we do not pay
the ``/rest/api/3/field`` round-trip on every invocation.
"""

from __future__ import annotations

from .client import JiraClient


# Canonical names we will accept for the Story-points field, in
# preference order.  Modern Jira Cloud uses "Story point estimate";
# legacy sites use "Story Points".  Some sites have both (renamed
# custom fields or residual configurations) — the preferred name wins
# even if the legacy field appears earlier in the ``/rest/api/3/field``
# listing.
_STORY_POINTS_NAME_PREFERENCE: tuple[str, ...] = (
    "story point estimate",
    "story points",
)


async def discover_story_points_field(client: JiraClient) -> str | None:
    """Resolve the custom-field id for "Story Points" on this Jira site.

    Calls ``/rest/api/3/field`` via :meth:`JiraClient.list_fields`, scans
    the result for a custom field whose ``name`` matches (case-insensitive)
    ``"Story point estimate"`` first, then ``"Story Points"``, and returns
    the ``id`` (e.g. ``"customfield_10026"``).

    Preference is by **name, not iteration order**: if a site exposes both
    names (common after field renames), the modern "Story point estimate"
    always wins over the legacy "Story Points" regardless of which one
    the API lists first.

    Returns ``None`` when neither name is present on the site — the
    plugin must treat ``story_points`` as permanently ``None`` in that
    case (surface ``resolved_story_points_field=None`` in metadata so the
    compiler can distinguish "no points" from "points field missing").

    Pure function of the fields listing; no caching inside this
    function.  The plugin-level cache lives on the :class:`JiraHarvesterPlugin`
    instance (ATL-41) so we do not re-hit ``/rest/api/3/field`` on every
    ``list_documents`` call.

    Implementation: ATL-40.
    """
    fields = await client.list_fields()

    # Build a case-insensitive name → id map.  Iterate once so that
    # preference lookup below is O(1) per candidate name.
    by_name: dict[str, str] = {}
    for field in fields or ():
        name = field.get("name")
        field_id = field.get("id")
        if not name or not field_id:
            continue
        # Later entries don't overwrite earlier ones — the first id
        # registered under a given canonical name wins.  In practice
        # Jira never returns two fields with the same display name,
        # but guard against it defensively.
        by_name.setdefault(name.strip().lower(), field_id)

    for preferred_name in _STORY_POINTS_NAME_PREFERENCE:
        if preferred_name in by_name:
            return by_name[preferred_name]
    return None


def _derive_url(issue: dict) -> str:
    """Resolve the human-browsable URL for an issue.

    Preference order:

    1. ``issue["_links"]["html"]`` — present on some Atlassian response
       envelopes; already absolute.
    2. Derived from ``issue["self"]`` by stripping the REST path suffix
       ``/rest/api/3/issue/{id-or-key}`` and appending ``/browse/{key}``.
    3. Empty string when neither is available (defensive — should not
       happen for a real Jira response).
    """
    links = issue.get("_links") or {}
    html = links.get("html")
    if html:
        return html

    self_url = issue.get("self")
    key = issue.get("key")
    if not self_url or not key:
        return ""

    # ``self`` looks like ``https://acme.atlassian.net/rest/api/3/issue/10001``.
    # Strip ``/rest/api/...`` onwards, then append ``/browse/{key}``.
    marker = "/rest/api/"
    idx = self_url.find(marker)
    if idx == -1:
        # Unknown shape — fall back to returning self; callers can still
        # identify the issue even if the URL is REST-flavoured.
        return self_url
    base = self_url[:idx]
    return f"{base}/browse/{key}"


def _resolve_user(user: dict | None) -> tuple[str | None, str | None]:
    """Return ``(account_id, display_name)`` for a Jira user sub-object.

    Unassigned issues serialise as ``null`` (not missing), so the caller
    pattern ``fields.get("assignee") or {}`` is preferred upstream —
    we additionally defend here against ``None`` being threaded through.
    """
    if not user:
        return None, None
    return user.get("accountId"), user.get("displayName")


def flatten_issue_fields(
    issue: dict,
    story_points_field: str | None,
) -> dict:
    """Project a raw Jira issue JSON into the metadata dict for storage.

    Produces the exact key set from the Phase 1 Atlassian plan's
    "RawDocument.metadata required keys" — ``document_type``, ``url``, ``project_key``,
    ``issue_type``, ``status``, ``priority``, ``assignee_id``,
    ``assignee_name``, ``reporter_id``, ``reporter_name``, ``created``,
    ``updated``, ``labels``, ``story_points``, ``resolved_story_points_field``,
    ``attachment_count``.

    When ``story_points_field`` is ``None`` (auto-discovery returned
    nothing) or the field is absent on this issue, ``story_points`` is
    emitted as ``None``.  ``resolved_story_points_field`` echoes the
    field id used (or ``None``) so downstream consumers can tell "no
    points assigned" apart from "site has no story-points field".

    Non-lossy: the raw ADF description is **not** emitted here — the
    caller keeps the full issue JSON in :class:`RawDocument.content`
    and uses this flat dict only for filter / manifest / compiler
    metadata.  Contrast with the friend's ``_normalize`` projection
    (``friends_code/harvesters/jira.py:179``), which dropped the
    description entirely.

    Null-safety: Jira returns explicit ``null`` for unassigned issues,
    missing priority, etc.  We use the ``fields.get(k) or {}`` pattern
    for every optional sub-object so both "key absent" and "key present
    but null" are handled uniformly.

    Implementation: ATL-22.
    """
    fields = issue.get("fields") or {}

    # User / object sub-fields: use ``or {}`` so explicit ``None``
    # (unassigned, unprioritised) is treated the same as absent key.
    assignee = fields.get("assignee") or {}
    reporter = fields.get("reporter") or {}
    issue_type_obj = fields.get("issuetype") or {}
    status_obj = fields.get("status") or {}
    priority_obj = fields.get("priority") or {}
    project_obj = fields.get("project") or {}

    assignee_id, assignee_name = _resolve_user(assignee)
    reporter_id, reporter_name = _resolve_user(reporter)

    # Project key: prefer the canonical ``fields.project.key`` (present
    # in full-issue and most JQL list responses).  Fall back to splitting
    # the issue key (``CONN-123`` → ``CONN``) when the project object is
    # absent, since the issue key is globally-unique-per-instance and its
    # prefix is the project key by construction.
    project_key = project_obj.get("key")
    if not project_key:
        issue_key = issue.get("key", "")
        if "-" in issue_key:
            project_key = issue_key.rsplit("-", 1)[0]
        else:
            project_key = None

    # Story points: only look up the custom field if auto-discovery (or
    # the YAML override) gave us an id.  ``fields.get(id)`` returns
    # ``None`` when the key is absent or the value is explicitly null —
    # which is exactly what the caller wants.
    story_points: float | None = None
    if story_points_field is not None:
        raw_sp = fields.get(story_points_field)
        # Jira returns numbers as float; guard against string-typed
        # values that some custom configurations emit.
        if isinstance(raw_sp, (int, float)):
            story_points = float(raw_sp)
        elif isinstance(raw_sp, str):
            try:
                story_points = float(raw_sp)
            except ValueError:
                story_points = None

    # Labels: always a list.  ``fields.get("labels", [])`` handles
    # missing key, but a stored ``null`` would break ``len()`` / iter.
    labels = fields.get("labels") or []

    # Attachment count: ``fields.attachment`` is absent for issues
    # fetched without the ``attachment`` field requested; treat as 0.
    attachment_count = len(fields.get("attachment") or [])

    return {
        "document_type": "issue",
        "url": _derive_url(issue),
        "project_key": project_key,
        "issue_type": issue_type_obj.get("name"),
        "status": status_obj.get("name"),
        "priority": priority_obj.get("name"),
        "assignee_id": assignee_id,
        "assignee_name": assignee_name,
        "reporter_id": reporter_id,
        "reporter_name": reporter_name,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "labels": list(labels),
        "story_points": story_points,
        "resolved_story_points_field": story_points_field,
        "attachment_count": attachment_count,
    }
