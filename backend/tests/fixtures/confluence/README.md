# Confluence test fixtures (ATL-50)

Frozen JSON snapshots shaped like the Atlassian Cloud REST API so downstream
tests run without a network round-trip.

| File                          | Purpose                                                                                     |
|-------------------------------|---------------------------------------------------------------------------------------------|
| `list_pages_response.json`    | `GET /rest/api/space/{key}/page?expand=version` envelope — 5 pages, mixed statuses.         |
| `list_pages_archived.json`    | Same shape as above but mixed with `status: "archived"` entries — exercises the filter.     |
| `page_with_ancestors.json`    | `GET /rest/api/content/{id}?expand=body.storage,ancestors,version,history,metadata.labels,metadata.properties` — root -> mid -> leaf chain. |
| `page_with_attachments.json`  | Same shape — two attachments referenced under `/rest/api/content/{id}/child/attachment`.    |
| `attachments_response.json`   | `GET /rest/api/content/{id}/child/attachment` envelope with 2 attachment records.           |
| `page_xhtml_rich.json`        | Full page whose `body.storage.value` carries a code block + table + `<ac:structured-macro>` — the parser edge-case payload. |
| `page_malformed_body.json`    | Full page whose body is truncated/unclosed XHTML — exercises the parser's tolerance.        |
| `page_empty_space.json`       | List-envelope with an empty `results` array — exercises "empty space" pathway.              |
| `attachments/diagram.png`     | Tiny binary payload used as attachment content by the integration test.                     |
| `attachments/spec.pdf`        | Tiny binary payload used as the second attachment in the integration test.                  |

The shapes mirror `tests/test_confluence_plugin.py`'s `_list_page`,
`_full_page`, and `_attachment` helpers — if those helpers ever need
to diverge from the real API, this directory must update in lockstep.
