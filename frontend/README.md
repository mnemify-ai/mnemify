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

The dev server needs the backend running too — start it from the repo root with
`./run.sh --dev` (brings up both), or `mnemify up` in `backend/`. With no
backend, the brain map and the connect/harvest screens just sit on a "couldn't
reach the backend" / "nothing compiled yet" state — nothing breaks, the live bits
are inert.

There's no bundled demo dataset: the 3D map fetches the compiled terrain from
`GET /api/terrain/render-data`. A fresh install (nothing compiled) shows the
connect → harvest → compile onboarding screen.

## More

- [`../docs/FRONTEND.md`](../docs/FRONTEND.md) — the architecture in depth: stack, folder layout, where data comes from, routes, the page map, the BrainMap props, the wizards, the harvest/compile SSE wire protocol, the theme system.
- [`../docs/TECHNICAL.md`](../docs/TECHNICAL.md) — the end-to-end data flow (connect → harvest → compile → brain map) and the SSE architecture.
- [`../docs/ROADMAP.md`](../docs/ROADMAP.md) — the product/UX menu for what's next.
