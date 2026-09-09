import { useEffect, useRef } from "react";
import { Compass, ExternalLink } from "lucide-react";
import { ApiError } from "../app/api/client";
import {
  useDocument,
  useDocumentAttachments,
  useDocumentContent,
} from "../app/api/documents";
import { RenderedContent } from "../app/components/DocViewerPane";
import { SourceBadge } from "../app/components/SourceBadge";
import { ErrorState } from "../app/components/ui/ErrorState";
import { Skeleton } from "../app/components/ui/Skeleton";
import { SideDrawer } from "../app/components/ui/SideDrawer";
import { relativeTime } from "../app/lib/relativeTime";
import { formatShortDate, type TerrainFocusTarget } from "./citationDisplay";

export type SourceInspectorTarget = {
  docId: string;
  heading: string | null;
  /** The chunk excerpt backing the claim — used to locate and highlight the
   *  matching passage once the document renders. */
  excerpt: string;
  updatedAt: string | null;
  sourceUrl: string | null;
  terrainFocus: TerrainFocusTarget | null;
};

/**
 * "View source" — a temporary, evidence-focused document inspector. Slides in
 * from the right like every other drawer in the app, but stops at the Ask
 * dock's left edge (`avoidAskDock`) rather than sliding over it: the whole
 * point of the panel is to read the evidence *against* the answer that cited
 * it, which you can't do if it hides the answer. On any route, in any tab.
 *
 * Deliberately lean: title + a few metadata lines, the passage highlighted
 * and scrolled into view, an optional "Show on map" action, and one
 * close button. No re-harvest/attachments/breadcrumb management chrome —
 * that's DocViewerPane's job on the full documents page, not this one's.
 * The body itself is DocViewerPane's `RenderedContent`, so there is exactly
 * one document renderer in the app wearing two different chromes.
 */
export function SourceInspector({
  target,
  onClose,
  onShowOnTerrain,
}: {
  target: SourceInspectorTarget | null;
  onClose: () => void;
  onShowOnTerrain?: (focus: TerrainFocusTarget) => void;
}) {
  return (
    <SideDrawer
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      width="480px"
      avoidAskDock
    >
      {target ? (
        <SourceInspectorBody
          target={target}
          onShowOnTerrain={
            onShowOnTerrain && target.terrainFocus
              ? () => {
                  onShowOnTerrain(target.terrainFocus!);
                  onClose();
                }
              : undefined
          }
        />
      ) : null}
    </SideDrawer>
  );
}

function SourceInspectorBody({
  target,
  onShowOnTerrain,
}: {
  target: SourceInspectorTarget;
  onShowOnTerrain?: () => void;
}) {
  const doc = useDocument(target.docId);
  const content = useDocumentContent(target.docId);
  const attachments = useDocumentAttachments(target.docId);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current || !content.data?.content) return;
    highlightPassage(containerRef.current, target.excerpt);
  }, [content.data?.content, target.excerpt]);

  if (doc.isError) {
    const status = doc.error instanceof ApiError ? doc.error.status : null;
    return (
      <div className="flex-1 p-6 pt-12">
        {status === 404 ? (
          <ErrorState
            title="Source not found"
            description="It may have been deleted or filtered out since this answer was grounded."
          />
        ) : (
          <ErrorState
            title="Couldn't load source"
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
        <Skeleton variant="line" width="70%" className="h-6" />
        <div className="space-y-2 pt-2">
          <Skeleton variant="line" width="95%" />
          <Skeleton variant="line" width="90%" />
          <Skeleton variant="line" width="60%" />
        </div>
      </div>
    );
  }

  const d = doc.data;
  const format = content.data?.format ?? "raw";

  return (
    <div className="flex h-full flex-col min-h-0">
      <header className="px-5 pt-5 pb-3 border-b border-hair shrink-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="eyebrow">Source</span>
          <SourceBadge source={d.source} size="sm" />
        </div>
        <h3 className="font-serif text-lg text-ink leading-snug pr-6">{d.title}</h3>
        <p className="mt-1 font-sans text-xs text-muted">
          {target.heading ? `${target.heading} · ` : ""}
          {d.updated_at
            ? `updated ${relativeTime(d.updated_at)}`
            : target.updatedAt
              ? formatShortDate(target.updatedAt)
              : null}
        </p>
        {target.terrainFocus && onShowOnTerrain ? (
          <button
            type="button"
            onClick={onShowOnTerrain}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-hair px-2.5 py-1.5 font-sans text-xs text-ink hover:bg-bone/60 transition-colors"
          >
            <Compass size={13} strokeWidth={1.5} aria-hidden />
            Show on map
          </button>
        ) : null}
      </header>

      <div ref={containerRef} className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
        {content.isLoading ? (
          <div className="space-y-2" aria-busy="true">
            <Skeleton variant="line" width="92%" />
            <Skeleton variant="line" width="88%" />
            <Skeleton variant="line" width="95%" />
            <Skeleton variant="line" width="70%" />
          </div>
        ) : (
          <RenderedContent
            source={d.source}
            format={format}
            content={content.data?.content ?? ""}
            attachments={attachments.data?.items}
          />
        )}
      </div>

      {target.sourceUrl ? (
        <footer className="px-5 py-2.5 border-t border-hair shrink-0">
          <a
            href={target.sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-sans text-[11px] text-magenta hover:underline"
          >
            Open original
            <ExternalLink size={11} strokeWidth={1.5} aria-hidden />
          </a>
        </footer>
      ) : null}
    </div>
  );
}

// ── best-effort passage highlight ───────────────────────────────────

const HIGHLIGHT_ATTR = "data-citation-highlight";
const HIGHLIGHT_CLASSES = ["bg-magenta/10", "ring-1", "ring-magenta/25", "rounded-md"];
const HIGHLIGHT_SELECTOR = "p, li, blockquote, pre, h1, h2, h3, h4, h5, h6, td, dd";

/** Strip markdown syntax + collapse whitespace so a raw chunk excerpt can be
 *  matched against the *rendered* (plain-text) document body, which won't
 *  contain the `**`/`#`/etc. markup the excerpt came from. */
function normalizeForMatch(s: string): string {
  return s
    .replace(/[*_`#>~]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Finds the block whose text contains the start of `excerpt` and highlights
 *  + scrolls to it. Best-effort: if chunking/rendering diverged enough that
 *  no block matches, the document still opened with full surrounding
 *  context — it just isn't pre-scrolled. */
function highlightPassage(root: HTMLElement, excerpt: string) {
  root.querySelectorAll(`[${HIGHLIGHT_ATTR}]`).forEach((el) => {
    el.removeAttribute(HIGHLIGHT_ATTR);
    el.classList.remove(...HIGHLIGHT_CLASSES);
  });

  const anchor = normalizeForMatch(excerpt.replace(/…$/, "")).slice(0, 70);
  if (anchor.length < 12) return; // too short to be a reliable anchor

  for (const el of Array.from(root.querySelectorAll(HIGHLIGHT_SELECTOR))) {
    if (normalizeForMatch(el.textContent || "").includes(anchor)) {
      el.setAttribute(HIGHLIGHT_ATTR, "true");
      el.classList.add(...HIGHLIGHT_CLASSES);
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
  }
}
