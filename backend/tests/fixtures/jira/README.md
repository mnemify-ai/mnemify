# Jira fixtures — ATL-55

Frozen Jira REST API response snapshots used by Phase 1f test files:

- `tests/test_jira_plugin.py` (ATL-56)
- `tests/test_jira_failure_modes.py` (ATL-58)
- `tests/test_integration_jira.py` (ATL-59)

These fixtures make Jira tests runnable without any network access. Load
them via the helper in `tests/test_jira_plugin.py` (`_load_fixture`) or
re-declare a local loader per test file.

## Inventory

| File | Purpose |
|---|---|
| `jql_search_page1.json` | Page 1 of JQL search over 10 CONN-* issues (5 issues, `nextPageToken="eyJpZCI6NX0="`). Minimal `_LIST_FIELDS` shape. |
| `jql_search_page2.json` | Page 2 (5 issues, no `nextPageToken` — last page). Pagination termination: loop stops when `nextPageToken` is absent. |
| `jql_search_empty.json` | Empty-project response (`{"issues": []}`) used by ATL-58. No `nextPageToken` — single empty page terminates immediately. |
| `issue_with_attachments.json` | Full `/rest/api/3/issue/CONN-1` — ADF description, two attachments (PDF + PNG), story points set. |
| `issue_with_adf.json` | Full `/rest/api/3/issue/CONN-5` — rich ADF body (heading + list + codeBlock + mention), no attachments. |
| `issue_missing_assignee.json` | Full `/rest/api/3/issue/CONN-8` — `assignee: null`, `priority: null`, no attachments (tests null-assignee metadata path). |
| `fields_list.json` | `/rest/api/3/field` response including `customfield_10026` = "Story point estimate" + the standard schema fields. |
| `attachments/design.pdf` | Attachment payload for CONN-1 (stub bytes — not a real PDF). |
| `attachments/screenshot.png` | Attachment payload for CONN-1 (stub bytes — not a real PNG). |

The two JQL pages sum to 10 issues; the 3 full-issue responses cover
the distinct combinations from the plan row: attachments, ADF bodies,
and missing-assignee. Fixture keys are strictly within the `CONN`
project to keep JQL and metadata assertions trivial.
