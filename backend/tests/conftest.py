"""Shared test configuration and fixtures."""
import logging
import os


import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--mnemify-debug",
        action="store_true",
        default=False,
        help="Enable verbose debug output in tests",
    )


@pytest.fixture(autouse=True)
def configure_logging(request):
    debug = request.config.getoption("--mnemify-debug") or os.getenv(
        "MNEMIFY_DEBUG", ""
    ).lower() in ("1", "true")
    if debug:
        logging.basicConfig(level=logging.DEBUG, force=True)
    else:
        logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)

@pytest.fixture(autouse=True)
def _isolated_mnemify_home(tmp_path, monkeypatch):
    """Point every test at a throwaway MNEMIFY_HOME.

    Without this, ``src.paths.home()`` would fall through to the *legacy*
    layout on a dev machine and tests would read (or write!) the developer's
    real ``backend/.mnemify`` data. Tests that ``chdir`` into ``tmp_path`` see
    the same ``tmp_path/.mnemify`` they always did.
    """
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    # Starlette's TestClient sends ``Host: testserver``; the Host guard in
    # ``create_app`` would otherwise 403 every request in the suite.
    monkeypatch.setenv("MNEMIFY_ALLOWED_HOSTS", "testserver")


#: Every name ``/api/secrets`` can read or write. Kept as a literal so this
#: root conftest imports nothing from ``src.api`` (which would drag FastAPI,
#: the SSE buses and the scheduler into every test session's import graph).
#: ``routes_secrets.SECRET_ALLOWLIST`` is the source of truth; if the two ever
#: diverge, ``tests/test_routes_secrets.py`` asserts on the real one and fails.
_SECRET_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "NOTION_TOKEN",
    "CONFLUENCE_EMAIL",
    "CONFLUENCE_API_TOKEN",
)


@pytest.fixture(autouse=True)
def _no_ambient_secrets(monkeypatch):
    """Keep provider keys out of the environment, in both directions.

    *Before*: a developer's shell (or a ``.env`` some module loaded at import
    time) must not decide whether a test passes — "no key anywhere" has to mean
    the same thing on a laptop and in CI.

    *After*: ``credential_store.refresh()`` and ``save_secret()`` call
    ``load_dotenv(override=True)``, which assigns into ``os.environ`` directly.
    monkeypatch never saw those assignments and so cannot undo them, which is
    why the teardown pops the names itself — otherwise one test saving a key
    would quietly satisfy every later test's environment fallback.
    """
    for name in _SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in _SECRET_NAMES:
        os.environ.pop(name, None)
