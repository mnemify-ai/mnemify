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
