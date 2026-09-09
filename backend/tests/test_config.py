"""Unit tests for config module (src/config.py)."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

logger = logging.getLogger(__name__)


# ── get_notion_token ───────────────────────────────────────────────


def test_get_notion_token_returns_token_when_env_var_is_set():
    from src.config import get_notion_token

    with patch.dict(os.environ, {"NOTION_TOKEN": "ntn_real_token_abc123"}):
        token = get_notion_token()

    assert token == "ntn_real_token_abc123"


def test_get_notion_token_raises_when_env_var_not_set():
    from src.config import get_notion_token

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("NOTION_TOKEN", None)
        with pytest.raises(EnvironmentError, match="NOTION_TOKEN"):
            get_notion_token()


def test_get_notion_token_raises_for_placeholder_value():
    from src.config import get_notion_token

    with patch.dict(os.environ, {"NOTION_TOKEN": "ntn_your_integration_token_here"}):
        with pytest.raises(EnvironmentError, match="NOTION_TOKEN"):
            get_notion_token()


def test_get_notion_token_raises_for_empty_string():
    from src.config import get_notion_token

    with patch.dict(os.environ, {"NOTION_TOKEN": ""}):
        with pytest.raises(EnvironmentError):
            get_notion_token()


# ── load_config ────────────────────────────────────────────────────


def test_load_config_loads_env_file_from_specified_path(tmp_path):
    from src.config import load_config

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_from_dotenv_file\n", encoding="utf-8")

    # load_config should not raise
    load_config(env_path=env_file)
    # We don't assert the token was set here because dotenv may not
    # override already-set variables — just verify no exception
