# scripts/

Implementation behind the four entry points at the repo root. Nothing in here
is meant to be run directly (except `install.sh` / `install.ps1`, which are
served from a URL) — run `setup.sh` / `setup.bat` or `mnemify.sh` / `mnemify.bat`
from the repo root instead.

| File | What it is |
|---|---|
| `setup.ps1` | Windows mirror of `setup.sh`. Called by `setup.bat`. |
| `mnemify.ps1` | Windows mirror of `mnemify.sh`. Called by `mnemify.bat` and by the shortcut. |
| `make-launcher.sh` | Creates `Mnemify.app` (macOS) or `mnemify.desktop` (Linux). |
| `make-launcher.ps1` | Creates `Mnemify.lnk` on the Desktop and in the Start Menu. |
| `install.sh` | What `curl -fsSL …/scripts/install.sh \| sh` runs: clone or pull, then `setup.sh`. |
| `install.ps1` | What `irm …/scripts/install.ps1 \| iex` runs: clone or pull, then `setup.ps1`. |

## Rules these files live by

- **`setup.*` is idempotent.** Re-running it is the update path, so every step
  has to be safe to repeat.
- **`mnemify.*` is dumb.** No git, no network, no updates, no port logic. It
  fixes up `PATH`, checks that setup has run, and hands over to `mnemify up`.
  The server owns the port, the "already running" case, the browser, and the
  idle shutdown.
- **No `MNEMIFY_HOME` logic in shell.** `backend/src/paths.py` is the only place
  that decides where data lives.
- **Launchers hardcode this checkout's absolute path.** Move or rename the
  folder and the icon breaks — re-run `setup.sh` from the new location.
- **Nothing changes a system setting.** The Windows `.bat` wrappers pass
  `-ExecutionPolicy Bypass` to one PowerShell process; the macOS quarantine step
  clears a per-file attribute on files the user downloaded, nothing more.
- **Installers are chosen by their result, not their presence.** `setup.ps1`
  tries `winget install astral-sh.uv`, then re-checks whether `uv` is on PATH
  and falls back to the official `astral.sh/uv/install.ps1` if it isn't.
  winget *exists* on CI runners and locked-down machines and still fails
  there, so branching on `Get-Command winget` alone strands the install.
- **Both Windows scripts re-read the registry `Path`.** An installer that runs
  during setup writes its directory to the registry and says "restart your
  shell" — winget does this for `uv`. Processes started earlier, Explorer and
  therefore the shortcut included, keep the stale value. `setup.ps1`
  (`Update-SessionPath`) and `mnemify.ps1` both re-read `Machine` + `User`
  `Path` for that reason. Drop it from either and setup succeeds while the
  very next launch cannot find `uv`. A list of likely directories is not a
  substitute: winget picks its own, and it is not on that list.

## Passing server flags on Windows

`mnemify.bat --no-browser --port 8793` works, and `mnemify.bat` forwards `%*`
**verbatim** — do not insert a `--`, and do not type one:

| Form | Result |
|---|---|
| `mnemify.bat --no-browser --port 8793` | ✅ `$ServerArgs = --no-browser, --port, 8793` |
| `mnemify.bat -- --no-browser` | ❌ `The parameter name '' is ambiguous` |
| `powershell -File scripts\mnemify.ps1 -Gui` | ✅ the switch binds; the shortcut uses this |

A token starting with `--` is not a parameter name, so `ValueFromRemainingArguments`
on `$ServerArgs` collects it. A bare `--`, however, reaches the script through
`-File` as a parameter token with an *empty* name, and the binder rejects it
before the script body runs — which is why the `--` cannot be stripped in
PowerShell code. (`mnemify.ps1` does drop a stray `--` out of `$ServerArgs`, for
hosts that pass it through rather than rejecting it.)

## Environment overrides (mostly for tests and CI)

| Variable | Effect |
|---|---|
| `MNEMIFY_NONINTERACTIVE=1` | No prompts, and `setup` does not launch the app at the end. |
| `MNEMIFY_LAUNCHER_DIR` | Where `make-launcher` writes, instead of `~/Applications` / Desktop + Start Menu. |
| `MNEMIFY_LOG_DIR` | Where `--gui` / `-Gui` writes `launcher.log`. |
| `MNEMIFY_DIALOG_DRYRUN=1` | Log the error dialog instead of showing it (nothing to click in CI). |
| `MNEMIFY_INSTALL_DIR` | Where `install.sh` / `install.ps1` clones to. Default `~/Mnemify`. |
| `MNEMIFY_REPO_URL` | Clone from a fork instead of `mnemify-ai/mnemify`. |

`MNEMIFY_HOME`, `MNEMIFY_ENV_FILE`, `MNEMIFY_YAML_FILE` and `MNEMIFY_WEB_DIST`
are read by the app itself (`backend/src/paths.py`), not by these scripts.

## Default log locations

| | |
|---|---|
| macOS | `~/Library/Logs/Mnemify/launcher.log` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/mnemify/launcher.log` |
| Windows | `%LOCALAPPDATA%\Mnemify\logs\launcher.log` |

These are deliberately OS-conventional and independent of `MNEMIFY_HOME`: they
are about the *launch*, not about your data. One previous generation is kept as
`launcher.log.1`.
