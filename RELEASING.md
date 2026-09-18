# Releasing Mnemify

Manual on purpose. Nothing is published to a registry: a release is a tag plus
notes, and users install whatever `main` is when they download it — so `main`
stays green and the tag is a bookmark people can cite.

## Cut a release

1. **Bump the version in three places** (the first two must match — CI's
   `version sync` job fails the build if they drift):
   - `backend/pyproject.toml` → `version = "X.Y.Z"`
   - `frontend/web/package.json` → `"version": "X.Y.Z"`
   - `README.md` → the `version-vX.Y.Z` shields.io badge label (hardcoded).
2. `cd backend && uv lock` — refreshes the `mnemify` entry in `uv.lock`.
3. Open a PR with those four files. Wait for both workflows:
   - `ci` — `backend (pytest)`, `frontend (tsc + vitest + build)`, `version sync`
   - `install-smoke` — `ubuntu-latest`, `macos-latest`, `windows-latest`

   The `ruff (non-blocking)` step inside `ci` is advisory and may be red.
4. Merge to `main`, then wait for both workflows to go green **on `main`**.
   `install-smoke` is the only thing that proves `setup.sh` / `setup.ps1` still
   installs on a machine with no `uv`.
5. Tag and push:

   ```sh
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

6. `gh release create vX.Y.Z --generate-notes`
7. Click the README's version badge — it links to `/releases`, empty until now.
   Confirm it lands on the release you just made.

## One-time repo setup (not done yet)

Both need admin on `mnemify-ai/mnemify`:

- **Branch protection on `main`** — Settings → Branches → rule for `main`:
  require a PR, and require all six checks from step 3 to pass.
- **Description and homepage** — both empty today:

  ```sh
  gh repo edit mnemify-ai/mnemify \
    --description "Your knowledge, as a world you can explore. Local-first, MIT." \
    --homepage https://mnemify.ai
  ```

## When `install-smoke` fails on Windows

There is no console to read — `mnemify.ps1` runs hidden. Open the failed run,
download the **`smoke-windows-latest`** artifact, and read `server.out.log` /
`server.err.log` (the server) and `launcher.log` (the launcher, when `-Gui` was
used). The job also prints the tail of each of those into the log on failure.

The most likely first failure is the `setup.ps1 -NoLaunch` step at
*installing uv*: GitHub's Windows images do not reliably provide a usable
`winget` in a non-interactive session, and `setup.ps1` prefers `winget` before
falling back to the official `irm https://astral.sh/uv/install.ps1` installer.
If that is what the log shows, fix the fallback in `scripts/setup.ps1` — do not
pre-install `uv` in the workflow, because "does setup install uv on a machine
that has none" is the thing this job exists to check.
