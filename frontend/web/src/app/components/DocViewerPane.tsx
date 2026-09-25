// Document viewer — the right-hand pane on /documents.
//
// Owns the orchestration: data fetches for the doc, content, and attachments;
// the header, properties block, attachments list, footer; and the
// `RenderedContent` dispatcher that routes to a source-appropriate body
// renderer.
//
// The body renderers live in sibling files so this file stays focused:
//   - DocViewerNotion.tsx     — Notion structured-block JSON
//   - DocViewerHtml.tsx       — Confluence XHTML
//   - DocViewerMarkdown.tsx   — pre-baked markdown (Notion fallback, Obsidian)

import { useState, type ReactNode } from "react";
import { ChevronRight, Download, FileText, MoreHorizontal, RefreshCw, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  useDocument,
  useDocumentContent,
  useDocumentAttachments,
  useReharvestDocument,
  type DocAttachment,
  type DocProperty,
} from "../api/documents";
import { ApiError, apiUrl } from "../api/client";
import { SourceBadge } from "./SourceBadge";
import { Popover } from "./ui/Popover";
import { Skeleton } from "./ui/Skeleton";
import { ErrorState } from "./ui/ErrorState";
import { NotionRender } from "./DocViewerNotion";
import { HtmlRender } from "./DocViewerHtml";
import { MarkdownRender } from "./DocViewerMarkdown";
import { formatBytes } from "./DocTable";
import { relativeTime } from "../lib/relativeTime";
import { AttachmentViewer } from "./attachments/AttachmentViewer";
import { preloadRenderer } from "./attachments/registry";

interface DocViewerPaneProps {
  docId: string;
  onClose: () => void;
  /** Embedded mode (knowledge-map right panel): the host already provides
   *  its own Back/close navigation, so the pane drops its X button and lets
   *  the host slot that navigation into the toolbar via `leading`. */
  embedded?: boolean;
  /** Content rendered at the start of the compact toolbar row. */
  leading?: ReactNode;
}

export function DocViewerPane({ docId, onClose, embedded = false, leading }: DocViewerPaneProps) {
  const shell = embedded
    ? "h-full flex flex-col min-w-0"
    : "h-full flex flex-col bg-cream border-l border-hair min-w-0";
  return (
    <aside className={shell}>
      <DocViewerBody docId={docId} onClose={onClose} embedded={embedded} leading={leading} />
    </aside>
  );
}

function DocViewerBody({
  docId,
  onClose,
  embedded,
  leading,
}: {
  docId: string;
  onClose: () => void;
  embedded: boolean;
  leading?: ReactNode;
}) {
  const doc = useDocument(docId);
  const content = useDocumentContent(docId);
  const attachments = useDocumentAttachments(docId);
  const reharvest = useReharvestDocument();

  function handleReharvest() {
    reharvest.mutate(docId, {
      onSuccess: (res) => toast.success(`Re-harvested (${res.action}).`),
      onError: (err) => toast.error("Couldn't re-harvest", { description: String(err) }),
    });
  }

  if (doc.isError) {
    const status = doc.error instanceof ApiError ? doc.error.status : null;
    return (
      <div className="flex-1 p-6 pt-12">
        <CloseButton onClose={onClose} />
        {status === 404 ? (
          <ErrorState
            title="Document not found"
            description="It may have been deleted at source or filtered out."
          />
        ) : (
          <ErrorState
            title="Couldn't load document"
            description={doc.error instanceof Error ? doc.error.message : "Unexpected error."}
            onRetry={() => void doc.refetch()}
          />
        )}
      </div>
    );
  }

  if (!doc.data) {
    return (
      <div className="p-6 pt-12 space-y-3" aria-busy="true">
        <CloseButton onClose={onClose} />
        <Skeleton variant="line" width="70%" className="h-6" />
        <div className="space-y-2 pt-2">
          <Skeleton variant="line" width="95%" />
          <Skeleton variant="line" width="90%" />
          <Skeleton variant="line" width="92%" />
          <Skeleton variant="line" width="60%" />
        </div>
      </div>
    );
  }

  const d = doc.data;
  const format = content.data?.format ?? "raw";
  const pad = embedded ? "px-0.5" : "px-6";

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Compact toolbar: host nav (map) · source · collapsed path · actions.
          Everything else — title, metadata, body — scrolls together below. */}
      <div
        className={`${pad} ${embedded ? "pt-0 pb-2" : "pt-3 pb-2"} border-b border-hair shrink-0 flex items-center gap-2 min-w-0`}
      >
        {leading}
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <SourceBadge source={d.source} size="sm" />
          <DocBreadcrumb titles={d.path_titles ?? []} ids={d.path_ids ?? []} />
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <OverflowMenu
            onRefresh={handleReharvest}
            refreshing={reharvest.isPending}
          />
          {!embedded && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close document viewer"
              className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-bone/60 transition-colors"
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          )}
        </div>
      </div>

      <section className={`flex-1 min-h-0 overflow-y-auto overflow-x-hidden ${pad} pt-4 pb-5`}>
        <h2 className="font-serif text-xl text-ink leading-snug tracking-tight break-words">
          {d.title}
        </h2>
        <p className="font-sans text-xs text-muted mt-1.5">
          {d.space && d.space !== "—" ? `${d.space} · ` : ""}
          {d.harvested_at ? `harvested ${relativeTime(d.harvested_at)}` : "not harvested"}
        </p>
        <DetailsDisclosure
          rows={[
            ["Source", `${d.source}${d.type ? ` · ${d.type}` : ""}`],
            ["Location", <PathText key="loc" titles={d.path_titles ?? []} />],
            ["Harvested", d.harvested_at ? new Date(d.harvested_at).toLocaleString() : ""],
            ["Updated", d.updated_at ? new Date(d.updated_at).toLocaleString() : ""],
            ["Size", d.size_bytes ? formatBytes(d.size_bytes) : ""],
            ["Format", format],
            ["ID", d.source_id ?? ""],
          ]}
        >
          <PropertiesPanel properties={d.properties} skipKeys={[d.title]} />
        </DetailsDisclosure>
        <div className="border-t border-hair mb-6" aria-hidden />
        {content.isLoading ? (
          <div className="space-y-2" aria-busy="true">
            <Skeleton variant="line" width="92%" />
            <Skeleton variant="line" width="88%" />
            <Skeleton variant="line" width="95%" />
            <Skeleton variant="line" width="70%" />
            <Skeleton variant="line" width="80%" />
          </div>
        ) : (
          <RenderedContent
            source={d.source}
            format={format}
            content={content.data?.content ?? ""}
            attachments={attachments.data?.items}
          />
        )}
        <AttachmentsSection
          items={attachments.data?.items ?? []}
          loading={attachments.isLoading}
        />
      </section>
    </div>
  );
}

/** "⋯" menu holding the rarely-used document actions. */
function OverflowMenu({ onRefresh, refreshing }: { onRefresh: () => void; refreshing: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      className="min-w-[200px]"
      trigger={
        <button
          type="button"
          aria-label="Document actions"
          aria-haspopup="menu"
          aria-expanded={open}
          className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-bone/60 transition-colors"
        >
          <MoreHorizontal size={16} strokeWidth={1.5} aria-hidden />
        </button>
      }
    >
      <ul role="menu" className="flex flex-col gap-0.5">
        <li role="none">
          <button
            type="button"
            role="menuitem"
            disabled={refreshing}
            onClick={() => {
              setOpen(false);
              onRefresh();
            }}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left text-[13px] text-ink hover:bg-bone/60 disabled:opacity-50 disabled:cursor-default transition-colors"
          >
            <RefreshCw
              size={13}
              strokeWidth={1.5}
              className={refreshing ? "animate-spin" : ""}
              aria-hidden
            />
            {refreshing ? "Refreshing…" : "Refresh from source"}
          </button>
        </li>
      </ul>
    </Popover>
  );
}

/** Collapsed "Details" block under the title: the secondary metadata
 *  (timestamps, size, format, ID, location) plus any source properties. Sits
 *  on a slightly darker warm surface so it reads as metadata, not document. */
function DetailsDisclosure({
  rows,
  children,
}: {
  rows: [string, ReactNode][];
  children?: ReactNode;
}) {
  const filled = rows.filter(([, v]) => (typeof v === "string" ? v.trim().length > 0 : v != null));
  return (
    <details className="group mt-3 mb-5 rounded-lg bg-bone/60 open:bg-bone/70 transition-colors">
      <summary className="flex items-center gap-1.5 cursor-pointer select-none px-3.5 py-2.5 font-sans text-[11px] uppercase tracking-eyebrow text-muted hover:text-ink list-none [&::-webkit-details-marker]:hidden rounded-lg">
        <ChevronRight
          size={11}
          strokeWidth={1.75}
          className="transition-transform group-open:rotate-90"
          aria-hidden
        />
        Details
      </summary>
      <div className="px-3.5 pb-3.5 pt-0.5 font-sans">
        <dl className={detailsGridCls}>
          {filled.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className={detailsDtCls}>{k}</dt>
              <dd className={detailsDdCls}>{v}</dd>
            </div>
          ))}
        </dl>
        {children}
      </div>
    </details>
  );
}

// Both columns share one line-height (leading-5 = 20px) and align on the
// baseline so an 11px uppercase label and a 12.5px value sit on the same line.
const detailsGridCls =
  "grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 items-baseline";
const detailsDtCls =
  "font-sans text-[11px] leading-5 uppercase tracking-eyebrow text-muted";
const detailsDdCls = "font-sans text-[12.5px] leading-5 text-ink break-words";

/** Ancestor chain for the Details block. Each folder name and its trailing
 *  chevron form one unbreakable unit, so wrapping never strands a chevron at
 *  the far right of a line. */
function PathText({ titles }: { titles: string[] }) {
  if (titles.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-y-0.5">
      {titles.map((t, i) => (
        <span key={`${i}-${t}`} className="inline-flex items-center whitespace-nowrap">
          <span className="whitespace-normal">{t}</span>
          {i < titles.length - 1 && (
            <ChevronRight
              size={11}
              strokeWidth={2}
              className="shrink-0 mx-1.5 text-muted/50"
              aria-hidden
            />
          )}
        </span>
      ))}
    </span>
  );
}

function formatPropertyValue(prop: DocProperty | null | undefined): string {
  // Notion properties occasionally arrive as a bare null (an unresolved
  // property column) rather than a {type, value} object — guard so the
  // panel doesn't crash on access. See DocProperty in api/documents.ts.
  if (!prop || typeof prop !== "object") return "";
  const v = prop.value;
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(String).filter(Boolean).join(", ");
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

function PropertiesPanel({
  properties,
  skipKeys,
}: {
  properties?: Record<string, DocProperty | null>;
  skipKeys?: string[];
}) {
  if (!properties) return null;
  const skip = new Set((skipKeys ?? []).map((s) => s.toLowerCase()));
  const entries = Object.entries(properties).filter(([k, p]) => {
    if (skip.has(k.toLowerCase())) return false;
    const v = formatPropertyValue(p);
    return v.length > 0;
  });
  if (entries.length === 0) return null;
  return (
    <dl className={`${detailsGridCls} mt-2.5 pt-2.5 border-t border-line/20`}>
      {entries.map(([k, p]) => (
        <div key={k} className="contents">
          <dt className={detailsDtCls}>{k}</dt>
          <dd className={detailsDdCls}>{formatPropertyValue(p)}</dd>
        </div>
      ))}
    </dl>
  );
}

function AttachmentsSection({
  items,
  loading,
}: {
  items: DocAttachment[];
  loading: boolean;
}) {
  const [viewing, setViewing] = useState<DocAttachment | null>(null);

  if (loading) return null;
  // Images are rendered inline within the markdown body (see renderInline's
  // image pattern + resolveImageSrc), so the gallery only surfaces non-image
  // attachments (PDFs, docs, zips). When nothing non-image is left the whole
  // section disappears.
  const files = items.filter((a) => !a.is_image);
  if (files.length === 0) return null;

  return (
    <section className="mt-8 border-t border-hair pt-5">
      <p className="eyebrow mb-3">
        Attachments · {files.length}
      </p>
      <ul className="space-y-1.5">
        {files.map((a) => (
          <li
            key={a.name}
            className="flex items-stretch rounded-lg border border-hair bg-bone/30 overflow-hidden hover:border-hair-strong transition-colors"
          >
            <button
              type="button"
              onClick={() => setViewing(a)}
              onMouseEnter={() => preloadRenderer(a)}
              onFocus={() => preloadRenderer(a)}
              className="flex-1 min-w-0 flex items-center gap-3 px-3 py-2 text-left hover:bg-bone/50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-magenta/40"
              aria-label={`Preview ${a.name}`}
            >
              <FileText
                size={14}
                strokeWidth={1.5}
                className="text-muted shrink-0"
                aria-hidden
              />
              <div className="flex-1 min-w-0">
                <p className="font-serif text-sm text-ink truncate">{a.name}</p>
                <p className="font-mono text-[10px] text-muted">
                  {a.mime} · {humanBytes(a.size_bytes)}
                </p>
              </div>
            </button>
            <a
              href={apiUrl(a.url)}
              download={a.name}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 px-3 font-sans text-[11px] text-magenta hover:bg-magenta/10 transition-colors shrink-0 border-l border-hair"
              aria-label={`Download ${a.name}`}
            >
              <Download size={12} strokeWidth={1.75} aria-hidden />
              Download
            </a>
          </li>
        ))}
      </ul>
      <AttachmentViewer attachment={viewing} onClose={() => setViewing(null)} />
    </section>
  );
}

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close document viewer"
      className="absolute top-3 right-3 p-1.5 rounded-lg text-muted hover:text-ink hover:bg-bone/60 transition-colors"
    >
      <X size={16} strokeWidth={1.5} />
    </button>
  );
}

/** Pick a renderer based on the source + reported format. Exported for the
 *  citation source inspector (ask/SourceInspector.tsx), which reuses this
 *  dispatch instead of re-implementing per-source rendering. */
export function RenderedContent({
  source,
  format,
  content,
  attachments,
}: {
  source: string;
  format: string;
  content: string;
  attachments?: DocAttachment[];
}) {
  const fmt = format?.toLowerCase() ?? "";
  if (!content.trim()) {
    return <p className="font-sans text-sm text-muted">Preview unavailable.</p>;
  }
  // Route by format first — the BE may legitimately ship a Notion doc as
  // markdown (e.g. when the raw JSON would exceed the content-size cap and
  // the server falls back to the normalized markdown).
  if (fmt === "markdown" || fmt === "md") {
    return <MarkdownRender source={content} attachments={attachments} />;
  }
  if (fmt === "html") {
    return <HtmlRender html={content} attachments={attachments} />;
  }
  if (fmt === "json") {
    return <NotionRender source={content} />;
  }
  // Fall back to source-based routing when format is missing/unknown.
  if (source === "notion") {
    return <NotionRender source={content} />;
  }
  if (source === "confluence") {
    return <HtmlRender html={content} attachments={attachments} />;
  }
  if (source === "obsidian" || source === "localfiles") {
    return <MarkdownRender source={content} attachments={attachments} />;
  }
  return <RawRender content={content} />;
}

function RawRender({ content }: { content: string }) {
  return (
    <pre className="font-mono text-[11px] text-ink/90 whitespace-pre-wrap break-words bg-bone/40 border border-hair rounded-lg p-3">
      {content}
    </pre>
  );
}

/** Root-first ancestor path shown in the toolbar. Collapsed by default to a
 *  single line — "… › Parent" for deep trees — and expands to the full chain
 *  on click. Segments whose id is present (i.e. the ancestor was itself
 *  harvested) become clickable and swap the viewer to that doc. */
function DocBreadcrumb({ titles, ids }: { titles: string[]; ids: string[] }) {
  const [, setParams] = useSearchParams();
  const [expanded, setExpanded] = useState(false);
  if (titles.length === 0) return null;

  function openDoc(id: string) {
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        out.set("id", id);
        return out;
      },
      { replace: false },
    );
  }

  const collapsed = !expanded && titles.length > 1;
  const visible = collapsed ? titles.slice(-1) : titles;
  const offset = titles.length - visible.length;

  return (
    <nav
      aria-label="Document path"
      className={`flex items-center gap-1 min-w-0 font-sans text-[11px] text-muted ${
        expanded ? "flex-wrap" : "flex-nowrap overflow-hidden"
      }`}
    >
      {collapsed && (
        <>
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="hover:text-ink shrink-0 px-0.5"
            aria-label={`Show full path (${titles.length} levels)`}
            title={titles.join(" › ")}
          >
            …
          </button>
          <ChevronRight size={11} strokeWidth={1.75} className="shrink-0 text-muted/60" aria-hidden />
        </>
      )}
      {visible.map((title, vi) => {
        const i = vi + offset;
        const id = ids[i] || "";
        const isLast = i === titles.length - 1;
        const segCls = collapsed ? "truncate min-w-0" : "max-w-[18ch] truncate";
        const segment = id ? (
          <button
            type="button"
            onClick={() => openDoc(id)}
            className={`hover:text-ink hover:underline underline-offset-2 transition-colors ${segCls}`}
            title={title}
          >
            {title}
          </button>
        ) : (
          <span className={segCls} title={title}>
            {title}
          </span>
        );
        return (
          <span key={`${i}-${title}`} className="inline-flex items-center gap-1 min-w-0">
            {segment}
            {!isLast && (
              <ChevronRight
                size={11}
                strokeWidth={1.75}
                className="shrink-0 text-muted/60"
                aria-hidden
              />
            )}
          </span>
        );
      })}
    </nav>
  );
}
