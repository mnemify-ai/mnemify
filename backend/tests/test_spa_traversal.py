"""The SPA fallback must never serve a file from outside the built bundle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import create_app


def _client_with_dist(tmp_path, monkeypatch) -> tuple[TestClient, object]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>")
    (dist / "robots.txt").write_text("robots")
    (tmp_path / "secret.txt").write_text("SECRET")
    monkeypatch.setenv("MNEMIFY_WEB_DIST", str(dist))
    return TestClient(create_app()), dist


def test_files_inside_dist_are_served(tmp_path, monkeypatch):
    client, _ = _client_with_dist(tmp_path, monkeypatch)
    assert client.get("/robots.txt").text == "robots"
    assert "INDEX" in client.get("/").text
    assert "INDEX" in client.get("/some/spa/route").text


def test_dot_segments_cannot_escape_dist(tmp_path, monkeypatch):
    client, _ = _client_with_dist(tmp_path, monkeypatch)
    # Raw ASGI scope: uvicorn does not normalise dot-segments, so neither does
    # TestClient here — the path reaches the route as written.
    import anyio

    async def go():
        app = client.app
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/../secret.txt",
            "raw_path": b"/../secret.txt",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 8783),
        }
        await app(scope, receive, send)
        return sent

    sent = anyio.run(go)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"SECRET" not in body
    assert b"INDEX" in body
