// Google-Drive-style centered modal for previewing attachments.
//
// Wraps ui/Dialog (Radix-based — already handles centered position, backdrop
// blur, focus trap, Esc-to-close, enter animation, motion-reduce). We size
// it large (95vw × 90vh) for document content; renderer dispatch goes through
// the registry so each format lives in its own lazy-loaded chunk.

import {
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Download, ExternalLink } from "lucide-react";
import { Dialog, DialogClose } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { apiUrl } from "../../api/client";
import type { DocAttachment } from "../../api/documents";
import { pickRenderer, type ChromeState } from "./registry";
import { RendererFrame } from "./RendererFrame";

interface AttachmentViewerProps {
  attachment: DocAttachment | null;
  onClose: () => void;
}

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function AttachmentViewer({ attachment, onClose }: AttachmentViewerProps) {
  // The actual modal mounts only when we have an attachment; once mounted the
  // renderer subtree stays stable until the modal closes, so its lazy chunk
  // doesn't re-import on every parent re-render.
  return (
    <Dialog
      open={!!attachment}
      onOpenChange={(v) => !v && onClose()}
      width="95vw"
      ariaLabel={attachment ? `Preview ${attachment.name}` : "Attachment preview"}
      // Fixed height (not just max-h) so the modal stays a constant size — a
      // short or zoomed-out page must not collapse the content-driven height.
      className="h-[90vh] !max-h-[90vh] !rounded-2xl"
    >
      {attachment && (
        <ViewerBody attachment={attachment} onClose={onClose} />
      )}
    </Dialog>
  );
}

function ViewerBody({
  attachment,
  onClose,
}: {
  attachment: DocAttachment;
  onClose: () => void;
}) {
  const inlineUrl = apiUrl(`${attachment.url}?inline=1`);
  const downloadUrl = apiUrl(attachment.url);

  const [chrome, setChrome] = useState<ChromeState>({});
  // Renderers call `onChrome` from effects; wrap in a stable callback so they
  // don't pin a fresh setter on every parent render.
  const onChrome = useCallback((next: ChromeState) => setChrome(next), []);

  // Modal-global keyboard shortcuts. Reads chrome via ref so the listener
  // doesn't recreate every time pagination / zoom values update.
  const chromeRef = useRef(chrome);
  useEffect(() => {
    chromeRef.current = chrome;
  }, [chrome]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      // Don't intercept typing in form fields (password prompts, future
      // search inputs). Buttons / divs are fair game.
      if (
        tgt &&
        (tgt.tagName === "INPUT" ||
          tgt.tagName === "TEXTAREA" ||
          tgt.isContentEditable)
      ) {
        return;
      }
      const c = chromeRef.current;
      switch (e.key) {
        case "ArrowRight":
          if (c.sheets) {
            e.preventDefault();
            c.sheets.select(
              Math.min(c.sheets.names.length - 1, c.sheets.active + 1),
            );
          } else if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(
              Math.min(c.pagination.total, c.pagination.current + 1),
            );
          }
          break;
        case "ArrowLeft":
          if (c.sheets) {
            e.preventDefault();
            c.sheets.select(Math.max(0, c.sheets.active - 1));
          } else if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(Math.max(1, c.pagination.current - 1));
          }
          break;
        case "ArrowDown":
        case "PageDown":
          if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(
              Math.min(c.pagination.total, c.pagination.current + 1),
            );
          }
          break;
        case "ArrowUp":
        case "PageUp":
          if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(Math.max(1, c.pagination.current - 1));
          }
          break;
        case "Home":
          if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(1);
          }
          break;
        case "End":
          if (c.pagination) {
            e.preventDefault();
            c.pagination.goto(c.pagination.total);
          }
          break;
        case "+":
        case "=":
          if (c.zoom) {
            e.preventDefault();
            c.zoom.set(Math.min(3, +(c.zoom.value + 0.1).toFixed(2)));
          }
          break;
        case "-":
          if (c.zoom) {
            e.preventDefault();
            c.zoom.set(Math.max(0.5, +(c.zoom.value - 0.1).toFixed(2)));
          }
          break;
        case "f":
        case "F":
          if (e.metaKey || e.ctrlKey) {
            // Renderers with cross-document search (PDF) intercept browser
            // Cmd/Ctrl-F because virtualization makes native find miss
            // off-screen pages. Renderers without search leave it alone.
            if (c.onFind) {
              e.preventDefault();
              c.onFind();
            }
          } else if (c.zoom) {
            e.preventDefault();
            c.zoom.fitWidth();
          }
          break;
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const entry = useMemo(() => pickRenderer(attachment), [attachment]);
  // Stable lazy component per renderer id — guards against re-imports if a
  // sibling state change rerenders ViewerBody. Keyed by entry.id, since
  // changing attachment to a different format remounts ViewerBody anyway.
  const Renderer = useMemo(() => lazy(entry.load), [entry]);

  function triggerDownload() {
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = attachment.name;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <DialogClose onClose={onClose} />
      <header className="px-6 pt-5 pb-4 border-b border-hair shrink-0 flex items-start justify-between gap-4 pr-14">
        <div className="flex-1 min-w-0">
          <p className="eyebrow mb-1">Attachment</p>
          <h2
            className="font-serif text-xl text-ink leading-snug truncate"
            title={attachment.name}
          >
            {attachment.name}
          </h2>
          <p className="font-mono text-[11px] text-muted mt-1.5">
            {attachment.mime || "unknown type"} · {humanBytes(attachment.size_bytes)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <a
            href={inlineUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open in new tab"
            title="Open in new tab"
            className="inline-flex items-center justify-center h-9 w-9 rounded-full text-muted hover:text-ink hover:bg-bone/60 transition-colors"
          >
            <ExternalLink size={15} strokeWidth={1.5} aria-hidden />
          </a>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={triggerDownload}
          >
            <Download size={13} strokeWidth={1.75} aria-hidden />
            Download
          </Button>
        </div>
      </header>

      <section className="flex-1 min-h-0 flex flex-col bg-bone/30 overflow-hidden">
        <RendererFrame downloadUrl={downloadUrl} filename={attachment.name}>
          <Renderer
            attachment={attachment}
            inlineUrl={inlineUrl}
            downloadUrl={downloadUrl}
            onChrome={onChrome}
          />
        </RendererFrame>
      </section>

      <ViewerFooter chrome={chrome} />
    </div>
  );
}

function ViewerFooter({ chrome }: { chrome: ChromeState }) {
  const hasAnyChrome =
    !!chrome.pagination ||
    !!chrome.sheets ||
    !!chrome.zoom ||
    !!chrome.footerExtra;

  if (!hasAnyChrome) {
    return (
      <footer
        className="px-6 py-2.5 border-t border-hair shrink-0 font-sans text-[10px] text-muted uppercase tracking-eyebrow"
        aria-live="polite"
      >
        {/* Empty placeholder — keeps modal height stable across renderers. */}
        <span className="invisible">·</span>
      </footer>
    );
  }

  return (
    <footer
      className="px-6 py-2.5 border-t border-hair shrink-0 flex items-center justify-between gap-3 font-sans text-[11px] text-ink"
      aria-live="polite"
    >
      <div className="flex items-center gap-3 min-w-0">
        {chrome.sheets && <SheetTabs sheets={chrome.sheets} />}
      </div>
      <div className="flex items-center gap-4 shrink-0">
        {chrome.pagination && (
          <PaginationControls
            pagination={chrome.pagination}
            // When a renderer ships its own toolbar (signaled by NOT setting
            // chrome.zoom — see PDF), the footer indicator is read-only.
            // Renderers that rely on footer chrome get the full prev/next.
            compact={!chrome.zoom}
          />
        )}
        {chrome.zoom && <ZoomControls zoom={chrome.zoom} />}
        {chrome.footerExtra && <span>{chrome.footerExtra}</span>}
      </div>
    </footer>
  );
}

function PaginationControls({
  pagination,
  compact = false,
}: {
  pagination: NonNullable<ChromeState["pagination"]>;
  compact?: boolean;
}) {
  const { current, total, goto } = pagination;
  if (compact) {
    return (
      <span
        className="font-mono tabular-nums text-[11px] text-muted"
        aria-label={`Page ${current} of ${total}`}
      >
        {current} / {total}
      </span>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => goto(Math.max(1, current - 1))}
        disabled={current <= 1}
        className="px-2 py-1 rounded text-muted hover:text-ink disabled:opacity-disabled disabled:pointer-events-none"
        aria-label="Previous page"
      >
        ‹
      </button>
      <span className="font-mono tabular-nums text-[11px]" aria-label={`Page ${current} of ${total}`}>
        {current} / {total}
      </span>
      <button
        type="button"
        onClick={() => goto(Math.min(total, current + 1))}
        disabled={current >= total}
        className="px-2 py-1 rounded text-muted hover:text-ink disabled:opacity-disabled disabled:pointer-events-none"
        aria-label="Next page"
      >
        ›
      </button>
    </div>
  );
}

function ZoomControls({ zoom }: { zoom: NonNullable<ChromeState["zoom"]> }) {
  const { value, set, fitWidth } = zoom;
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => set(Math.max(0.5, value - 0.1))}
        className="px-2 py-1 rounded text-muted hover:text-ink"
        aria-label="Zoom out"
      >
        −
      </button>
      <span className="font-mono tabular-nums text-[11px] min-w-[3ch] text-center">
        {Math.round(value * 100)}%
      </span>
      <button
        type="button"
        onClick={() => set(Math.min(3, value + 0.1))}
        className="px-2 py-1 rounded text-muted hover:text-ink"
        aria-label="Zoom in"
      >
        +
      </button>
      <button
        type="button"
        onClick={fitWidth}
        className="ml-1 px-2 py-1 rounded text-muted hover:text-ink font-sans text-[10px] uppercase tracking-eyebrow"
        aria-label="Fit width"
      >
        Fit
      </button>
    </div>
  );
}

function SheetTabs({ sheets }: { sheets: NonNullable<ChromeState["sheets"]> }) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto min-w-0" role="tablist">
      {sheets.names.map((name, i) => {
        const active = i === sheets.active;
        return (
          <button
            key={`${i}-${name}`}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => sheets.select(i)}
            className={
              "px-2.5 py-1 rounded-md font-sans text-[11px] whitespace-nowrap transition-colors " +
              (active
                ? "bg-cream text-ink border-b-2 border-magenta"
                : "text-muted hover:text-ink hover:bg-bone/60")
            }
          >
            {name}
          </button>
        );
      })}
    </div>
  );
}

// Re-exported as a no-op convenience so render-only files can detect a no-op
// chrome update without importing the type elsewhere.
export type { ChromeState } from "./registry";
export const NoopChrome: ReactNode = null;
