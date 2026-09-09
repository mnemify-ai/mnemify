// Notion-block renderer for the document viewer. Walks Notion's nested block
// tree from /api/documents/{id}/content (when the harvester ships structured
// JSON rather than pre-baked markdown) and emits a serif-styled article.
//
// Extracted from DocViewerPane.tsx — Notion rendering is ~370 lines and
// stands cleanly on its own. The dispatcher in DocViewerPane (`RenderedContent`)
// imports `NotionRender` and routes Notion-source docs here.

interface NotionBlock {
  block_id?: string;
  type?: string;
  text_content?: string;
  data?: Record<string, unknown>;
  children?: NotionBlock[];
}

interface NotionRawPage {
  page?: { title?: string; url?: string };
  blocks?: NotionBlock[];
  markdown?: string | null;
}

interface NotionRawDatabase {
  database?: {
    database_id?: string;
    title?: string;
    url?: string;
    properties_schema?: Record<string, { type?: string; name?: string }>;
  };
  rows?: Array<{
    page_id?: string;
    title?: string;
    url?: string;
    properties?: Record<string, unknown>;
  }>;
}

import { useMemo } from "react";
import { MarkdownRender } from "./DocViewerMarkdown";
import {
  Blockquote,
  bulletItemCls,
  CodeBlock,
  emphasisCls,
  headingCls,
  headingTag,
  InlineCode,
  insetCls,
  listCls,
  orderedItemCls,
  paragraphCls,
  ProseArticle,
  ProseHr,
  ProseLink,
  ProseTable,
  ProseTd,
  ProseTh,
  ProseTheadRow,
  ProseTr,
  RawBlock,
  strongCls,
  TaskCheckbox,
  TaskLabel,
} from "./markdown";
import { cn } from "../lib/cn";

export function NotionRender({ source }: { source: string }) {
  const parsed = useMemo<(NotionRawPage & NotionRawDatabase) | null>(() => {
    try {
      return JSON.parse(source) as NotionRawPage & NotionRawDatabase;
    } catch {
      return null;
    }
  }, [source]);

  if (!parsed) {
    // JSON.parse failed — the source was either truncated mid-structure
    // or shipped in an unexpected shape. Fall back to plain text so the
    // user still sees the underlying content instead of a hard error.
    return (
      <div className="space-y-2">
        <p className="font-sans text-xs text-muted italic">
          Notion document couldn&rsquo;t be parsed as structured blocks — showing raw content.
        </p>
        <RawBlock content={source} />
      </div>
    );
  }

  // Databases are harvested as their own documents with a different envelope
  // shape ({database, rows}) than pages ({page, blocks, markdown}). Without
  // this branch the dispatcher fell into "blocks.length === 0" and rendered
  // "This page has no content yet" for every Notion database.
  if (parsed.database || Array.isArray(parsed.rows)) {
    return <NotionDatabaseRender envelope={parsed} />;
  }

  // Notion sometimes ships a pre-baked markdown alongside the blocks.
  // Prefer it when present — it's already nicely flat.
  if (parsed.markdown && parsed.markdown.trim()) {
    return <MarkdownRender source={parsed.markdown} />;
  }

  const blocks = parsed.blocks ?? [];
  if (blocks.length === 0) {
    return <p className="font-sans text-sm text-muted">This page has no content yet.</p>;
  }

  return (
    <ProseArticle>
      <NotionBlocks blocks={blocks} />
    </ProseArticle>
  );
}

function formatDbCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((v) => formatDbCell(v)).filter(Boolean).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function NotionDatabaseRender({ envelope }: { envelope: NotionRawDatabase }) {
  const schema = envelope.database?.properties_schema ?? {};
  const rows = envelope.rows ?? [];
  const titleProp = Object.entries(schema).find(([, s]) => s?.type === "title")?.[0];
  const otherProps = Object.keys(schema).filter((n) => n !== titleProp);
  const headers = [titleProp || "Title", ...otherProps];

  if (rows.length === 0) {
    return (
      <div className="space-y-3">
        <p className="font-sans text-sm text-muted">
          Empty database — no rows.
        </p>
        {headers.length > 1 && (
          <p className="font-sans text-xs text-muted">
            <span className="eyebrow mr-2">Properties</span>
            {headers.slice(1).join(" · ")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="eyebrow">
        Database · {rows.length} {rows.length === 1 ? "row" : "rows"}
      </p>
      <ProseTable>
        <thead>
          <ProseTheadRow>
            {headers.map((h) => (
              <ProseTh key={h}>{h}</ProseTh>
            ))}
          </ProseTheadRow>
        </thead>
        <tbody>
          {rows.map((row, ri) => {
            const props = row.properties ?? {};
            return (
              <ProseTr key={row.page_id ?? ri}>
                <ProseTd className="text-ink">
                  {row.url ? (
                    <ProseLink href={row.url}>{row.title || "Untitled"}</ProseLink>
                  ) : (
                    <span className="text-ink">{row.title || "Untitled"}</span>
                  )}
                </ProseTd>
                {otherProps.map((p) => (
                  <ProseTd key={p}>{formatDbCell(props[p])}</ProseTd>
                ))}
              </ProseTr>
            );
          })}
        </tbody>
      </ProseTable>
    </div>
  );
}

/** Block types whose own renderer in {@link NotionBlock} consumes ``children``
 *  directly. For everything else, {@link NotionBlocks} recurses into children
 *  after rendering the parent, so structural wrappers like ``paragraph`` /
 *  ``heading`` / ``callout`` (Notion can stash real content inside the
 *  children of an outwardly empty paragraph) don't drop their nested content. */
const SELF_CONSUMES_CHILDREN = new Set([
  "toggle",
  "table",
  "column_list",
  "column",
  "synced_block",
  "meeting_notes",
]);

function NotionBlocks({ blocks }: { blocks: NotionBlock[] }) {
  // Group consecutive list items into a single <ul>/<ol>. Notion sends them
  // as siblings, but HTML needs the wrapper for proper indentation.
  const out: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < blocks.length) {
    const b = blocks[i];
    const t = b.type ?? "";
    if (t === "bulleted_list_item" || t === "numbered_list_item") {
      const ordered = t === "numbered_list_item";
      const items: React.ReactNode[] = [];
      while (
        i < blocks.length &&
        blocks[i].type === t
      ) {
        items.push(
          <li key={key++} className={ordered ? orderedItemCls : bulletItemCls}>
            <NotionInline block={blocks[i]} />
            {blocks[i].children && blocks[i].children!.length > 0 && (
              <div className="mt-1">
                <NotionBlocks blocks={blocks[i].children!} />
              </div>
            )}
          </li>,
        );
        i += 1;
      }
      out.push(
        ordered ? (
          <ol key={key++} className={listCls}>
            {items}
          </ol>
        ) : (
          <ul key={key++} className={listCls}>
            {items}
          </ul>
        ),
      );
      continue;
    }
    out.push(<NotionBlock key={key++} block={b} />);
    // Recurse into children for any block whose own renderer doesn't already
    // do so (paragraph, heading, quote, callout, to_do, …). Without this,
    // Notion pages whose real content lives inside a chain of nested
    // paragraphs render as completely empty.
    if (
      b.children &&
      b.children.length > 0 &&
      !SELF_CONSUMES_CHILDREN.has(t)
    ) {
      out.push(
        <div key={key++} className="ml-0">
          <NotionBlocks blocks={b.children} />
        </div>,
      );
    }
    i += 1;
  }
  return <>{out}</>;
}

function NotionBlock({ block }: { block: NotionBlock }) {
  const t = block.type ?? "";
  const data = (block.data ?? {}) as Record<string, unknown>;
  switch (t) {
    case "paragraph":
      return (
        <p className={paragraphCls}>
          <NotionInline block={block} />
        </p>
      );
    case "heading_1":
    case "heading_2":
    case "heading_3": {
      const level = Number(t.slice(-1));
      const Tag = headingTag(level);
      return (
        <Tag className={headingCls(level)}>
          <NotionInline block={block} />
        </Tag>
      );
    }
    case "divider":
      return <ProseHr />;
    case "quote":
      return (
        <Blockquote>
          <NotionInline block={block} />
        </Blockquote>
      );
    case "callout":
      return (
        <div className="bg-bone/40 border border-hair rounded-lg px-4 py-3 flex items-start gap-3">
          {typeof data["icon"] === "object" && data["icon"] && "emoji" in (data["icon"] as Record<string, unknown>) ? (
            <span className="text-lg leading-none mt-0.5">
              {String((data["icon"] as Record<string, unknown>).emoji ?? "")}
            </span>
          ) : null}
          <div className="flex-1 min-w-0">
            <NotionInline block={block} />
          </div>
        </div>
      );
    case "code":
      return <CodeBlock>{block.text_content ?? ""}</CodeBlock>;
    case "to_do": {
      const checked = (data["checked"] as boolean | undefined) ?? false;
      return (
        <label className="flex items-start gap-2.5">
          <TaskCheckbox checked={checked} />
          <TaskLabel checked={checked}>
            <NotionInline block={block} />
          </TaskLabel>
        </label>
      );
    }
    case "toggle":
      return (
        <details className="bg-bone/20 border border-hair rounded-lg px-3 py-2">
          <summary className="cursor-pointer font-medium">
            <NotionInline block={block} />
          </summary>
          {block.children && block.children.length > 0 && (
            <div className="mt-2 pl-3">
              <NotionBlocks blocks={block.children} />
            </div>
          )}
        </details>
      );
    case "child_page":
    case "child_database": {
      const title =
        block.text_content ||
        (typeof data["title"] === "string" ? (data["title"] as string) : "Untitled");
      return (
        <div className={cn(insetCls, "flex items-center gap-2 text-sm")}>
          <span className="font-sans text-[10px] uppercase tracking-eyebrow text-muted">
            {t === "child_database" ? "Database" : "Sub-page"}
          </span>
          <span className="font-serif text-ink">{title}</span>
        </div>
      );
    }
    case "image":
    case "file":
    case "video":
    case "audio":
    case "pdf":
    case "embed": {
      const caption = block.text_content || "";
      // The real attachment is downloaded into the doc's attachments dir;
      // it's listed below the content in the Attachments section. Here we
      // just acknowledge the placement.
      return (
        <div className={cn(insetCls, "text-sm font-sans text-muted italic")}>
          <span className="font-sans text-[10px] uppercase tracking-eyebrow mr-2">{t}</span>
          {caption || "Attachment — see below."}
        </div>
      );
    }
    case "bookmark":
    case "link_preview": {
      const url = typeof data["url"] === "string" ? (data["url"] as string) : "";
      const label = block.text_content || url || (t === "bookmark" ? "Bookmark" : "Link preview");
      if (!url) {
        return <p className="text-ink/80 italic">{label}</p>;
      }
      return (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className={cn(insetCls, "block hover:border-hair-strong transition-colors")}
        >
          <span className="font-sans text-[10px] uppercase tracking-eyebrow text-muted mr-2">
            {t === "bookmark" ? "Bookmark" : "Link"}
          </span>
          <span className="text-magenta break-all">{label}</span>
        </a>
      );
    }
    case "link_to_page": {
      // Notion ships either {type: "page_id", page_id: "..."} or
      // {type: "database_id", database_id: "..."}. We don't currently
      // resolve the target title — surface the kind and the id as a hint.
      const linkType = typeof data["type"] === "string" ? (data["type"] as string) : "";
      const targetId =
        (typeof data["page_id"] === "string" && (data["page_id"] as string)) ||
        (typeof data["database_id"] === "string" && (data["database_id"] as string)) ||
        "";
      const kind = linkType === "database_id" ? "Database" : "Sub-page";
      return (
        <div className={cn(insetCls, "flex items-center gap-2 text-sm")}>
          <span className="font-sans text-[10px] uppercase tracking-eyebrow text-muted">
            Link · {kind}
          </span>
          <span className="font-mono text-[11px] text-ink/80 break-all">
            {targetId || "—"}
          </span>
        </div>
      );
    }
    case "equation": {
      // No KaTeX/MathJax bundled — render the source LaTeX in a code-like
      // box so the user can still see (and copy) the expression instead of
      // it disappearing entirely.
      const expr = typeof data["expression"] === "string" ? (data["expression"] as string) : "";
      const body = expr || block.text_content || "";
      if (!body) return null;
      return <CodeBlock>{body}</CodeBlock>;
    }
    case "breadcrumb":
      // Inline Notion "breadcrumb" block — Notion uses it to drop a small
      // location indicator inside the page body. The actual breadcrumb at
      // the top of the viewer (DocViewerPane) already shows the path, so
      // surface this as a quiet placeholder rather than re-deriving it.
      return (
        <p className="font-sans text-[11px] uppercase tracking-eyebrow text-muted">
          ↳ Breadcrumb
        </p>
      );
    case "table_of_contents":
      // Building a real TOC means traversing later siblings to collect
      // headings. We don't have that information at render time without a
      // pre-pass, so emit a quiet marker that preserves the block's
      // intent without faking content.
      return (
        <p className="font-sans text-[11px] uppercase tracking-eyebrow text-muted">
          Table of contents
        </p>
      );
    case "column_list":
    case "column":
    case "synced_block": {
      // Structural containers: render children flat. Without this, a page
      // wrapped in column_list → column → [headings, paragraphs] looks
      // completely empty because the container itself has no text_content.
      if (block.children && block.children.length > 0) {
        return <NotionBlocks blocks={block.children} />;
      }
      const text = block.text_content?.trim() || "";
      return text ? <p className={paragraphCls}>{text}</p> : null;
    }
    case "meeting_notes": {
      // Notion meeting_notes blocks bundle three sections — AI summary, the
      // user's notes, and the audio transcript — as three empty-paragraph
      // children. ``data.children`` maps section name to the block_id of
      // each wrapper, so we can emit a clear heading per section instead of
      // running them together as one wall of text.
      if (!block.children || block.children.length === 0) {
        const text = block.text_content?.trim() || "";
        return text ? <p className={paragraphCls}>{text}</p> : null;
      }
      const childMap = (data["children"] as Record<string, unknown> | undefined) ?? {};
      const idToLabel: Record<string, string> = {};
      if (typeof childMap["summary_block_id"] === "string") {
        idToLabel[childMap["summary_block_id"]] = "Summary";
      }
      if (typeof childMap["notes_block_id"] === "string") {
        idToLabel[childMap["notes_block_id"]] = "Notes";
      }
      if (typeof childMap["transcript_block_id"] === "string") {
        idToLabel[childMap["transcript_block_id"]] = "Transcript";
      }
      return (
        <>
          {block.children.map((c, idx) => {
            const label = idToLabel[c.block_id ?? ""];
            // The wrapper paragraph itself is empty; the real content lives
            // in its children. Rendering ``c.children`` directly skips the
            // empty <p> that would otherwise create visual noise.
            const inner = c.children ?? [];
            return (
              <section key={c.block_id ?? idx} className="space-y-3">
                {label && (
                  <h3 className={cn(headingCls(2), "mt-4 border-b border-hair pb-1.5")}>
                    {label}
                  </h3>
                )}
                <NotionBlocks blocks={inner.length > 0 ? inner : [c]} />
              </section>
            );
          })}
        </>
      );
    }
    case "table": {
      // Render table_row children as a simple HTML table. Each row's children
      // are cells (Notion ships table_row blocks with rich_text-per-cell).
      const rows = (block.children ?? []).filter((c) => c.type === "table_row");
      if (rows.length === 0) {
        const text = block.text_content?.trim() || "";
        return text ? <p className={paragraphCls}>{text}</p> : null;
      }
      const cellsOf = (row: NotionBlock): string[] => {
        const d = (row.data ?? {}) as Record<string, unknown>;
        const cells = d["cells"];
        if (Array.isArray(cells)) {
          return cells.map((cell) =>
            Array.isArray(cell)
              ? cell.map((r) => (r as Record<string, unknown>)["plain_text"] ?? "").join("")
              : String(cell ?? ""),
          );
        }
        return [row.text_content ?? ""];
      };
      return (
        <ProseTable>
          <tbody>
            {rows.map((row, ri) => (
              <ProseTr key={ri}>
                {cellsOf(row).map((c, ci) => (
                  <ProseTd key={ci}>{c}</ProseTd>
                ))}
              </ProseTr>
            ))}
          </tbody>
        </ProseTable>
      );
    }
    case "table_row":
      // Only reached if a table_row appears outside a table parent.
      return null;
    default: {
      // Unknown block type: render text_content if any. NotionBlocks (our
      // caller) will recurse into block.children automatically since the
      // default type isn't in SELF_CONSUMES_CHILDREN — don't double-render
      // here.
      const text = block.text_content?.trim() || "";
      if (text) return <p className={paragraphCls}>{text}</p>;
      return null;
    }
  }
}

/** Render a Notion block's rich_text array (or fall back to text_content). */
function NotionInline({ block }: { block: NotionBlock }) {
  const data = (block.data ?? {}) as Record<string, unknown>;
  const rich = data["rich_text"];
  if (Array.isArray(rich) && rich.length > 0) {
    return (
      <>
        {rich.map((r, i) => (
          <NotionRichFragment key={i} fragment={r as Record<string, unknown>} />
        ))}
      </>
    );
  }
  return <>{block.text_content ?? ""}</>;
}

function NotionRichFragment({ fragment }: { fragment: Record<string, unknown> }) {
  const text = (fragment["plain_text"] as string | undefined)
    ?? ((fragment["text"] as Record<string, unknown> | undefined)?.["content"] as string | undefined)
    ?? "";
  const annotations = (fragment["annotations"] as Record<string, unknown> | undefined) ?? {};
  const link = (fragment["href"] as string | undefined)
    ?? ((fragment["text"] as Record<string, unknown> | undefined)?.["link"] as Record<string, unknown> | undefined)?.["url"] as string | undefined;

  let node: React.ReactNode = text;
  if (annotations["code"]) {
    node = <InlineCode>{node}</InlineCode>;
  }
  if (annotations["bold"]) {
    node = <strong className={strongCls}>{node}</strong>;
  }
  if (annotations["italic"]) {
    node = <em className={emphasisCls}>{node}</em>;
  }
  if (annotations["underline"]) {
    node = <u>{node}</u>;
  }
  if (annotations["strikethrough"]) {
    node = <s>{node}</s>;
  }
  if (link && typeof link === "string") {
    node = <ProseLink href={link}>{node}</ProseLink>;
  }
  return <>{node}</>;
}
