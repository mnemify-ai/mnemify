"""Page, block, and attachment extraction from Notion.

Handles:
- Listing all accessible pages (with optional "modified since" filtering)
- Fetching a single page's metadata
- Recursively fetching a page's block tree (the actual content)
- Extracting plain text from a block tree
- Scanning a block tree for image/file/pdf/video/audio blocks
- Downloading attachments to a local directory
- Generating a manifest of what was downloaded

Usage:
    async with NotionClient(token="...") as client:
        page_extractor = PageExtractor(client)
        att_extractor = AttachmentExtractor(client)

        pages = await page_extractor.list_pages()
        blocks = await page_extractor.get_page_blocks("page_id")
        markdown = page_extractor.blocks_to_markdown(blocks)

        attachments = att_extractor.find_attachments(blocks, parent_page_id="page_id")
        downloaded = await att_extractor.download_all(attachments, output_dir=Path("./temp"))
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.harvester import report_extraction_warning

from .client import NotionClient
from .models import NotionAttachment, NotionBlock, NotionPage

logger = logging.getLogger(__name__)

# Block types that contain downloadable files
FILE_BLOCK_TYPES = {"image", "file", "pdf", "video", "audio"}


class PageExtractor:
    """Extracts pages and their block content from Notion."""

    def __init__(self, client: NotionClient, max_depth: int = 10):
        """Initialize the page extractor with a client and recursion limit."""
        self.client = client
        self.max_depth = max_depth

    # ── Page listing ───────────────────────────────────────────────

    async def list_pages(self, since: datetime | None = None) -> list[NotionPage]:
        """List accessible pages.

        ``since`` is accepted for interface compatibility but ignored: Notion's
        ``/search`` endpoint has no server-side modified-since filter, so the
        only thing a ``since`` filter ever did here was drop pages client-side
        — which broke Manage Scope expansion (newly-scoped pages with old
        last_edited_time would never reach the orchestrator's per-doc Layer 1
        short-circuit). The orchestrator now deduplicates per-doc instead.
        """
        raw_results = await self.client.paginate(
            "POST",
            "/search",
            body={"filter": {"property": "object", "value": "page"}},
        )

        pages = []
        for raw in raw_results:
            page = self._parse_page(raw)
            if page.archived:
                continue
            pages.append(page)

        logger.info(f"Listed {len(pages)} pages")
        return pages

    async def get_page(self, page_id: str) -> NotionPage:
        """Fetch metadata for a single Notion page."""
        raw = await self.client.get(f"/pages/{page_id}")
        return self._parse_page(raw)

    # ── Block extraction ───────────────────────────────────────────

    async def get_page_blocks(
        self,
        page_id: str,
        depth: int = 0,
    ) -> list[NotionBlock]:
        """Recursively fetch the block tree for a page or parent block."""
        if depth > self.max_depth:
            report_extraction_warning("notion_max_depth", page_id)
            logger.warning(f"Max depth {self.max_depth} reached for block {page_id}")
            return []

        raw_blocks = await self.client.paginate(
            "GET",
            f"/blocks/{page_id}/children",
        )

        blocks = []
        for raw in raw_blocks:
            block = self._parse_block(raw)

            # Recursively fetch children if present
            if block.has_children:
                block.children = await self.get_page_blocks(block.block_id, depth + 1)

            blocks.append(block)

        if depth == 0:
            logger.info(f"Fetched {self._count_blocks(blocks)} blocks for page {page_id}")

        return blocks

    async def get_full_page(self, page_id: str) -> tuple[NotionPage, list[NotionBlock]]:
        """Fetch both page metadata and its full block tree."""
        page = await self.get_page(page_id)
        blocks = await self.get_page_blocks(page_id)
        return page, blocks

    # ── Markdown rendering ─────────────────────────────────────────

    def blocks_to_markdown(self, blocks: list[NotionBlock], indent: int = 0) -> str:
        """Render a block tree as markdown, locally — no API call.

        Replaces the previous round-trip through Notion's ``/markdown``
        endpoint. The block tree contains everything the renderer needs;
        this saves one API call per page (~25 % of the per-page API
        budget at Notion's 3 rps cap).

        Coverage is pragmatic — paragraphs, headings, bulleted/numbered
        lists (with nesting), to-dos, code, quotes, callouts, dividers,
        bookmarks, file-bearing blocks, and child page/database links
        all render to canonical markdown. The long tail (tables,
        toggles-as-details, columns, equations, mentions, synced blocks)
        falls back to a plain text-content line so we never lose the
        text — docs/BACKLOG.md tracks the full per-block backlog.

        Inline ``rich_text`` annotations (bold, italic, strikethrough,
        code, links) are emitted as markdown.
        """
        lines: list[str] = []
        list_index = 1  # for numbered lists at this nesting level
        prev_was_numbered = False

        for block in blocks:
            if block.block_type != "numbered_list_item":
                list_index = 1
                prev_was_numbered = False

            line = self._block_to_markdown_line(block, indent, list_index)
            if line is not None:
                lines.append(line)

            if block.block_type == "numbered_list_item":
                if not prev_was_numbered:
                    list_index = 2
                else:
                    list_index += 1
                prev_was_numbered = True

            if block.children and block.block_type != "table":
                # Only list-like blocks pass nesting indent to their children;
                # for structural containers (column_list, column, synced_block,
                # toggle) and section blocks (headings, callouts) children are
                # rendered flat. Without this guard, a page wrapped in two
                # levels of columns produced 4-space leading prefixes on every
                # line — which CommonMark treats as a code block, hiding all
                # headings and paragraphs from the rendered output.
                # Tables consume their own table_row children via
                # ``_render_table``, so we skip the recursion for them.
                child_indent = (
                    indent + 1
                    if block.block_type
                    in ("bulleted_list_item", "numbered_list_item", "to_do")
                    else indent
                )
                child_md = self.blocks_to_markdown(block.children, child_indent)
                if child_md:
                    lines.append(child_md)

        return "\n".join(lines)

    def _block_to_markdown_line(
        self,
        block: NotionBlock,
        indent: int,
        list_index: int,
    ) -> str | None:
        """Render a single block as one markdown line (or None to skip)."""
        prefix = "  " * indent
        bt = block.block_type
        rt = block.data.get("rich_text") if isinstance(block.data, dict) else None
        text = self._rich_text_to_markdown(rt) if rt else block.text_content

        if bt == "paragraph":
            return f"{prefix}{text}" if text else ""

        if bt == "heading_1":
            return f"\n{prefix}# {text}\n"
        if bt == "heading_2":
            return f"\n{prefix}## {text}\n"
        if bt == "heading_3":
            return f"\n{prefix}### {text}\n"

        if bt == "bulleted_list_item":
            return f"{prefix}- {text}"
        if bt == "numbered_list_item":
            return f"{prefix}{list_index}. {text}"

        if bt == "to_do":
            checked = block.data.get("checked", False) if isinstance(block.data, dict) else False
            marker = "[x]" if checked else "[ ]"
            return f"{prefix}- {marker} {text}"

        if bt == "quote":
            return f"{prefix}> {text}" if text else f"{prefix}>"

        if bt == "callout":
            icon = ""
            if isinstance(block.data, dict):
                emoji = (block.data.get("icon") or {}).get("emoji")
                if emoji:
                    icon = f"{emoji} "
            return f"{prefix}> {icon}{text}" if text else None

        if bt == "code":
            lang = block.data.get("language", "") if isinstance(block.data, dict) else ""
            return f"{prefix}```{lang}\n{prefix}{text}\n{prefix}```"

        if bt == "divider":
            return f"\n{prefix}---\n"

        if bt == "bookmark":
            url = block.data.get("url", "") if isinstance(block.data, dict) else ""
            label = block.caption or url or "bookmark"
            return f"{prefix}[{label}]({url})" if url else f"{prefix}{label}"

        if bt == "image":
            caption = block.caption or "image"
            url = block.file_url or ""
            return f"{prefix}![{caption}]({url})" if url else f"{prefix}[{caption}]"

        if bt in ("file", "pdf", "video", "audio"):
            label = block.caption or bt
            url = block.file_url or ""
            return f"{prefix}[{label}]({url})" if url else f"{prefix}[{label}]"

        if bt == "child_page":
            return f"{prefix}- 📄 {text or 'Untitled'}"
        if bt == "child_database":
            return f"{prefix}- 🗄 {text or 'Untitled'}"

        if bt == "toggle":
            # Render summary bolded; the toggle's children will render flat
            # below it via the normal recursion in blocks_to_markdown.
            return f"{prefix}**{text}**" if text else None

        if bt == "equation":
            expr = block.data.get("expression", "") if isinstance(block.data, dict) else ""
            return f"{prefix}$${expr}$$" if expr else None

        if bt == "embed":
            url = block.data.get("url", "") if isinstance(block.data, dict) else ""
            label = block.caption or text or url or "embed"
            return f"{prefix}[{label}]({url})" if url else f"{prefix}{label}"

        if bt == "table":
            return self._render_table(block, prefix)

        if bt == "table_row":
            # Consumed by the parent table renderer. Returning None here keeps
            # us from emitting a stray text-content line at the row level.
            return None

        # Structural container blocks (column_list, column, synced_block) emit
        # nothing themselves — their children render flat through the normal
        # recursion. Anything else with no handler and no text gets a warning
        # so we can spot newly introduced block types in production logs.
        if bt in ("column_list", "column", "synced_block"):
            return None
        if text:
            return f"{prefix}{text}"
        report_extraction_warning("notion_unsupported_block", bt)
        logger.warning("Notion block type %r had no handler and no text; dropping", bt)
        return None

    def _render_table(self, block: NotionBlock, prefix: str) -> str | None:
        """Render a Notion ``table`` block (whose children are ``table_row``)
        as a CommonMark pipe table.

        Cells live in ``row.data["cells"]`` as a list-of-lists of rich_text
        fragments. We flatten each cell through ``_rich_text_to_markdown``
        so inline annotations survive, escape any ``|`` characters that
        would break the pipe-table syntax, and pad short rows so the header
        and body widths match.
        """
        rows = [c for c in (block.children or []) if c.block_type == "table_row"]
        if not rows:
            return None

        def cell_texts(row: NotionBlock) -> list[str]:
            cells = row.data.get("cells") if isinstance(row.data, dict) else None
            if not isinstance(cells, list):
                return [row.text_content or ""]
            out: list[str] = []
            for cell in cells:
                if isinstance(cell, list):
                    out.append(self._rich_text_to_markdown(cell).replace("|", "\\|"))
                else:
                    out.append(str(cell or "").replace("|", "\\|"))
            return out

        grid = [cell_texts(r) for r in rows]
        cols = max((len(r) for r in grid), default=0)
        if cols == 0:
            return None
        for r in grid:
            r.extend([""] * (cols - len(r)))

        lines = [
            f"{prefix}| " + " | ".join(grid[0]) + " |",
            f"{prefix}|" + "|".join(["---"] * cols) + "|",
        ]
        for r in grid[1:]:
            lines.append(f"{prefix}| " + " | ".join(r) + " |")
        return "\n".join(lines)

    @staticmethod
    def _rich_text_to_markdown(rich_text: list[dict] | None) -> str:
        """Render a Notion ``rich_text`` array as markdown with inline annotations.

        Handles bold/italic/strikethrough/code annotations and link hrefs.
        Underline has no markdown equivalent and is dropped (the underlying
        text remains).
        """
        if not rich_text:
            return ""
        parts: list[str] = []
        for rt in rich_text:
            text = rt.get("plain_text", "")
            if not text:
                continue
            ann = rt.get("annotations") or {}
            href = rt.get("href")
            if ann.get("code"):
                text = f"`{text}`"
            if ann.get("bold"):
                text = f"**{text}**"
            if ann.get("italic"):
                text = f"*{text}*"
            if ann.get("strikethrough"):
                text = f"~~{text}~~"
            if href:
                text = f"[{text}]({href})"
            parts.append(text)
        return "".join(parts)

    # ── Serialization ──────────────────────────────────────────────

    def blocks_to_native_json(self, blocks: list[NotionBlock]) -> list[dict]:
        """Serialize a block tree into JSON-compatible dictionaries."""
        return [self._block_to_dict(b) for b in blocks]

    def _block_to_dict(self, block: NotionBlock) -> dict:
        """Serialize one block and its children into a dictionary."""
        d = {
            "block_id": block.block_id,
            "type": block.block_type,
            "text_content": block.text_content,
            "data": block.data,
        }
        if block.file_url:
            d["file_url"] = block.file_url
            d["file_type"] = block.file_type
        if block.caption:
            d["caption"] = block.caption
        if block.children:
            d["children"] = [self._block_to_dict(c) for c in block.children]
        return d

    # ── Deserialization ────────────────────────────────────────────

    @staticmethod
    def blocks_from_json(data: list[dict]) -> list[NotionBlock]:
        """Reconstruct a NotionBlock tree from serialized JSON dicts.

        This is the inverse of blocks_to_native_json(). Used by the plugin
        to round-trip through RawDocument content for extract_plain_text().
        """
        return [PageExtractor._block_from_dict(d) for d in data]

    @staticmethod
    def _block_from_dict(d: dict) -> NotionBlock:
        """Reconstruct one NotionBlock from a dictionary."""
        children = [
            PageExtractor._block_from_dict(c) for c in d.get("children", [])
        ]
        return NotionBlock(
            block_id=d.get("block_id", ""),
            block_type=d.get("type", "unsupported"),
            has_children=len(children) > 0,
            children=children,
            data=d.get("data", {}),
            text_content=d.get("text_content", ""),
            file_url=d.get("file_url"),
            file_type=d.get("file_type"),
            caption=d.get("caption", ""),
        )

    # ── Internal parsing ───────────────────────────────────────────

    def _parse_page(self, raw: dict) -> NotionPage:
        """Convert a raw Notion page payload into a NotionPage model."""
        title = self._extract_page_title(raw.get("properties", {}))

        parent = raw.get("parent", {})
        parent_type = parent.get("type", "")
        parent_id = parent.get(parent_type, "") if parent_type != "workspace" else "workspace"

        created_by_id = raw.get("created_by", {}).get("id", "")
        last_edited_by_id = raw.get("last_edited_by", {}).get("id", "")

        return NotionPage(
            page_id=raw["id"],
            title=title,
            url=raw.get("url", ""),
            created_at=self._parse_dt(raw.get("created_time")),
            modified_at=self._parse_dt(raw.get("last_edited_time")),
            parent_type=parent_type,
            parent_id=str(parent_id),
            properties=raw.get("properties", {}),
            archived=raw.get("archived", False),
            created_by_id=created_by_id,
            last_edited_by_id=last_edited_by_id,
        )

    def _parse_block(self, raw: dict) -> NotionBlock:
        """Convert a raw Notion block payload into a NotionBlock model."""
        block_type = raw.get("type", "unsupported")
        block_data = raw.get(block_type, {})

        block = NotionBlock(
            block_id=raw["id"],
            block_type=block_type,
            has_children=raw.get("has_children", False),
            data=block_data,
        )

        block.text_content = self._extract_rich_text(block_data.get("rich_text", []))

        if block_type == "child_page":
            block.text_content = block_data.get("title", "")
        elif block_type == "child_database":
            block.text_content = block_data.get("title", "")
        elif block_type == "code":
            block.text_content = self._extract_rich_text(block_data.get("rich_text", []))
            block.data["language"] = block_data.get("language", "")

        if block_type in ("image", "file", "pdf", "video", "audio"):
            file_info = block_data.get("file") or block_data.get("external")
            if file_info:
                block.file_url = file_info.get("url", "")
            block.file_type = "file" if "file" in block_data else "external"
            block.caption = self._extract_rich_text(block_data.get("caption", []))

        return block

    @staticmethod
    def _extract_rich_text(rich_text: list[dict]) -> str:
        """Flatten a Notion rich_text array into one plain string."""
        parts = []
        for rt in rich_text:
            text = rt.get("plain_text", "")
            if text:
                parts.append(text)
        return "".join(parts)

    @staticmethod
    def _extract_page_title(properties: dict) -> str:
        """Extract the title value from a page property map."""
        for prop in properties.values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_parts)
        return "Untitled"

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """Parse a Notion timestamp into a datetime when possible."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _count_blocks(self, blocks: list[NotionBlock]) -> int:
        """Count blocks recursively, including nested children."""
        count = len(blocks)
        for b in blocks:
            if b.children:
                count += self._count_blocks(b.children)
        return count


class AttachmentExtractor:
    """Finds and downloads attachments from Notion page content."""

    def __init__(self, client: NotionClient):
        """Initialize the attachment extractor with a Notion client."""
        self.client = client

    # ── Discovery ──────────────────────────────────────────────────

    def find_attachments(
        self,
        blocks: list[NotionBlock],
        parent_page_id: str = "",
    ) -> list[NotionAttachment]:
        """Scan a block tree and return all downloadable attachments."""
        attachments = []
        self._walk_blocks(blocks, parent_page_id, attachments)
        logger.info(f"Found {len(attachments)} attachments in page {parent_page_id}")
        return attachments

    def _walk_blocks(
        self,
        blocks: list[NotionBlock],
        parent_page_id: str,
        results: list[NotionAttachment],
    ) -> None:
        """Recursively collect file-bearing blocks into attachment models."""
        for block in blocks:
            if block.block_type in FILE_BLOCK_TYPES and block.file_url:
                att = NotionAttachment(
                    block_id=block.block_id,
                    block_type=block.block_type,
                    url=block.file_url,
                    filename=self._url_to_filename(block.file_url, block.block_type),
                    mime_type=self._guess_mime_type(block.file_url, block.block_type),
                    caption=block.caption,
                    source_type=block.file_type or "external",
                    parent_page_id=parent_page_id,
                )
                results.append(att)

            if block.children:
                self._walk_blocks(block.children, parent_page_id, results)

    # ── Download ───────────────────────────────────────────────────

    async def download_attachment(
        self,
        attachment: NotionAttachment,
        output_dir: Path,
    ) -> Path | None:
        """Download one attachment and return its local path on success."""
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as http:
                response = await http.get(attachment.url)
                response.raise_for_status()
                content = response.content

        except Exception as e:
            logger.error(f"Failed to download {attachment.url}: {e}")
            return None

        content_hash = hashlib.sha256(content).hexdigest()[:16]
        ext = self._get_extension(attachment.filename, attachment.mime_type)
        output_filename = f"{attachment.block_type}_{content_hash}{ext}"
        output_path = output_dir / output_filename

        if output_path.exists():
            logger.debug(f"Attachment already exists: {output_path}")
            return output_path

        output_path.write_bytes(content)
        logger.info(
            f"Downloaded: {attachment.filename} → {output_path.name} ({len(content)} bytes)"
        )
        return output_path

    async def download_all(
        self,
        attachments: list[NotionAttachment],
        output_dir: Path,
    ) -> list[dict]:
        """Download all attachments and return a manifest of results."""
        manifest = []
        for att in attachments:
            local_path = await self.download_attachment(att, output_dir)
            manifest.append({
                "block_id": att.block_id,
                "original_filename": att.filename,
                "url": att.url,
                "caption": att.caption,
                "mime_type": att.mime_type,
                "source_type": att.source_type,
                "parent_page_id": att.parent_page_id,
                "local_path": str(local_path) if local_path else None,
                "downloaded": local_path is not None,
            })

        downloaded_count = sum(1 for m in manifest if m["downloaded"])
        logger.info(
            f"Downloaded {downloaded_count}/{len(attachments)} attachments to {output_dir}"
        )
        return manifest

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _url_to_filename(url: str, block_type: str) -> str:
        """Infer a filename from a URL or fall back to the block type."""
        parsed = urlparse(url)
        path = parsed.path

        if path and "/" in path:
            name = path.rsplit("/", 1)[-1]
            if "?" in name:
                name = name.split("?")[0]
            if name and "." in name:
                return name

        return f"{block_type}_attachment"

    @staticmethod
    def _guess_mime_type(url: str, block_type: str) -> str | None:
        """Guess a MIME type from the URL and block type."""
        parsed_path = urlparse(url).path
        mime, _ = mimetypes.guess_type(parsed_path)
        if mime:
            return mime

        defaults = {
            "image": "image/png",
            "pdf": "application/pdf",
            "video": "video/mp4",
            "audio": "audio/mpeg",
        }
        return defaults.get(block_type)

    @staticmethod
    def _get_extension(filename: str, mime_type: str | None) -> str:
        """Choose a file extension from the filename or MIME type."""
        if "." in filename:
            return "." + filename.rsplit(".", 1)[-1].lower()
        if mime_type:
            ext = mimetypes.guess_extension(mime_type)
            if ext:
                return ext
        return ""
