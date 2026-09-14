# Mnemify Backend

The Python backend: the **harvester** (zero-LLM data collection from Notion / Confluence / Jira / Obsidian — fetch, hash, deduplicate, store), the **terrain compiler** (`src/terrain/` — chunk → extract → embed → semantically cluster (HDBSCAN) → layout → name → derive the v2 brain-map → bake the v3 hex render-data), the **FastAPI server** (`src/api/` — the brain-map JSON, SSE-streamed harvest/compile progress, the connect wizard, and it hosts the built React app), and the **`mnemify` CLI** (`src/cli.py`).

Everything Mnemify writes lives under `.mnemify/` (gitignored): `raw/`, `normalized/`, `harvest-manifest.db`, `harvest-log.jsonl`, `terrain.json`, `mocknotes.json`, `render-data.json`, `terrain.db`.

## Quick start

```bash
cd backend
uv sync --extra dev                 # creates .venv/ with the package, the `mnemify` CLI, and the test tools
cp .env.template .env               # add NOTION_TOKEN / CONFLUENCE_* / JIRA_* / SLACK_* / GITHUB_TOKEN / OPENAI_API_KEY as needed
cp example_mnemify.yaml mnemify.yaml   # Notion is enabled by default — flip other sources on here too

uv run mnemify harvest           # pull docs from every source enabled in mnemify.yaml
uv run mnemify terrain build --ai-mode local   # compile → .mnemify/{terrain,mocknotes,render-data}.json (no API key)
uv run mnemify up                # start the FastAPI server (also serves the built React SPA)
```

> Without a `mnemify.yaml`, every source defaults to disabled and `mnemify harvest` no-ops with "No sources to harvest" — the `cp example_mnemify.yaml mnemify.yaml` step above is what turns Notion on.

> The whole app (backend + the React UI) is normally launched from the repo root — see [Run it](../README.md#run-it) in the repo README for the cross-platform steps. `uv run mnemify <cmd>` and `uv run python -m src <cmd>` are equivalent (or activate `.venv/` and drop the `uv run` prefix).

## The CLI

| Command | What |
|---|---|
| `mnemify harvest [--source S] [--dry-run] [--force-full]` | Pull docs from the enabled sources into `.mnemify/` |
| `mnemify terrain build [--ai-mode openai\|local] [--source S]` | Compile → v2 brain-map + v3 hex render-data |
| `mnemify terrain schema --out PATH` | Export the v2 brain-map JSON Schema |
| `mnemify up [--no-browser]` | Start the FastAPI server (`/api/*` + the React SPA) on :8783 |
| `mnemify status [--json]` | Manifest stats + recent log activity |
| `mnemify inspect <id> [--content]` | Print a document's manifest entry (and optionally its raw body) |
| `mnemify normalize` | Re-generate the normalized markdown sidecars from stored raw files |
| `mnemify purge [--older-than-days N] [--dry-run]` | Drop raw files for docs deleted at source |
| `mnemify debug` | Connection test + list documents + fetch one sample, for any source |
| `mnemify reset` | Wipe harvested data, disable every source, clear Mnemify-owned secrets |

## Tests

```bash
uv run pytest -q                       # the full suite (live-network tests skip without creds)
uv run pytest -q --ignore=tests/test_integration_harvest.py   # everything except the opt-in live-Notion module
uv run ruff check src/                 # lint
uv run pytest -q --mnemify-debug -v    # verbose with debug logging
```

## More

- [`../AGENTS.md`](../AGENTS.md) — code orientation: the harvester plugin contract, the terrain compiler file map, the API/SSE layout, the on-disk `.mnemify/` state.
- `example_mnemify.yaml` — an annotated source-config example (copy to `mnemify.yaml`, gitignored).
