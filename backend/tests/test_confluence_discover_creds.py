"""``POST /connections/confluence/discover`` must never pair a caller-chosen
``base_url`` with the *saved* email/token: that would post the user's
credentials, as Basic auth, to whatever host the body named."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import create_app


@pytest.fixture
def seen(monkeypatch):
    calls: list[tuple[str, tuple | None]] = []

    class _FakeAsyncClient:
        def __init__(self, *a, auth=None, **k):
            self._auth = auth

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **k):
            calls.append((url, self._auth))
            return httpx.Response(200, json={"results": [], "size": 0})

    monkeypatch.setattr("src.api.routes_connections.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setenv("CONFLUENCE_EMAIL", "me@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "saved-token")
    return calls


def test_base_url_alone_is_refused(tmp_path, seen):
    c = TestClient(create_app())
    r = c.post("/api/connections/confluence/discover", json={"base_url": "https://attacker.example"})
    assert r.status_code == 400
    assert seen == []  # no request left the machine


def test_partial_triples_are_refused(tmp_path, seen):
    c = TestClient(create_app())
    for body in (
        {"base_url": "https://x.atlassian.net", "email": "me@example.com"},
        {"token": "t"},
        {"email": "me@example.com", "token": "t"},
    ):
        assert c.post("/api/connections/confluence/discover", json=body).status_code == 400
    assert seen == []


def test_full_triple_from_the_caller_is_used_as_given(tmp_path, seen):
    c = TestClient(create_app())
    body = {"base_url": "https://x.atlassian.net/", "email": "a@b.c", "token": "pasted"}
    assert c.post("/api/connections/confluence/discover", json=body).status_code == 200
    assert seen and seen[0][1] == ("a@b.c", "pasted")
    assert seen[0][0].startswith("https://x.atlassian.net/rest/api/space")
