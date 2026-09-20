# Mnemify Dashboard

The web app — a 3D hex map of everything you've worked on (the *compiled* terrain),
surrounded by surfaces for connecting sources, running harvests and compiles, and
browsing the results. React 18 + Vite 5 + TypeScript, TanStack Query for REST,
Three.js / `@react-three/fiber` for the brain map.

```
frontend/
└── web/                    The React app
    └── src/
        ├── app/            Pages, layouts, components, API hooks, theme
        └── brainMap/       Self-contained 3D map module (R3F + drei + N8AO + bloom)
```

## Quick start

```bash
cd web
npm install
npm run build        # → web/dist/  (the FastAPI server serves this in production)
npm run dev          # Vite on http://localhost:5173 — proxies /api/* to the backend on :8783
npm test             # Vitest
npx tsc -b           # typecheck
```

The dev server needs the backend running too — start it with `uv run mnemify up`
in `backend/`. This two-terminal setup is the *developer* path; the normal way to
run Mnemify is `sh setup.sh` at the repo root, which builds `dist/` and lets the
backend serve it from one process (see [Install](../README.md#install)). With no
backend, the brain map and the connect/harvest screens just sit on a "couldn't
reach the backend" / "nothing compiled yet" state — nothing breaks, the live bits
are inert.

There's no bundled demo dataset: the 3D map fetches the compiled terrain from
`GET /api/terrain/render-data`. A fresh install (nothing compiled) shows the
connect → harvest → compile onboarding screen.

## More

- [`../AGENTS.md`](../AGENTS.md) — code orientation: the app's folder layout, how it talks to `/api/*`, the end-to-end harvest → compile → map flow.
- [`../LICENSE`](../LICENSE) — MIT; the whole repository, including this package, is licensed under it.
