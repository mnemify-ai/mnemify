"""Unit tests for RawStore (src/harvester/raw_store.py)."""

from __future__ import annotations

import hashlib


from src.harvester import RawDocument
from src.harvester.raw_store import RawStore, _extension, _infer_ext


# ── Extension mapping ──────────────────────────────────────────────


def test_extension_known_formats():
    assert _extension("json") == ".json"
    assert _extension("md") == ".md"
    assert _extension("xml") == ".xml"
    assert _extension("html") == ".html"


def test_extension_unknown_format_returns_bin():
    assert _extension("csv") == ".bin"
    assert _extension("") == ".bin"


def test_infer_ext_from_filename():
    assert _infer_ext("photo.png") == ".png"
    assert _infer_ext("archive.tar") == ".tar"
    assert _infer_ext("document.pdf") == ".pdf"


def test_infer_ext_no_extension_returns_bin():
    assert _infer_ext("noextension") == ".bin"
    assert _infer_ext("") == ".bin"


# ── path_for ───────────────────────────────────────────────────────


def test_path_for_uses_two_char_shard(tmp_path):
    store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    source_id = "abcdef1234567890"
    path = store.path_for("notion", source_id, "json")
    assert path == tmp_path / "raw" / "notion" / "ab" / f"{source_id}.json"


def test_path_for_short_id(tmp_path):
    store = RawStore(tmp_path / "raw")
    path = store.path_for("notion", "xy", "md")
    assert path == tmp_path / "raw" / "notion" / "xy" / "xy.md"


# ── write ──────────────────────────────────────────────────────────


def test_write_creates_file_at_expected_path(tmp_path):
    store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    source_id = "abcdef1234567890"
    raw = RawDocument(
        source_id=source_id,
        title="Test Page",
        content=b'{"page": {}}',
        format="json",
    )
    written = store.write("notion", source_id, raw)

    assert written.exists()
    assert written == store.path_for("notion", source_id, "json")
    assert written.read_bytes() == b'{"page": {}}'


def test_write_is_atomic_uses_os_replace(tmp_path, monkeypatch):
    """os.replace must be called — ensure no partial writes are visible."""
    replaced: list[tuple] = []
    original_replace = __import__("os").replace

    def tracking_replace(src, dst):
        replaced.append((src, dst))
        original_replace(src, dst)

    monkeypatch.setattr("os.replace", tracking_replace)

    store = RawStore(tmp_path / "raw")
    raw = RawDocument(source_id="aabbcc", title="T", content=b"data", format="json")
    store.write("notion", "aabbcc", raw)

    assert len(replaced) == 1
    # tmp file name contains ".tmp_"
    assert ".tmp_" in replaced[0][0]


def test_write_overwrites_existing_file(tmp_path):
    store = RawStore(tmp_path / "raw")
    source_id = "aabbccdd"
    raw1 = RawDocument(source_id=source_id, title="T", content=b"v1", format="json")
    raw2 = RawDocument(source_id=source_id, title="T", content=b"v2", format="json")
    store.write("notion", source_id, raw1)
    store.write("notion", source_id, raw2)

    path = store.path_for("notion", source_id, "json")
    assert path.read_bytes() == b"v2"


def test_write_creates_shard_directory_on_demand(tmp_path):
    store = RawStore(tmp_path / "raw")
    source_id = "xxyyzz"
    raw = RawDocument(source_id=source_id, title="T", content=b"hello", format="md")
    store.write("notion", source_id, raw)

    shard_dir = tmp_path / "raw" / "notion" / "xx"
    assert shard_dir.is_dir()


# ── write_attachment ───────────────────────────────────────────────


def test_write_attachment_creates_file(tmp_path):
    store = RawStore(tmp_path / "raw")
    parent_id = "abcdef1234567890"
    att_bytes = b"\x89PNG\r\n\x1a\n fake"
    path = store.write_attachment("notion", parent_id, att_bytes, "photo.png")

    assert path.exists()
    assert path.read_bytes() == att_bytes
    assert path.suffix == ".png"
    # Must be inside the parent's shard dir
    assert path.parts[-3] == parent_id
    assert path.parts[-2] == "attachments"


def test_write_attachment_uses_content_hash_name(tmp_path):
    store = RawStore(tmp_path / "raw")
    att_bytes = b"some image data"
    expected_hash = hashlib.sha256(att_bytes).hexdigest()[:16]
    path = store.write_attachment("notion", "aabbcc", att_bytes, "img.jpg")

    assert path.stem == expected_hash


def test_write_attachment_skips_rewrite_if_exists(tmp_path, monkeypatch):
    """Re-writing same content does not call _atomic_write again."""
    writes: list[int] = []
    from src.harvester import raw_store as rs_module

    original = rs_module._atomic_write

    def tracking_write(target, data):
        writes.append(1)
        original(target, data)

    monkeypatch.setattr(rs_module, "_atomic_write", tracking_write)

    store = RawStore(tmp_path / "raw")
    att_bytes = b"same bytes"
    store.write_attachment("notion", "aabbcc", att_bytes, "file.png")
    store.write_attachment("notion", "aabbcc", att_bytes, "file.png")

    assert writes == [1]  # second call skipped


# ── delete ─────────────────────────────────────────────────────────


def test_delete_removes_raw_file(tmp_path):
    store = RawStore(tmp_path / "raw")
    source_id = "aabbccdd"
    raw = RawDocument(source_id=source_id, title="T", content=b"data", format="json")
    path = store.write("notion", source_id, raw)
    assert path.exists()

    store.delete("notion", source_id)
    assert not path.exists()


def test_delete_noop_when_file_missing(tmp_path):
    store = RawStore(tmp_path / "raw")
    # Should not raise
    store.delete("notion", "notexist")


def test_delete_removes_attachments_dir(tmp_path):
    store = RawStore(tmp_path / "raw")
    parent_id = "aabbccdd11223344"
    att_bytes = b"attachment data"
    att_path = store.write_attachment("notion", parent_id, att_bytes, "file.bin")
    assert att_path.exists()

    store.delete("notion", parent_id)
    att_dir = att_path.parent
    assert not att_dir.exists()


# ── converter_version ──────────────────────────────────────────────


def test_converter_version_stored_on_instance(tmp_path):
    store = RawStore(tmp_path / "raw", converter_version="1.2.3")
    assert store.converter_version == "1.2.3"
