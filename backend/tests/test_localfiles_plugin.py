"""Tests for LocalFilesHarvesterPlugin — SourcePlugin contract + text extraction.

Runs against a temp folder built per test. The PDF fixture is written by
hand (a minimal single-page PDF with a text stream) so no binary lives in
the repo and no PDF writer is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harvester import DocRef, HealthStatus, RawDocument, SourcePlugin
from src.harvester.localfiles.extract import NoTextLayerError, pdf_to_markdown
from src.harvester.localfiles.models import (
    LocalFilesConfig,
    LocalRoot,
    root_key,
    roots_from_scope_ids,
)
from src.harvester.localfiles.plugin import LocalFilesHarvesterPlugin, file_id
from src.harvester.localfiles.scanner import SUPPORTED_EXTENSIONS, format_for


def minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF whose only content is ``text`` in Helvetica."""
    stream = f"BT /F1 18 Tf 40 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def blank_pdf() -> bytes:
    """A valid PDF with a page but no text at all (stands in for a scan)."""
    return minimal_pdf("").replace(b"(", b"%(", 1)  # comment out the Tj line


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "notes").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "notes" / "meeting.md").write_text(
        "---\ntitle: Weekly sync\n---\n\n# Notes\n\nDiscussed the roadmap.\n"
    )
    (tmp_path / "notes" / "todo.txt").write_text("- ship local files\n- write tests\n")
    (tmp_path / "reports" / "q3.pdf").write_bytes(minimal_pdf("Quarterly customer report"))
    (tmp_path / "reports" / "scan.pdf").write_bytes(blank_pdf())
    (tmp_path / "reports" / "photo.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "reports" / "data.csv").write_text("a,b\n1,2\n")
    (tmp_path / ".git" / "HEAD.md").write_text("ref: refs/heads/main\n")
    (tmp_path / "node_modules" / "pkg" / "README.md").write_text("# dep\n")
    (tmp_path / "untitled.md").write_text("just a body, no heading\n")
    return tmp_path


@pytest.fixture
def plugin(folder: Path) -> LocalFilesHarvesterPlugin:
    return LocalFilesHarvesterPlugin(LocalFilesConfig(root_path=str(folder)))


# ── contract ─────────────────────────────────────────────────────

def test_is_source_plugin():
    assert issubclass(LocalFilesHarvesterPlugin, SourcePlugin)


def test_supported_extensions_cover_the_release_promise():
    assert {".md", ".txt", ".pdf"} <= set(SUPPORTED_EXTENSIONS)
    assert format_for(Path("x.PDF")) == "pdf"
    assert format_for(Path("x.png")) is None


# ── test_connection ───────────────────────────────────────────────

async def test_connection_counts_supported_files(plugin):
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy
    assert health.source_type == "localfiles"
    assert health.details["file_count"] == 5
    assert health.details["by_format"] == {"md": 2, "txt": 1, "pdf": 2}


async def test_connection_missing_folder():
    p = LocalFilesHarvesterPlugin(LocalFilesConfig(root_path="/nonexistent/mnemify-xyz"))
    health = await p.test_connection()
    assert not health.healthy
    assert "not found" in health.message.lower()


async def test_connection_does_not_require_obsidian_marker(folder):
    assert not (folder / ".obsidian").exists()
    health = await LocalFilesHarvesterPlugin(LocalFilesConfig(root_path=str(folder))).test_connection()
    assert health.healthy


# ── list_documents ────────────────────────────────────────────────

async def test_list_documents_skips_unsupported_and_hidden(plugin, folder):
    docs = await plugin.list_documents()
    rel = sorted(d.metadata["relative_path"] for d in docs)
    assert rel == [
        "notes/meeting.md",
        "notes/todo.txt",
        "reports/q3.pdf",
        "reports/scan.pdf",
        "untitled.md",
    ]
    for d in docs:
        assert isinstance(d, DocRef)
        assert d.source_type == "localfiles"
        assert d.source_id == file_id(root_key(str(folder)), d.metadata["relative_path"])
        assert d.metadata["root_path"] == root_key(str(folder))
        assert d.modified_at is not None


async def test_titles_from_frontmatter_or_stem(plugin):
    by_path = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    assert by_path["notes/meeting.md"].title == "Weekly sync"
    assert by_path["notes/todo.txt"].title == "todo"
    assert by_path["reports/q3.pdf"].title == "q3"
    assert by_path["untitled.md"].title == "untitled"


async def test_folder_metadata_feeds_container_clustering(plugin):
    by_path = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    assert by_path["notes/meeting.md"].metadata["folder"] == "notes"
    assert by_path["untitled.md"].metadata["folder"] == ""


async def test_watch_folders_restrict_scope(folder):
    cfg = LocalFilesConfig(root_path=str(folder), watch_folders=["reports"])
    docs = await LocalFilesHarvesterPlugin(cfg).list_documents()
    assert {d.metadata["relative_path"] for d in docs} == {"reports/q3.pdf", "reports/scan.pdf"}
    assert all(d.metadata["origin_scope_id"] == f"{root_key(str(folder))}::reports" for d in docs)


async def test_single_files_in_scope(folder):
    cfg = LocalFilesConfig(
        root_path=str(folder),
        watch_folders=["reports", "file:notes/todo.txt", "file:reports/q3.pdf"],
    )
    docs = await LocalFilesHarvesterPlugin(cfg).list_documents()
    by_path = {d.metadata["relative_path"]: d for d in docs}
    # The folder brings both PDFs; the explicit txt is added; q3 is not doubled.
    assert set(by_path) == {"reports/q3.pdf", "reports/scan.pdf", "notes/todo.txt"}
    rk = root_key(str(folder))
    assert by_path["notes/todo.txt"].metadata["origin_scope_id"] == f"{rk}::file:notes/todo.txt"
    assert by_path["reports/q3.pdf"].metadata["origin_scope_id"] == f"{rk}::file:reports/q3.pdf"
    assert by_path["reports/scan.pdf"].metadata["origin_scope_id"] == f"{rk}::reports"


async def test_missing_single_file_is_skipped(folder):
    cfg = LocalFilesConfig(root_path=str(folder), watch_folders=["file:nope.md"])
    assert await LocalFilesHarvesterPlugin(cfg).list_documents() == []


async def test_ignore_patterns(folder):
    cfg = LocalFilesConfig(root_path=str(folder), ignore_patterns=["reports/*", "*.txt"])
    docs = await LocalFilesHarvesterPlugin(cfg).list_documents()
    assert {d.metadata["relative_path"] for d in docs} == {"notes/meeting.md", "untitled.md"}


# ── fetch + normalize ─────────────────────────────────────────────

async def test_markdown_passthrough(plugin):
    docs = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    raw = await plugin.fetch_document(docs["notes/meeting.md"])
    assert isinstance(raw, RawDocument)
    assert raw.format == "md"
    norm = plugin.normalize(raw)
    assert norm.normalizer_version == "0.1.0-passthrough"
    assert "Discussed the roadmap." in norm.markdown


async def test_text_passthrough(plugin):
    docs = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    raw = await plugin.fetch_document(docs["notes/todo.txt"])
    assert raw.format == "txt"
    assert plugin.normalize(raw).markdown.startswith("- ship local files")


async def test_pdf_is_extracted_to_markdown(plugin):
    docs = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    raw = await plugin.fetch_document(docs["reports/q3.pdf"])
    assert raw.format == "pdf"
    assert raw.content.startswith(b"%PDF")
    norm = plugin.normalize(raw)
    assert norm.normalizer_version == "0.1.0-pypdf"
    assert "Quarterly customer report" in norm.markdown


async def test_scanned_pdf_raises_instead_of_compiling_blank(plugin):
    docs = {d.metadata["relative_path"]: d for d in await plugin.list_documents()}
    raw = await plugin.fetch_document(docs["reports/scan.pdf"])
    with pytest.raises(NoTextLayerError):
        plugin.normalize(raw)


def test_pdf_to_markdown_joins_pages_and_tidies_whitespace():
    md = pdf_to_markdown(minimal_pdf("Hello   local   PDF"))
    assert md.strip() == "Hello local PDF"


# ── multiple roots ───────────────────────────────────────────────

async def test_two_roots_same_relative_path_do_not_collide(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    for r in (a, b):
        (r / "notes").mkdir(parents=True)
        (r / "notes" / "same.md").write_text(f"# in {r.name}\n")
    cfg = LocalFilesConfig(roots=[LocalRoot(path=str(a)), LocalRoot(path=str(b), watch_folders=["notes"])])
    plugin = LocalFilesHarvesterPlugin(cfg)
    health = await plugin.test_connection()
    assert health.healthy and health.details["file_count"] == 2
    assert len(health.details["roots"]) == 2
    docs = await plugin.list_documents()
    assert len({d.source_id for d in docs}) == 2
    assert {d.title for d in docs} == {"in a", "in b"}
    origins = {d.metadata["root_name"]: d.metadata["origin_scope_id"] for d in docs}
    assert origins["a"] == f"{root_key(str(a))}::"
    assert origins["b"] == f"{root_key(str(b))}::notes"
    raw = await plugin.fetch_document(next(d for d in docs if d.metadata["root_name"] == "b"))
    assert b"in b" in raw.content


async def test_missing_root_reported_not_fatal(folder):
    cfg = LocalFilesConfig(roots=[LocalRoot(path=str(folder)), LocalRoot(path="/nope/gone")])
    plugin = LocalFilesHarvesterPlugin(cfg)
    assert not (await plugin.test_connection()).healthy
    # Listing still harvests the roots that exist.
    assert len(await plugin.list_documents()) == 5


def test_from_yaml_accepts_both_shapes(tmp_path):
    cfg = LocalFilesConfig.from_yaml({"root_path": str(tmp_path), "watch_folders": ["x"]})
    assert [r.watch_folders for r in cfg.roots] == [["x"]]
    cfg = LocalFilesConfig.from_yaml({"roots": [{"path": str(tmp_path)}, {"path": str(tmp_path / "b"), "watch_folders": ["y"]}]})
    assert cfg.scope_ids() == [f"{root_key(str(tmp_path))}::", f"{root_key(str(tmp_path / 'b'))}::y"]


def test_roots_round_trip_through_scope_ids(tmp_path):
    a = LocalRoot(path=str(tmp_path / "a"), ignore_patterns=["*.bak"])
    b = LocalRoot(path=str(tmp_path / "b"), watch_folders=["n", "file:n/x.md"])
    ids = LocalFilesConfig(roots=[a, b]).scope_ids()
    back = roots_from_scope_ids(ids, [a, b])
    assert [(r.key, r.watch_folders, r.ignore_patterns) for r in back] == [
        (a.key, [], ["*.bak"]),
        (b.key, ["n", "file:n/x.md"], []),
    ]
    # Dropping every id of a root unlinks it.
    assert [r.key for r in roots_from_scope_ids(ids[1:], [a, b])] == [b.key]


# ── registry ──────────────────────────────────────────────────────

def test_registered_with_plugin_registry(folder):
    import src.harvester.localfiles  # noqa: F401 — import registers
    from src.harvester.registry import create_plugin

    plugin, client = create_plugin("localfiles", {"roots": [{"path": str(folder)}]})
    assert isinstance(plugin, LocalFilesHarvesterPlugin)
    assert client is None
