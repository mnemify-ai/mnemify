"""``HostGuardMiddleware`` — only requests addressed to this machine get in.

A DNS-rebinding page is same-origin to ``http://attacker.example:8783`` and
can send any header, but not forge ``Host``. So ``Host`` is the check.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import ALLOWED_HOSTS_ENV, _host_of, create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "localhost:8783", "127.0.0.1:8783", "[::1]:8783", "LOCALHOST"],
)
def test_loopback_hosts_pass(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8783", "", "10.0.0.5"])
def test_foreign_hosts_are_refused(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden host"}


def test_foreign_host_cannot_quit(client):
    r = client.post(
        "/api/system/shutdown",
        headers={"Host": "attacker.example", "X-Mnemify-Client": "web"},
    )
    assert r.status_code == 403


def test_extra_hosts_from_env(client, monkeypatch):
    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "testserver, my-laptop.lan")
    assert client.get("/api/health", headers={"Host": "my-laptop.lan:8783"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "other.lan"}).status_code == 403


def test_host_of_strips_port_and_brackets():
    assert _host_of([(b"host", b"Localhost:8783")]) == "localhost"
    assert _host_of([(b"host", b"[::1]:8783")]) == "::1"
    assert _host_of([(b"host", b"[::1]")]) == "::1"
    assert _host_of([(b"host", b"127.0.0.1")]) == "127.0.0.1"
    assert _host_of([]) == ""
