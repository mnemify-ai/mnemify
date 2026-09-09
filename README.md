# Mnemify

> **Build for us. Used by everyone who works like us.**

Mnemify is **AI context infrastructure** — a portable, persistent knowledge graph built from the tools you already work in. It runs in three tiers:

1. **Harvest** — pull your documents from Notion, Confluence, Jira, Obsidian, Gmail, Calendar, Slack, and GitHub into native formats, deduplicated by content hash. Deterministic; no LLM.
2. **Compile** — chunk, tag, semantically cluster (via HDBSCAN), and lay out the harvested content into an emergent terrain: regions and peaks are based on embedding proximity, not a fixed folder taxonomy.
3. **Surface** — a FastAPI server + a React app: a 3D hex map of everything you've worked on, source-grounded attention signals, chat over the compiled terrain graph, and JSON artifacts downstream AI clients can use as compact context.

Everything Mnemify generates lives under `.mnemify/` (gitignored). Nothing gets written into the repo.

This repo holds the backend **and** the web app. (The marketing site lives in a separate repo.)

---

## Run it

You need **Python 3.11+** and **Node.js 18+**. These commands work the same on Windows, macOS, and Linux — from the repo root:

```bash
cd backend
pip install -e .
python -m src up --port 8783 --reload --no-browser
```

```bash
cd frontend/web
npm install
npm run dev          # Vite dev server on http://localhost:5173, proxies /api/* to :8783
```

Open **http://localhost:5173**. Both processes need to be running side by side (two terminals); `Ctrl-C` stops each.

### Shortcut for macOS / Linux / WSL / Git Bash

`run.sh` wraps both of the steps above into one command. It's a bash script, so plain Windows `cmd`/PowerShell can't run it directly — use WSL, Git Bash, or a macOS/Linux terminal instead.

```bash
./run.sh                  # build the React app once and serve everything from the
                          # backend on http://127.0.0.1:8783 — one process,
                          # no HMR. The "run and fire" mode.

./run.sh --dev            # FastAPI (auto-reload) + Vite dev server (HMR) side by
                          # side — open http://localhost:5173, Ctrl-C stops both.

./run.sh --no-browser     # don't auto-open a tab.
```

The first run installs dependencies automatically (`pip install -e backend`, `npm install`).

### Credentials

Copy the template and fill in whatever sources you want:

```bash
cp backend/.env.template backend/.env
```

- `NOTION_TOKEN` — a Notion internal-integration token (and share the pages you want to harvest with the integration).
- `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN`, `JIRA_EMAIL` / `JIRA_API_TOKEN` — Atlassian cloud email + an [API token](https://id.atlassian.com/manage-profile/security/api-tokens).
- `SLACK_USER_TOKEN` — a Slack user OAuth token (`xoxp-…`) from your own Slack App (steps in `.env.template`).
- `GITHUB_TOKEN` — a fine-grained GitHub personal access token (`github_pat_…`) scoped to the repos you want to harvest.
- **Gmail / Calendar** use Google OAuth, not a `.env` token: drop your Google Cloud `oauth_client.json` at `backend/src/harvester/_google/oauth_client.json`, then run `mnemify login --source gmail` / `--source calendar`. Full setup steps are in `.env.template`.
- **Obsidian** needs nothing — just a vault path, set in the connect wizard.
- `OPENAI_API_KEY` — only needed for the **Compile** step's OpenAI path. The compiler also has a deterministic `--ai-mode local` that needs no key and no network.

Enabled sources, scopes, and filters live in `mnemify.yaml` (copy `backend/example_mnemify.yaml` to start, or let the connect wizards in the UI write it for you). Tokens stay in `.env` — never in the YAML, never committed.

### Then

Open the app → **Settings → Connections**, connect a source, run a **harvest**, then a **compile**. The home page turns into a living map of everything you've worked on. (Until you compile, it shows the connect → harvest → compile onboarding screen.)

---

## V1 product contract

Mnemify V1 is a **read-only active knowledge terrain**. It does not edit Notion, Confluence, Jira, or source systems, and it does not create tasks or write comments back. The terrain is the semantic source of navigation truth; operational facts are overlays and panels, not folders inside the map.

The compiler emits:

- `terrain.json` — the rich v2 knowledge terrain with regions, tags, source notes, compiled summaries, graph nodes/edges, and attention signals.
- `render-data.json` — the compact v3 hex artifact used by the 3D map.
- `mocknotes.json` — source-note registry for citations and panels.

The V1 attention layer extracts source-grounded signals from harvested content:

- `todo`
- `risk`
- `decision`
- `open_question`
- `owner`
- `recent_change`

Signals roll up into `attentionScore` and `attentionLevel` on every region and tag. The frontend can switch from the normal semantic view to a **Burning** overlay, tinting the same terrain by urgency without changing geography. Region/tag panels show summaries, active docs, todos, risks, decisions, owners, recent changes, open questions, and related source pages.

Chat uses the compiled terrain graph first, not raw documents first. Retrieval seeds from regions, tags, entities, and attention signals, then only cites source notes/chunks needed for grounding. This keeps context bundles smaller and faster than dumping full documents into the model.

---

## Repo layout

```
mnemify/
├── run.sh                  # macOS/Linux/WSL one-command launcher shortcut (above)
├── README.md               # this file
├── backend/                # Python — harvester + compiler + FastAPI + the `mnemify` CLI
│   ├── src/                #   harvester/ · terrain/ (the compiler) · api/ · cli.py
│   ├── tests/              #   pytest suite (live-network tests are opt-in via env)
│   ├── pyproject.toml      #   deps + the `mnemify` console script
│   ├── .env.template       #   copy → .env
│   └── example_mnemify.yaml
├── frontend/web/           # React + Vite + TypeScript — the dashboard + 3D brain map
│   └── src/                #   app/ (pages, components, API hooks) · brainMap/ (the R3F module)
└── docs/                   # see below
```

## Docs

- [`docs/BACKEND.md`](docs/BACKEND.md) — the backend in depth: the harvester pipeline + plugin contract, the terrain compiler, the FastAPI routes, the CLI, the SQLite schemas.
- [`docs/FRONTEND.md`](docs/FRONTEND.md) — the React app: the page map, the 3D brain map module, how data flows from `/api/*`, the SSE wire protocol, the theme system.
- [`docs/TECHNICAL.md`](docs/TECHNICAL.md) — the cross-cutting view: connect → harvest → compile → v2 brain-map → v3 hex render, the event-bus/SSE architecture, the on-disk `.mnemify/` layout, the schema contracts.
- [`docs/TESTING.md`](docs/TESTING.md) — the manual end-to-end smoke test (the automated suites are `pytest -q` in `backend/` and `npm test` in `frontend/web/`).
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — the product/UX menu for what's next.
- [`docs/BACKLOG.md`](docs/BACKLOG.md) — the engineering backlog of small follow-ups.

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free to use, modify, and redistribute for any noncommercial purpose. Commercial use requires a separate agreement with the copyright holders.
