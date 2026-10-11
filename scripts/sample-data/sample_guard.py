"""The one check every sample-data script runs before touching a Mnemify home.

The scripts write a fictional company into a manifest, a workspace database
and, through export.py, into the committed frontend/web/public/demo. Pointed at
a real home they would mix fiction into someone's knowledge base, or copy
their real documents into the repo. So a home is only accepted when:

* MNEMIFY_HOME is set explicitly, and MNEMIFY_ENV_FILE / MNEMIFY_YAML_FILE
  (which override it) are not;
* it is not the platform default home or anywhere inside this repo (the
  legacy backend/.mnemify holds a developer's real data);
* it carries the SENTINEL file. seed.py creates it, and only in a directory
  that is new or empty.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SENTINEL = ".mnemify-sample"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def corpus_dir() -> Path:
    """Where the sample corpus lives. It stays out of the repo (only the slim
    export in frontend/web/public/demo is committed): MNEMIFY_SAMPLE_CORPUS,
    else a `sample-corpus` folder next to the repo checkout."""
    raw = os.environ.get("MNEMIFY_SAMPLE_CORPUS")
    path = Path(raw).expanduser().resolve() if raw else REPO.parent / "sample-corpus"
    if not (path / "notion").is_dir():
        _fail(f"no sample corpus at {path}; set MNEMIFY_SAMPLE_CORPUS (see scripts/sample-data/README.md).")
    return path


def _fail(msg: str) -> None:
    sys.exit(f"sample-data: {msg}")


def _platform_default() -> Path | None:
    try:
        sys.path.insert(0, str(REPO / "backend"))
        from src import paths

        return Path(paths.platform_default()).expanduser().resolve()
    except Exception:  # noqa: BLE001
        return None


def scratch_home(*, create: bool = False) -> Path:
    """The validated scratch home. With `create`, a new or empty directory is
    initialised (sentinel written); otherwise the sentinel must exist."""
    raw = os.environ.get("MNEMIFY_HOME")
    if not raw:
        _fail("set MNEMIFY_HOME to a scratch directory (see scripts/sample-data/README.md).")
    for var in ("MNEMIFY_ENV_FILE", "MNEMIFY_YAML_FILE"):
        if os.environ.get(var):
            _fail(f"unset {var}: it overrides MNEMIFY_HOME and could point at real data.")
    home = Path(raw).expanduser().resolve()
    repo = REPO.resolve()
    if home == repo or repo in home.parents:
        _fail(f"refusing a home inside the repo ({home}).")
    default = _platform_default()
    if default is not None and (home == default or default in home.parents):
        _fail(f"refusing Mnemify's default home ({home}); it holds real data.")
    if home == Path.home().resolve():
        _fail("refusing your home directory itself.")
    sentinel = home / SENTINEL
    if not sentinel.is_file():
        if not create:
            _fail(f"{home} is not a sample home (no {SENTINEL}); run seed.py on a new, empty directory first.")
        if home.exists() and any(home.iterdir()):
            _fail(f"{home} already exists and isn't empty; use a new directory for the sample.")
        home.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("Scratch home for scripts/sample-data. Safe to delete.\n", encoding="utf-8")
    return home


def local_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        _fail(f"refusing a non-local server ({url}); the sample server must run on this machine.")
    return url.rstrip("/")
