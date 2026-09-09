# Mnemify — Backlog & Deferred Work

A focused backlog of small-to-medium follow-ups. Each item names files, says *why*, and tags rough effort. Aim: each one fits in a single PR. (Moved here from `improvements.md` at the repo root during the May 2026 cleanup; forward-looking product/UX roadmap is in [`ROADMAP.md`](ROADMAP.md).)

Last updated: 2026-05-13.

## Done since this list was written

- **#10** — `html_to_plain_text` was *formalized*, not deleted: it's a tested XHTML→text utility (`backend/src/harvester/confluence/extractor.py`) with fixture coverage; the `confluence/__init__.py` docstring now documents its status.
- **#14** — the event bus has a replay ring buffer; a tab that reconnects mid-run gets the recent events replayed (`backend/src/api/event_bus.py`, `compile_bus.py`).
- **#21** — the React app has Vitest coverage (`formatEta`, the EWMA rate smoothing, the SSE state machine) — `frontend/web/`.
- Shipped wholesale: the **terrain compiler** (`backend/src/terrain/` → `.mnemify/{terrain,mocknotes,render-data}.json`), the **live compile pipeline + SSE progress + compile report**, the **3D hex brain map** reading live `/api/terrain/render-data`, the **connect→harvest→compile onboarding** screen, **Connections→Settings** tabs, **manage-scope** and the **advanced filter editor**, `./run.sh`, and the v3 hex bake vendored into the backend.

> **Note on §G / §K below:** items #17–#21 and #27–#29 reference `frontend/src/**/*.jsx`/`.js` — that was an earlier prototype frontend (now `mnemifyFE/`, out of scope here). The current dashboard is `frontend/web/src/**/*.tsx` (React + Vite + TS). Most of those items don't apply as written; treat them as "the *idea* is still good, the file paths aren't".

---

## A. Notion block→markdown: complete the long tail

Layer 2a shipped a pragmatic `PageExtractor.blocks_to_markdown` covering paragraphs, headings, lists, todos, code, quotes, callouts, dividers, bookmarks, file/image/pdf/video/audio, and child page/database links. Other block types still fall back to a plain text-content line — content isn't lost but structure is. These are the gaps:

1. **Tables** — `notion/pages.py:blocks_to_markdown`. Notion delivers tables as a parent `table` block whose children are `table_row` blocks; each row has a `cells: list[list[rich_text]]` array. Render as standard markdown pipe tables. *small.*
2. **Toggles** — same file. Render as `<details><summary>Title</summary>...children...</details>`. Markdown parsers tolerate inline HTML; downstream consumers keep the collapsibility signal. *small.*
3. **Columns / column_list** — same file. No real markdown equivalent; flatten children with a horizontal-rule separator between columns. *small.*
4. **Mentions** in `rich_text` — `notion/pages.py:_rich_text_to_markdown`. `mention` types (user, page, database, date) currently render as their `plain_text` only. Emit a stable reference syntax, e.g. `[@user-id]`, `[page:abc123]`, so downstream graph-building can resolve them. *small.*
5. **Equations** — same file. Render block equations as ` ```math ... ``` ` and inline as `$...$`. Notion stores the LaTeX in `block.data["equation"]["expression"]` (block) or `rich_text[].equation.expression` (inline). *small.*
6. **Synced blocks** — same file. Synced blocks reference another block tree; today they fall through. Emit children inline with an HTML comment marker `<!-- synced from {id} -->` for traceability. *small.*
7. **Underline** — `notion/pages.py:_rich_text_to_markdown`. Markdown has no native underline; consider rendering as `<u>...</u>` (HTML passthrough). The underlying text is currently preserved unmarked. *small.*
8. **Numbered list nesting** — same file. The current implementation resets the counter on every non-`numbered_list_item` sibling, but doesn't track separate counters for *nested* numbered lists at different indents. Fix by maintaining a per-depth counter. *small.*

Add unit tests for each new block type as you go (mirror the cases in `tests/test_notion_plugin.py:test_blocks_to_markdown_*`). *small per type.*

---

## B. Comments capability — surface to the UI

Layer 2b added a backend-side cache that disables Notion comment fetches after the first 401/403, with a single `logger.warning`. The user only sees this in the backend log, not the harvest UI.

9. **Emit a one-shot SSE log event when comments are disabled** — `backend/src/harvester/notion/plugin.py:_fetch_page_document` currently logs to `logger`. Plumb a callback (or pass a `harvest_logger` reference) so the plugin can publish a user-visible "Notion comments skipped — integration lacks Read comments capability" event onto the SSE bus exactly once per run. The frontend already renders log events; no UI change needed. *small (light interface change).*

---

## C. Confluence cleanup left over from Layer 4

10. **Drop or formalize the unused `html_to_plain_text` export** — `backend/src/harvester/confluence/extractor.py:71-114` and `confluence/__init__.py:24,38`. Layer 4 removed `Confluence.extract_plain_text`, so the module-level export is no longer wired into the harvest path. Either delete the function and tests, or document a remaining use case. *small.*

---

## D. Rate-limiter unification

11. **Single retry/backoff abstraction shared by all clients** — `notion/client.py:113-189` is hand-rolled (sliding window + custom retry); `confluence/client.py:189-230` and `jira/client.py` both use `tenacity`. Worth extracting a `RetryHarness` that takes a `(retryable_status_codes, retry_after_parser, max_attempts, max_wait)` config. Notion's sliding-window admission stays separate; the *retry* logic should be unified. Improves consistency of `Retry-After` handling and 5xx behavior. *medium.*
12. **Token-bucket option for Notion (advanced)** — `notion/client.py:_wait_for_rate_limit`. The current sliding window is correct but conservative. A token bucket allowing brief bursts above 3 rps (with a strict 1-second average ceiling) could shave 5-10% more in some workloads. Only worth doing if 429s remain rare. *medium.*
13. **Expose rate-limit metrics** — `notion/client.py`. Add counters for: requests admitted, requests waited, 429s observed, mean wait time. Surface via a debug log line or a small `/api/harvest/diagnostics` endpoint. Helps tune `rate_buffer` post-deploy. *small.*

---

## E. Event bus / SSE reliability

14. **Ring buffer + replay for late subscribers** — `backend/src/api/event_bus.py:14-44`. The bus currently drops events on backpressure (`QueueFull → silent drop`). If a UI tab reconnects mid-harvest it sees nothing. Keep a `deque(maxlen=200)` of recent events; on subscribe, replay them before yielding live events. *small.*
15. **Drop counter / lag visibility** — same file. Surface a `_dropped_count` and "subscriber N hasn't drained in M sec" in logs, so future SSE issues are diagnosable without instrumenting in the moment. *small.*

---

## F. Logging

16. **Rotate `harvest-log.jsonl`** — `backend/src/harvester/logger.py`. The file appends forever. Switch to a `RotatingFileHandler` (or equivalent: emit a size-check before each write and rotate at 100 MB). *small.*

---

## G. Frontend UX & a11y

17. **`aria-label` on per-source progress cards** — `frontend/src/components/HarvestProgress.jsx`. Screen reader users currently can't tell what's happening. Add `role="status"` and a synthesized label on each card (e.g. "Notion: 57 of 466 documents harvested, 1.2 per second"). *small.*
18. **Magic-number constants** — `frontend/src/lib/harvestStream.js:181,204` (log buffer cap of 200), `backend/src/api/event_bus.py:15` (queue capacity 512). Lift to named constants with an explanatory comment. *small.*
19. **Tooltip on the "~" ETA prefix** — `frontend/src/routes/Harvest.jsx`, `HarvestProgress.jsx`. We added `~Xm Ys` for baseline-rate-derived ETA, but new users won't know what the tilde means. Tooltip: "Estimated from typical Notion throughput; will update once we measure your run." *small.*
20. **Keyboard shortcuts for harvest controls** — `frontend/src/routes/Harvest.jsx`. Start/cancel/retry are mouse-only today. Wire into `ShortcutHelp` (the existing pattern in `frontend/src/components/ShortcutHelp.jsx`). *small.*

---

## H. Frontend tests

21. **Unit tests for `harvestStream.js` rate smoothing and `formatEta`** — no frontend tests exist today. Vitest would catch regressions in the EWMA, the null-rate fallback, and the `1m 23s` formatter. Cover: warming-up state (rate=null), single-value EWMA initialization, sequence smoothing, format edge cases (sub-second, hours-long). *small.*

---

## I. Backend tests

22. **`test_integration_harvest.py` — stale cases against the live API** — `backend/tests/test_integration_harvest.py`. This module only runs with `NOTION_TOKEN` set (skipped otherwise). When it does run, four cases fail: `test_database_scope_keeps_only_pages_from_target_database` (pre-existing — the live workspace doesn't satisfy the precondition; fix the test logic, fix the filter, or `pytest.skip` it), plus `test_plain_text_extraction_returns_nonempty_string`, `test_content_length_filter_rejects_short_and_accepts_long`, `test_markdown_endpoint_returns_content` — these call `NotionHarvesterPlugin.extract_plain_text` / `PageExtractor.get_page_markdown`, methods removed in a later refactor. Either rewrite those cases against the current plugin API or delete them. *small.*
23. **Stress test for the Notion sliding-window admission** — new file under `backend/tests/`. Fire N concurrent fake requests against a mocked httpx, assert the wait scheduling never exceeds 3 admissions per rolling 1-second window. Catches regressions if anyone touches `_wait_for_rate_limit`. *medium.*

---

## J. Config / DX

24. **Inline comments in `mnemify.yaml`** — `backend/mnemify.yaml`. Today the schema is self-evident if you've read the code; not if you're a new user. Add per-key comments (`concurrency: 5  # Notion is rate-limit-bound; >5 buys little`, etc.) and a header pointing at `example_mnemify.yaml`. *small.*
25. **`mnemify check --validate-config`** — `backend/src/cli.py` (a new flag on the existing `check`/`debug` command, or a new `validate` subcommand). Reads the YAML, asserts every referenced env var exists, attempts each plugin's `test_connection`, prints a green check or a remediation hint. *medium.*
26. **Auth-failure error messages with remediation** — `notion/plugin.py:test_connection`, `confluence/client.py:215-221`, `jira/client.py`. Today: `"Notion API 401 (unauthorized)"`. Tomorrow: `"Notion API 401: token rejected. Check that NOTION_TOKEN starts with 'ntn_' and that the integration is invited to the workspace pages you're trying to harvest."`. *small.*

---

## K. Potential follow-ups for the work just shipped

27. **Calibrate `SOURCE_BASELINE_RATE`** — `frontend/src/lib/sources.js`. Values are currently model-derived (Notion 1.5/s, Confluence 5/s). Once a few real harvests are on the books, replace with measured medians so the predicted ETA is closer to reality. Could even ship the measured rate from the backend on `complete` and persist a rolling estimate. *small.*
28. **Tune EWMA constant** — `frontend/src/lib/harvestStream.js`. Currently `0.7 * prev + 0.3 * next`. If the rate readout still feels jumpy after a few days of use, try `0.85 / 0.15` for heavier smoothing — but watch that responsiveness to genuine slowdowns (e.g. 429 stalls) doesn't suffer. *trivial; tune live.*
29. **Live-rate takeover threshold** — `Harvest.jsx:aggregate`. Today the aggregate switches from baseline-derived ETA to live-derived ETA on the first non-null per-source rate. Consider waiting until the live rate has been stable for ~5 seconds (e.g. variance below a threshold) to avoid thrashing between estimates. *small.*

---

## L. Documents page — surface tag mappings (unblocks frontend tag/region filters)

30. **Expose `primary_tag_id` + `tag_ids` on `DocRow`** — `backend/src/api/routes_documents.py:_row_to_doc` returns a row that drops everything tag-related. Currently the frontend `DocFiltersPanel` has a "Tag/region filters need a backend mapping that's still on the way" placeholder because there's no way client-side to map a harvested doc → its compile-time tag assignments. The link exists in `backend/src/terrain/pipelines/compiler.py` (`doc_to_tags` dict, plus `_note_id_for(doc_id) → "n-{sha256(doc_id)[:8]}"`), but isn't persisted in a doc-keyed shape. Two viable paths: (a) **Persist `.mnemify/doc_tags.json`** — `{doc_id: {primary_tag_id, tag_ids, region_id, top_region_id}}` — at the end of compile, then have `routes_documents.py` join against it. Small, cheap, reads on every list call. (b) **New endpoint** `GET /api/documents/tag-map` that returns the same dict — frontend caches it, indexes client-side, joins in `useDocuments`. Either way the UI work then becomes mechanical: turn the placeholder in `DocFiltersPanel.tsx` into a real region radio + tag typeahead. *medium (backend) + small (frontend).*
