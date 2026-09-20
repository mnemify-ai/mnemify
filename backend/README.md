# Mnemify Backend

The Python backend: the **harvester** (zero-LLM data collection from Notion, Confluence and Obsidian — fetch, hash, deduplicate, store; five more connectors — Jira, Slack, GitHub, Gmail, Calendar — are in the tree but off in this build, see `src/sources.py` and `MNEMIFY_SOURCES`), the **terrain compiler** (`src/terrain/` — chunk → extract → embed → semantically cluster (HDBSCAN) → layout → name → emit the terrain and the hex map data), the **FastAPI server** (`src/api/` — the brain-map JSON, SSE-streamed harvest/compile progress, the connect wizard, and it hosts the built React app), and the **`mnemify` CLI** (`src/cli.py`).

Harvested and compiled data lives under `.mnemify/`: `raw/`, `normalized/`, `harvest-manifest.db`, `harvest-log.jsonl`, `terrain.json`, `mocknotes.json`, `render-data.json`, `terrain.db`. That folder sits inside a *home* directory alongside `mnemify.yaml`, `.env`, `logs/` and the running server's `server.pid`/`server.port`. `src/paths.py` decides where home is — a per-user data directory outside the repo by default (see [Where your data lives](../README.md#where-your-data-lives)), `backend/` itself in an existing checkout that already has state there, or wherever `MNEMIFY_HOME` points.

## Quick start

```bash
cd backend
uv sync --extra dev              # creates .venv/ with the package, the `mnemify` CLI, and the test tools
uv run mnemify up                # start the FastAPI server (also serves the built React SPA)
                                 # → Settings → AI & Models for OPENAI_API_KEY / ANTHROPIC_API_KEY
                                 # → Build → Sources for the Notion / Confluence / Obsidian wizards

uv run mnemify harvest           # pull docs from every source the wizards enabled
uv run mnemify terrain build --ai-mode local   # compile → .mnemify/{terrain,mocknotes,render-data}.json (no API key)
```

> **Credentials and source config belong in the app**, not in a file you edit. The wizards write `.env` (mode `0600`) and `mnemify.yaml` into your data home — `src/paths.py` decides where that is. Dropping a hand-written `.env` + `cp example_mnemify.yaml mnemify.yaml` here in `backend/` still works as a manual fallback, but it also *pins this `backend/` folder as the data home* (the legacy layout), so prefer the UI unless you mean to do that. `example_mnemify.yaml` is the annotated reference for what each block means; the secret names it expects are the `*_env` keys in each source block plus `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. With no `mnemify.yaml` at all, every source is disabled and `mnemify harvest` no-ops with "No sources to harvest" — connect something in **Build → Sources** first.

> This is the from-source developer path. Most people install with `sh setup.sh` / `setup.bat` at the repo root and start the app from its icon — see [Install](../README.md#install) and [Start and stop](../README.md#start-and-stop) in the repo README. `uv run mnemify <cmd>` and `uv run python -m src <cmd>` are equivalent (or activate `.venv/` and drop the `uv run` prefix).

## The CLI

| Command | What |
|---|---|
| `mnemify harvest [--source S] [--dry-run] [--force-full]` | Pull docs from the enabled sources into `.mnemify/` |
| `mnemify terrain build [--ai-mode openai\|local] [--source S]` | Compile the harvested docs into the terrain + hex map data |
| `mnemify terrain schema --out PATH` | Export the terrain JSON Schema |
| `mnemify up [--host H] [--port N] [--no-browser] [--reload]` | Start the FastAPI server (`/api/*` + the React SPA) on :8783. One instance at a time: if one is already up it prints the URL, opens the browser and exits 0. If the port is taken by something else it tries the next ten. |
| `mnemify stop` | Ask the running server to quit (reads `<home>/server.port`; no signals, works on Windows) |
| `mnemify migrate-home [--yes]` | Move a legacy `backend/` state layout into the platform app-data home |
| `mnemify status [--json]` | Manifest stats + recent log activity |
| `mnemify inspect <id> [--content]` | Print a document's manifest entry (and optionally its raw body) |
| `mnemify normalize` | Re-generate the normalized markdown sidecars from stored raw files |
| `mnemify purge [--older-than-days N] [--dry-run]` | Drop raw files for docs deleted at source |
| `mnemify debug` | Connection test + list documents + fetch one sample, for any source |
| `mnemify reset` | Wipe harvested data, disable every source, clear Mnemify-owned secrets |

> **Under `--reload`, `mnemify stop` does nothing and the pid/port files don't describe the process you're looking at.** The reloader is a supervisor: it watches the files and restarts a *child* that actually serves, and only the child registers a shutdown handle. So `mnemify stop`, the UI's Quit button and the idle watchdog all no-op (they log "no server is registered"). Ctrl-C the terminal instead. Everything in this note is dev-only — a normal `mnemify up` has no reloader and stops all three ways.

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
- [`../LICENSE`](../LICENSE) — MIT; the whole repository, including this package, is licensed under it.
