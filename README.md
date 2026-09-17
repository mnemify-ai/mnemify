<p align="center">
  <img src="assets/logo.png" alt="Mnemify — Your knowledge. A world you can explore." width="100%">
</p>

<h3 align="center">Built for us. Shared with everyone who works like us.</h3>

<p align="center">
  <a href="https://mnemify.ai"><img alt="Website" src="https://img.shields.io/badge/website-mnemify.ai-8b2e4a?style=flat-square"></a>
  <a href="https://github.com/mnemify-ai/mnemify/releases"><img alt="Version" src="https://img.shields.io/badge/version-v1.0.0-1f6feb?style=flat-square"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-6a994e?style=flat-square"></a>
  <a href="backend/pyproject.toml"><img alt="Python" src="https://img.shields.io/badge/python-%3E%3D3.11-3776ab?style=flat-square&logo=python&logoColor=white"></a>
  <a href="frontend/web/package.json"><img alt="Node" src="https://img.shields.io/badge/node-%3E%3D18-339933?style=flat-square&logo=node.js&logoColor=white"></a>
  <a href="https://github.com/mnemify-ai/mnemify/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/mnemify-ai/mnemify?style=flat-square&color=e0a03a"></a>
</p>

<br>

<p align="center">
  <a href="https://github.com/user-attachments/assets/2bf6614e-cd72-4a0c-9ea2-017d22d91155">
    <img src="assets/demo.gif" alt="Mnemify demo: navigating the 3D knowledge map and chatting over it" width="100%">
  </a>
</p>

<p align="center"><sub>Click the preview to watch the full-resolution demo.</sub></p>

Our knowledge was scattered across Notion, Confluence, Jira, Obsidian, Google meeting notes, Slack threads, and more. We built Mnemify to bring it together into one connected, searchable map — and we use it every day to rediscover what we know and give our AI tools better context.

After several months of heavy daily use, we're sharing it with you.

## How it works

Mnemify is **AI context infrastructure**: a portable, persistent knowledge graph built from the tools you already work in. It runs in three tiers:

1. **Harvest** — pull your documents from Notion, Confluence, Jira, Obsidian, Gmail, Calendar, Slack, and GitHub into native formats, deduplicated by content hash. Deterministic; no LLM.
2. **Compile** — chunk, tag, semantically cluster, and lay out the harvested content into an emergent terrain: regions and peaks are based on embedding proximity, not a fixed folder taxonomy.
3. **Surface** — a FastAPI server + a React app: a 3D hex map of everything you've worked on, source-grounded attention signals, chat over the compiled terrain graph, and JSON artifacts downstream AI clients can use as compact context.

Everything Mnemify generates lives in a local `.mnemify/` folder on your machine. Nothing is written back to your sources.

---

## Run it

You need **[uv](https://docs.astral.sh/uv/)** (it installs Python 3.11+ for you if needed) and **Node.js 18+**. These commands work the same on Windows, macOS, and Linux — from the repo root:

```bash
cd backend
uv sync                                   # creates .venv/ and installs the backend + the `mnemify` CLI
uv run mnemify up --port 8783 --reload --no-browser
```

```bash
cd frontend/web
npm install
npm run dev          # Vite dev server on http://localhost:5173, proxies /api/* to :8783
```

Open **http://localhost:5173**. Both processes need to be running side by side (two terminals); `Ctrl-C` stops each.

To serve everything from one process instead (no HMR), build the web app once and let the backend host it:

```bash
cd frontend/web && npm run build          # → frontend/web/dist
cd ../../backend && uv run mnemify up     # http://127.0.0.1:8783 serves the API + the built app
```

`uv run mnemify …` and `uv run python -m src …` are equivalent.

### Credentials

Most of the setup happens in the app. Open **Build → Sources** and the connect wizard for each source walks you through pasting a token, validating it, and choosing what to harvest. Notion and Confluence tokens are saved to `backend/.env` for you; Obsidian just needs a vault path. A few sources still need a manual step:

```bash
cp backend/.env.template backend/.env
```

- `JIRA_EMAIL` / `JIRA_API_TOKEN` — your Atlassian cloud email + an [API token](https://id.atlassian.com/manage-profile/security/api-tokens).
- `SLACK_USER_TOKEN` — a Slack user OAuth token (`xoxp-…`) from your own Slack App (steps in `.env.template`).
- `GITHUB_TOKEN` — a fine-grained GitHub personal access token (`github_pat_…`) scoped to the repos you want to harvest.
- **Gmail / Calendar** use Google OAuth: drop your Google Cloud `oauth_client.json` at `backend/src/harvester/_google/oauth_client.json`, then run `mnemify login --source gmail` / `--source calendar`. Full steps are in `.env.template`.

Tokens only ever live in `.env`, never in `mnemify.yaml` and never in the repo.

### AI models

The **Compile** step and **Chat** need a language model. You have three options, and Mnemify picks up whichever you have:

- **OpenAI** (recommended) — set `OPENAI_API_KEY` in `backend/.env`. This is the default mode and the one we run day to day.
- **Claude Code** — if the `claude` CLI is installed and logged in, Mnemify detects it automatically and can use your Claude subscription for compile (`--ai-mode claude`) and chat, no API key needed. An Anthropic API key (`ANTHROPIC_API_KEY`, `--ai-mode anthropic`) works too.
- **Local** — `--ai-mode local` compiles deterministically with no key and no network. Good for a first look; the map is much better with a real model.

Even with Claude, keep an `OPENAI_API_KEY` set: embeddings for chunking and clustering always run through OpenAI, so every mode except local needs it. Model and mode can be changed later under **Settings → AI & Models**.

### Then

Open the app → **Build → Sources**, connect a source, run a **harvest**, then a **compile**. The home page turns into a living map of everything you've worked on. (Until you compile, it shows the connect → harvest → compile onboarding screen.)

The first harvest and compile take a while. After that the results are cached, so later runs are much faster.

---

## What it does (and doesn't)

Mnemify is **read-only**. It never edits Notion, Confluence, Jira, or any other source, and it never creates tasks or writes comments back. Your source pages stay the system of record; Mnemify is the map on top of them.

On top of the semantic map, Mnemify pulls out **attention signals** straight from your content — todos, risks, decisions, open questions, owners, and recent changes — and rolls them up into an urgency score for every region and topic. Flip the map into the **Burning** overlay and the same terrain is tinted by what needs attention, without the geography changing under you. Clicking a region or tag shows its summary, active documents, and every signal behind it, each linked back to the source page.

**Chat** works over the compiled map rather than over raw documents: it starts from regions, topics, entities, and attention signals, then cites only the source passages it needs to ground an answer. That keeps context small and fast, and it's the same compact context Mnemify can hand to your other AI tools.

---

## Contributing

Issues and pull requests are welcome. [`AGENTS.md`](AGENTS.md) is the orientation guide for anyone working on the code, and each package has its own README ([`backend/`](backend/README.md), [`frontend/`](frontend/README.md)) with setup, commands, and tests.

## License

[MIT](LICENSE) — open source. Use it at work, modify it, redistribute it, and build products on top of it. Just keep the copyright notice.
