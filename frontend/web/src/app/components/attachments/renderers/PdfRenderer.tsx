// PDF preview renderer.
//
// Built on react-pdf (pdf.js bindings) with per-page virtualization via
// @tanstack/react-virtual so a 500-page PDF only mounts ~5 pages at a time.
// The renderer owns its own top toolbar (zoom, rotate, search, print,
// thumbnails) because those controls are PDF-specific; cross-renderer
// chrome (pagination indicator + Cmd-F intercept) is still reported up
// to AttachmentViewer via the ChromeState contract.
//
// Failure modes covered:
//  - encrypted PDFs: onPassword → inline themed prompt; re-load with pw
//  - corrupted/unreachable PDFs: onLoadError → themed ErrorState; the
//    RendererFrame error boundary is the backstop for crashes during render
//  - mid-load close: aliveRef + AbortController guard async work (text
//    extraction, natural-size fetch) so closing the modal mid-load doesn't
//    setState on an unmounted tree

import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Document, pdfjs } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Lock } from "lucide-react";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "../../../theme/pdf.css";
import { Button } from "../../ui/Button";
import { ErrorState } from "../../ui/ErrorState";
import { Skeleton } from "../../ui/Skeleton";
import type { RendererProps } from "../registry";
import { PdfToolbar } from "./pdf/PdfToolbar";
import { ThumbnailSidebar } from "./pdf/ThumbnailSidebar";
import { PrintDialog } from "./pdf/PrintDialog";
import { PdfPage } from "./pdf/PdfPage";
import {
  buildIndex,
  findMatches,
  groupMatchesByPage,
  createPageHighlighter,
  type PageText,
} from "./pdf/searchIndex";
import {
  computeZoomForMode,
  getPageDimensions,
  initialPdfState,
  pdfReducer,
} from "./pdf/state";

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

// Horizontal padding around each page in the main scroll container.
const PAGE_GUTTER = 24;
// Vertical gap between pages.
const PAGE_GAP = 16;
// Manual ± step from the keyboard zoom shortcut.
const ZOOM_STEP = 0.1;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 5.0;

export default function PdfRenderer({
  inlineUrl,
  onChrome,
  attachment,
}: RendererProps) {
  const [state, dispatch] = useReducer(pdfReducer, initialPdfState);
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerWidthRef = useRef<number>(0);
  const containerHeightRef = useRef<number>(0);
  const aliveRef = useRef(true);
  const indexRef = useRef<PageText[]>([]);
  const indexAbortRef = useRef<AbortController | null>(null);
  // When set, the next text-layer render for that page should scroll the
  // active mark into view. Cleared once consumed.
  const pendingScrollRef = useRef<number | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      indexAbortRef.current?.abort();
    };
  }, []);

  const documentFile = useMemo(
    () => ({ url: inlineUrl, withCredentials: false }),
    [inlineUrl],
  );
  const documentOptions = useMemo(
    () => (state.password ? { password: state.password } : undefined),
    [state.password],
  );

  // Virtualizer drives the main scroll list. estimateSize is queried per
  // index — we use getPageDimensions which honors per-page rotation +
  // current zoom + container.
  const virtualizer = useVirtualizer({
    count: state.numPages ?? 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const { height } = getPageDimensions(
        state,
        index + 1,
        containerWidthRef.current,
        containerHeightRef.current,
      );
      return height + PAGE_GAP;
    },
    // Keep more off-screen pages rendered so normal scrolling rarely hits an
    // unrendered page (which would re-rasterize and flash). 5 ≈ ±5 pages
    // mounted — cheap even for long PDFs, much smoother than the old 2.
    overscan: 5,
  });

  // Recompute virtualizer sizes when zoom, rotations, or natural change.
  // The estimator captures `state` by reference; remeasure forces a fresh pass.
  useEffect(() => {
    virtualizer.measure();
  }, [state.zoom, state.rotations, state.natural, virtualizer]);

  // Derive the active page from scroll position (which virtualizer surfaces
  // via getVirtualItems). We compare to currentPage to avoid a re-render
  // loop when the value hasn't changed; setCurrentPage is itself a no-op
  // in the reducer if the value matches.
  const virtualItems = virtualizer.getVirtualItems();
  useEffect(() => {
    if (virtualItems.length === 0) return;
    const first = virtualItems[0];
    dispatch({ type: "setCurrentPage", page: first.index + 1 });
  }, [virtualItems]);

  // Measure container on mount + resize. After a resize we also re-derive
  // the zoom value if the user is in a fit-* mode.
  //
  // NOTE the `state.numPages` dep: the scroll element lives INSIDE <Document>,
  // which renders its `loading` prop (not children) until the PDF parses — so
  // `scrollRef.current` is null on first mount and this effect would early-
  // return forever (virtualizer identity is stable). Re-running when numPages
  // flips null→N attaches the observer + measures once the scroll div exists,
  // which the fit-page/fit-width zoom derivation depends on.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      containerWidthRef.current = el.clientWidth;
      containerHeightRef.current = el.clientHeight;
      // Trigger the zoom-from-mode effect via a state read in next tick.
      // Easiest: dispatch a no-op setZoomMode of the current mode — but
      // that's hacky. Instead, the derive effect below also runs on
      // initial mount; manual resize relies on the same path by re-reading
      // state via the next render. We force one via virtualizer.measure().
      virtualizer.measure();
    });
    ro.observe(el);
    containerWidthRef.current = el.clientWidth;
    containerHeightRef.current = el.clientHeight;
    return () => ro.disconnect();
  }, [virtualizer, state.numPages]);

  // Derive zoom value when mode or natural changes. Skipped for "custom"
  // since that's user-driven. We keep this in an effect (not the reducer)
  // because it depends on container dimensions which live in refs.
  useEffect(() => {
    if (state.zoomMode === "custom") return;
    const derived = computeZoomForMode(
      state.zoomMode,
      state.natural,
      containerWidthRef.current,
      containerHeightRef.current,
      PAGE_GUTTER,
    );
    if (derived === null) return;
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, derived));
    dispatch({ type: "setDerivedZoom", value: clamped });
  }, [state.zoomMode, state.natural]);

  // Document lifecycle. onLoadSuccess fires once pdf.js has parsed the
  // outline; we read page 1's natural size and kick off text indexing.
  const handleDocLoad = useCallback(async (pdf: PDFDocumentProxy) => {
    if (!aliveRef.current) return;
    dispatch({ type: "docLoaded", numPages: pdf.numPages });

    try {
      const page = await pdf.getPage(1);
      if (!aliveRef.current) return;
      // getViewport() defaults to the page's intrinsic rotation, so vp's
      // width/height are already in display orientation. We capture page.rotate
      // separately so the render can re-apply the exact same rotation.
      const vp = page.getViewport({ scale: 1 });
      dispatch({
        type: "setNatural",
        natural: { width: vp.width, height: vp.height },
        rotation: ((page.rotate % 360) + 360) % 360 as 0 | 90 | 180 | 270,
      });
    } catch {
      // Virtualizer falls back to its estimate if we can't read natural size.
    }

    // Background text indexing for search. Aborted on unmount.
    indexAbortRef.current?.abort();
    const controller = new AbortController();
    indexAbortRef.current = controller;
    dispatch({
      type: "setIndexing",
      indexing: { done: 0, total: pdf.numPages },
    });
    try {
      const pages = await buildIndex(
        pdf,
        (done, total) => {
          if (!aliveRef.current) return;
          dispatch({ type: "setIndexing", indexing: { done, total } });
        },
        controller.signal,
      );
      if (!aliveRef.current) return;
      indexRef.current = pages;
      dispatch({ type: "setIndexing", indexing: null });
      // Bump indexVersion so the match-recompute effect re-runs against
      // the now-complete index. Avoids a stale-closure trap: a previous
      // version of this branch read `state.search.query` from the closure,
      // which captures "" at first render and never sees what the user
      // typed mid-indexing.
      dispatch({ type: "indexBuilt" });
    } catch {
      // Aborted — nothing to do.
    }
  }, []);

  // Recompute matches when query OR index changes. indexVersion bumps when
  // background indexing finishes, so a query typed mid-indexing gets its
  // matches once the index lands.
  useEffect(() => {
    if (!state.search.query) {
      dispatch({ type: "setMatches", matches: [] });
      return;
    }
    if (indexRef.current.length === 0) return;
    const matches = findMatches(indexRef.current, state.search.query);
    dispatch({ type: "setMatches", matches });
  }, [state.search.query, state.indexVersion]);

  // When the active match changes, scroll to its page. After the text
  // layer renders we scroll the specific <mark> into view.
  const activeMatch =
    state.search.activeIndex >= 0
      ? state.search.matches[state.search.activeIndex]
      : null;
  useEffect(() => {
    if (!activeMatch) return;
    pendingScrollRef.current = activeMatch.pageNumber;
    virtualizer.scrollToIndex(activeMatch.pageNumber - 1, { align: "center" });
    // Best-effort: after one frame, if the page is already rendered, scroll
    // the mark into view. If not, the per-page onRenderTextLayerSuccess
    // callback below handles it once render completes.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollActiveMarkIntoView());
    });
    // virtualizer identity is stable; omit to avoid re-running on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMatch]);

  function scrollActiveMarkIntoView() {
    const root = scrollRef.current;
    if (!root) return;
    const mark = root.querySelector<HTMLElement>('mark[data-active="true"]');
    if (mark) {
      mark.scrollIntoView({ block: "center", behavior: "smooth" });
      pendingScrollRef.current = null;
    }
  }

  function handleTextLayerRendered(pageNumber: number) {
    if (pendingScrollRef.current === pageNumber) {
      scrollActiveMarkIntoView();
    }
  }

  // Internal keyboard shortcuts for zoom (since zoom no longer lives in
  // ChromeState, the AttachmentViewer-global handler can't drive it).
  // Page-navigation shortcuts still come from the global handler via the
  // pagination chrome we report below.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (
        tgt &&
        (tgt.tagName === "INPUT" ||
          tgt.tagName === "TEXTAREA" ||
          tgt.isContentEditable)
      ) {
        return;
      }
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        dispatch({
          type: "setZoom",
          value: Math.min(MAX_ZOOM, +(state.zoom + ZOOM_STEP).toFixed(2)),
        });
      } else if (e.key === "-") {
        e.preventDefault();
        dispatch({
          type: "setZoom",
          value: Math.max(MIN_ZOOM, +(state.zoom - ZOOM_STEP).toFixed(2)),
        });
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [state.zoom]);

  // Report pagination + onFind up to the modal chrome.
  const goto = useCallback((page: number) => {
    dispatch({ type: "goto", page });
    virtualizer.scrollToIndex(page - 1, { align: "start" });
    // virtualizer identity is stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openSearch = useCallback(() => {
    dispatch({ type: "openSearch" });
  }, []);

  useEffect(() => {
    onChrome({
      pagination:
        state.numPages != null
          ? { current: state.currentPage, total: state.numPages, goto }
          : undefined,
      onFind: openSearch,
    });
  }, [state.numPages, state.currentPage, goto, openSearch, onChrome]);

  // Per-page customTextRenderer cache. Built once per (matches, activeMatch)
  // change so the prop identity stays stable across unrelated re-renders
  // (e.g. scroll-position updates) — otherwise react-pdf would re-lay out
  // the text layer on every parent render for any page with matches.
  const matchesByPage = useMemo(
    () => groupMatchesByPage(state.search.matches),
    [state.search.matches],
  );

  const highlighters = useMemo(() => {
    if (!state.search.open) return new Map<number, ReturnType<typeof createPageHighlighter>>();
    const m = new Map<number, ReturnType<typeof createPageHighlighter>>();
    matchesByPage.forEach((matchesOnPage, pageNumber) => {
      const pageText = indexRef.current[pageNumber - 1];
      if (!pageText) return;
      const fn = createPageHighlighter(pageText, matchesOnPage, activeMatch);
      if (fn) m.set(pageNumber, fn);
    });
    return m;
  }, [state.search.open, matchesByPage, activeMatch]);

  // Inline render guards — fully replace the document view.
  if (state.loadError) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center overflow-y-auto p-6">
        <ErrorState
          title="Can't open this PDF"
          description={state.loadError.message || "The file may be corrupted or unreadable."}
          onRetry={() => {
            dispatch({ type: "setLoadError", error: null });
            dispatch({ type: "setPassword", password: null });
          }}
        />
      </div>
    );
  }

  if (state.pendingPassword) {
    return (
      <PasswordPrompt
        reason={state.pendingPassword.reason}
        filename={attachment.name}
        onSubmit={(pw) => {
          state.pendingPassword?.callback(pw);
          dispatch({ type: "setPassword", password: pw });
          dispatch({ type: "setPendingPassword", pending: null });
        }}
      />
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <PdfToolbar
        numPages={state.numPages}
        currentPage={state.currentPage}
        sidebarOpen={state.sidebarOpen}
        zoom={state.zoom}
        zoomMode={state.zoomMode}
        searchOpen={state.search.open}
        searchOpenVersion={state.search.openVersion}
        searchQuery={state.search.query}
        matches={state.search.matches}
        activeMatchIndex={state.search.activeIndex}
        indexing={state.indexing}
        onToggleSidebar={() => dispatch({ type: "toggleSidebar" })}
        onGoto={goto}
        onRotateCurrentPage={() =>
          dispatch({ type: "rotatePage", pageNumber: state.currentPage })
        }
        onZoomChange={(value) => dispatch({ type: "setZoom", value })}
        onZoomModeChange={(mode) => dispatch({ type: "setZoomMode", mode })}
        onOpenSearch={openSearch}
        onCloseSearch={() => dispatch({ type: "closeSearch" })}
        onSearchQueryChange={(query) =>
          dispatch({ type: "setSearchQuery", query })
        }
        onNextMatch={() => dispatch({ type: "nextMatch" })}
        onPrevMatch={() => dispatch({ type: "prevMatch" })}
        onOpenPrint={() => dispatch({ type: "openPrint" })}
      />

      {/* The <Document> is the flex row wrapping BOTH the thumbnail sidebar
          and the main scroll area, so the sidebar's <Page> thumbnails share
          the same react-pdf Document context (and the same parsed pdf.js
          instance) as the main pages. Rendering the sidebar outside Document
          throws — that was the "Can't preview this file" crash. */}
      <Document
        file={documentFile}
        options={documentOptions}
        onLoadSuccess={handleDocLoad}
        onLoadError={(err) => dispatch({ type: "setLoadError", error: err })}
        onLoadProgress={({ loaded, total }) => {
          if (total) {
            dispatch({ type: "setProgress", progress: { loaded, total } });
          }
        }}
        onPassword={(callback: (pw: string) => void, reason: number) => {
          dispatch({
            type: "setPendingPassword",
            pending: { callback, reason },
          });
        }}
        loading={<DocLoading progress={state.progress} />}
        error={<span className="sr-only">Failed to load PDF</span>}
        noData={<span className="sr-only">No PDF data</span>}
        className="flex-1 min-h-0 flex flex-row overflow-hidden"
      >
        {state.sidebarOpen && state.numPages != null && (
          <ThumbnailSidebar
            numPages={state.numPages}
            currentPage={state.currentPage}
            rotations={state.rotations}
            naturalRotation={state.naturalRotation}
            onSelect={goto}
          />
        )}

        <div
          ref={scrollRef}
          className="attachment-pdf flex-1 min-h-0 overflow-y-auto overflow-x-auto"
          tabIndex={0}
          aria-label="PDF document"
        >
          {state.numPages !== null && state.natural !== null && (
            <div
              style={{
                height: virtualizer.getTotalSize(),
                width: "100%",
                position: "relative",
                paddingTop: PAGE_GAP,
                paddingBottom: PAGE_GAP,
              }}
            >
              {virtualItems.map((v) => {
                const pageNumber = v.index + 1;
                const { width, height } = getPageDimensions(
                  state,
                  pageNumber,
                  containerWidthRef.current,
                  containerHeightRef.current,
                );
                return (
                  <div
                    key={v.key}
                    data-index={v.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      right: 0,
                      transform: `translateY(${v.start}px)`,
                      paddingLeft: PAGE_GUTTER,
                      paddingRight: PAGE_GUTTER,
                      paddingBottom: PAGE_GAP,
                    }}
                  >
                    <PdfPage
                      pageNumber={pageNumber}
                      width={width}
                      rotation={
                        ((state.naturalRotation +
                          (state.rotations[pageNumber] ?? 0)) %
                          360) as 0 | 90 | 180 | 270
                      }
                      customTextRenderer={highlighters.get(pageNumber) ?? undefined}
                      loading={<PageSkeleton height={height} />}
                      onRenderTextLayerSuccess={() =>
                        handleTextLayerRendered(pageNumber)
                      }
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Document>

      <PrintDialog
        open={state.printOpen}
        inlineUrl={inlineUrl}
        filename={attachment.name}
        onClose={() => dispatch({ type: "closePrint" })}
      />
    </div>
  );
}

function formatMb(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DocLoading({
  progress,
}: {
  progress: { loaded: number; total: number } | null;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4" aria-busy>
      <Skeleton variant="block" aspectRatio="3/4" width="min(520px, 80%)" />
      {progress && (
        <p className="font-mono text-[11px] text-muted tabular-nums">
          Loading {formatMb(progress.loaded)} / {formatMb(progress.total)}
        </p>
      )}
    </div>
  );
}

function PageSkeleton({ height }: { height: number }) {
  return (
    <div
      className="pdf-page-skeleton rounded-md animate-skeleton-pulse motion-reduce:animate-none"
      style={{ height }}
      aria-hidden
    />
  );
}

function PasswordPrompt({
  reason,
  filename,
  onSubmit,
}: {
  reason: number;
  filename: string;
  onSubmit: (pw: string) => void;
}) {
  const [value, setValue] = useState("");

  function handle(e: FormEvent) {
    e.preventDefault();
    if (value) onSubmit(value);
  }

  return (
    <div className="flex-1 min-h-0 flex items-center justify-center p-6">
      <form
        onSubmit={handle}
        className="flex flex-col items-center text-center max-w-[40ch]"
      >
        <div className="w-14 h-14 rounded-2xl bg-bone/70 border border-hair flex items-center justify-center mb-4">
          <Lock size={22} strokeWidth={1.5} className="text-muted" aria-hidden />
        </div>
        <h3 className="font-serif text-xl text-ink leading-tight">
          Password-protected PDF
        </h3>
        <p className="font-sans text-sm text-muted mt-2 leading-relaxed">
          {reason === 2
            ? "That password didn't match. Try again."
            : `Enter the password to view ${filename}.`}
        </p>
        <input
          type="password"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mt-5 w-full px-3 py-2 rounded-full border border-hair bg-bg text-ink font-sans text-sm focus:outline-none focus:border-magenta focus:ring-2 focus:ring-magenta/30 text-center"
          placeholder="Password"
        />
        <Button
          type="submit"
          variant="primary"
          size="md"
          className="mt-4"
          disabled={!value}
        >
          Unlock
        </Button>
      </form>
    </div>
  );
}
