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

import { useState } from "react";
import { ChevronRight, Download, FileText, RefreshCw, X } from "lucide-react";
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
import { Button } from "./ui/Button";
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
}

export function DocViewerPane({ docId, onClose }: DocViewerPaneProps) {
  return (
    <aside className="h-full flex flex-col bg-cream border-l border-hair min-w-0">
      <DocViewerBody docId={docId} onClose={onClose} />
    </aside>
  );
}

function DocViewerBody({ docId, onClose }: { docId: string; onClose: () => void }) {
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

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="px-6 pt-5 pb-4 border-b border-hair shrink-0 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <span className="eyebrow">Document</span>
            <SourceBadge source={d.source} size="sm" />
            <span className="font-sans text-[11px] text-muted">{d.type}</span>
          </div>
          <DocBreadcrumb titles={d.path_titles ?? []} ids={d.path_ids ?? []} />
          <h2 className="font-serif text-2xl text-ink leading-snug tracking-tight">{d.title}</h2>
          <p className="font-sans text-xs text-muted mt-1.5">
            {d.space && d.space !== "—" ? `${d.space} · ` : ""}
            {d.harvested_at ? `harvested ${relativeTime(d.harvested_at)}` : "not harvested"}
            {d.updated_at ? ` · updated ${relativeTime(d.updated_at)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleReharvest}
            disabled={reharvest.isPending}
            loading={reharvest.isPending}
          >
            {!reharvest.isPending && <RefreshCw size={14} strokeWidth={1.5} />}
            Re-harvest
          </Button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close document viewer"
            className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-bone/60 transition-colors"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>
      </header>

      <section className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-6 py-5">
        <PropertiesPanel properties={d.properties} skipKeys={[d.title]} />
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

      <footer className="px-6 py-2.5 border-t border-hair shrink-0 flex items-center justify-between gap-3 font-sans text-[10px] text-muted uppercase tracking-eyebrow">
        <span className="truncate">
          {formatBytes(d.size_bytes)} · {format} · ID {d.source_id}
        </span>
      </footer>
    </div>
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
    <dl className="mb-5 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {entries.map(([k, p]) => (
        <div key={k} className="contents">
          <dt className="font-sans text-[11px] uppercase tracking-eyebrow text-muted self-center">
            {k}
          </dt>
          <dd className="text-ink break-words">{formatPropertyValue(p)}</dd>
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
  if (source === "obsidian") {
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

/** Root-first ancestor breadcrumb above the doc title. Segments whose id is
 *  present (i.e. the ancestor was itself harvested) become clickable and
 *  swap the viewer to that doc; bare-title segments render plain. Wraps to
 *  multiple lines so a 7-10-deep Notion or Confluence tree doesn't cause
 *  horizontal overflow. */
function DocBreadcrumb({ titles, ids }: { titles: string[]; ids: string[] }) {
  const [, setParams] = useSearchParams();
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

  return (
    <nav
      aria-label="Document path"
      className="flex flex-wrap items-center gap-1 mb-2 font-sans text-[11px] text-muted"
    >
      {titles.map((title, i) => {
        const id = ids[i] || "";
        const isLast = i === titles.length - 1;
        const segment = id ? (
          <button
            type="button"
            onClick={() => openDoc(id)}
            className="hover:text-ink hover:underline underline-offset-2 transition-colors max-w-[18ch] truncate"
            title={title}
          >
            {title}
          </button>
        ) : (
          <span className="max-w-[18ch] truncate" title={title}>
            {title}
          </span>
        );
        return (
          <span key={`${i}-${title}`} className="inline-flex items-center gap-1">
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
