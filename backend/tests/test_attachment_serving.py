"""Attachment bytes are author-controlled and served on the API origin, so an
HTML or SVG attachment rendered inline would run script against ``/api``."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import paths
from src.api import create_app
from src.harvester.manifest import HarvestManifest


@pytest.fixture
def doc_with_attachments(tmp_path):
    data = paths.data_dir()
    # RawStore layout: raw/{source}/{shard}/{id}.json + raw/{source}/{shard}/{id}/attachments/
    shard = data / "raw" / "notion" / "ab"
    att = shard / "abc123" / "attachments"
    att.mkdir(parents=True)
    raw_file = shard / "abc123.json"
    raw_file.write_text("{}")
    (att / "deadbeef.html").write_text("<script>fetch('/api/secrets')</script>")
    (att / "cafe.svg").write_text("<svg onload=alert(1)></svg>")
    (att / "feed.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (att / "f00d.pdf").write_bytes(b"%PDF-1.4")
    m = HarvestManifest(data / "harvest-manifest.db")
    try:
        doc_id = m.upsert_document(
            source_type="notion",
            source_id="abc123",
            title="t",
            content_hash="h",
            source_modified="2026-01-01T00:00:00+00:00",
            raw_path=str(raw_file),
        )[0]
    finally:
        m.close()
    return TestClient(create_app()), doc_id


def _get(c, doc_id, name, inline=True):
    return c.get(f"/api/documents/{doc_id}/attachments/{name}", params={"inline": int(inline)})


def test_html_and_svg_are_never_served_inline_or_as_their_own_type(doc_with_attachments):
    c, doc_id = doc_with_attachments
    for name in ("deadbeef.html", "cafe.svg"):
        r = _get(c, doc_id, name)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/octet-stream")
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in r.headers["content-security-policy"]


def test_passive_types_may_be_inline(doc_with_attachments):
    c, doc_id = doc_with_attachments
    r = _get(c, doc_id, "f00d.pdf")
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in r.headers  # would break Chrome's PDF viewer
    r = _get(c, doc_id, "feed.png")
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["content-disposition"].startswith("inline")


def test_download_keeps_the_real_type_for_passive_files(doc_with_attachments):
    c, doc_id = doc_with_attachments
    r = _get(c, doc_id, "f00d.pdf", inline=False)
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("attachment")
