import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp, FileText, Inbox } from "lucide-react";
import { Link } from "react-router-dom";
import type { DocRow } from "../api/documents";
import { SourceBadge, sourceMeta } from "./SourceBadge";
import { relativeTime } from "../lib/relativeTime";
import { cn } from "../lib/cn";
import { EmptyState } from "./ui/EmptyState";
import { Button } from "./ui/Button";
import { Skeleton } from "./ui/Skeleton";
import type { DocFilters } from "../lib/useDocFilters";

type SortKey = "harvested" | "title" | "source" | "size";
type SortDir = "asc" | "desc";

const ROW_HEIGHT = 56;
const SKELETON_ROW_COUNT = 10;
// Column order matches the grid below: title, source, path, harvested.
// Min widths keep headers from overlapping when the viewer pane is open and
// the table area gets narrow — combined with overflow-x-auto on the scroll
// container they make the table horizontally scrollable.
const MIN_WIDTHS = [200, 100, 140, 100];
const DEFAULT_WIDTHS = [320, 110, 200, 120];
const COL_WIDTHS_STORAGE_KEY = "mnemify.docs.colWidths";

function loadInitialWidths(): number[] {
  if (typeof window === "undefined") return DEFAULT_WIDTHS.slice();
  try {
    const raw = window.localStorage.getItem(COL_WIDTHS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (
        Array.isArray(parsed) &&
        parsed.length === DEFAULT_WIDTHS.length &&
        parsed.every((n) => typeof n === "number" && Number.isFinite(n))
      ) {
        return parsed.map((n, i) => Math.max(n, MIN_WIDTHS[i]));
      }
    }
  } catch {
    /* ignore — fall back to defaults */
  }
  return DEFAULT_WIDTHS.slice();
}

interface DocTableProps {
  rows: DocRow[];
  total: number;
  loading: boolean;
  onSelect: (docId: string) => void;
  filters: DocFilters;
  activeFilterCount: number;
  onClearFilters: () => void;
}

export function DocTable({
  rows,
  total,
  loading,
  onSelect,
  filters,
  activeFilterCount,
  onClearFilters,
}: DocTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("harvested");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const [widths, setWidths] = useState<number[]>(loadInitialWidths);
  const widthsRef = useRef(widths);
  widthsRef.current = widths;

  useEffect(() => {
    try {
      window.localStorage.setItem(COL_WIDTHS_STORAGE_KEY, JSON.stringify(widths));
    } catch {
      /* ignore — private mode etc. */
    }
  }, [widths]);

  const gridTemplate = widths.map((w) => `${w}px`).join(" ");
  // `gap-4` between cells is 16px × (n-1). Width sum + gaps + horizontal
  // padding (px-5 = 20px on each side) keeps rows wide enough that headers
  // never overlap, regardless of available container width.
  const totalRowWidth = widths.reduce((a, b) => a + b, 0) + 16 * (widths.length - 1) + 40;

  function startResize(idx: number) {
    return (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startW = widthsRef.current[idx];

      function onMove(ev: PointerEvent) {
        const dx = ev.clientX - startX;
        const next = Math.max(startW + dx, MIN_WIDTHS[idx]);
        setWidths((ws) => {
          if (ws[idx] === next) return ws;
          const out = ws.slice();
          out[idx] = next;
          return out;
        });
      }
      function onUp() {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        document.body.style.removeProperty("cursor");
        document.body.style.removeProperty("user-select");
      }
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };
  }

  const sorted = useMemo(() => {
    const arr = [...rows];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "harvested") cmp = (a.harvested_at ?? "").localeCompare(b.harvested_at ?? "");
      else if (sortKey === "title") cmp = a.title.localeCompare(b.title);
      else if (sortKey === "source") cmp = a.source.localeCompare(b.source);
      else if (sortKey === "size") cmp = a.size_bytes - b.size_bytes;
      return cmp * dir;
    });
    return arr;
  }, [rows, sortKey, sortDir]);

  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(k);
      setSortDir(k === "title" || k === "source" ? "asc" : "desc");
    }
  }

  function ariaSortFor(k: SortKey): "ascending" | "descending" | "none" {
    if (sortKey !== k) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  }

  if (!loading && sorted.length === 0) {
    const hasFilters = activeFilterCount > 0;
    if (hasFilters) {
      return (
        <div className="bg-bone/40 border border-hair rounded-2xl">
          <EmptyState
            icon={<FileText size={28} strokeWidth={1.5} />}
            title="No documents match"
            description={emptyStateDescription(filters)}
            action={
              <Button variant="secondary" size="md" onClick={onClearFilters}>
                Clear filters
              </Button>
            }
          />
        </div>
      );
    }
    return (
      <div className="bg-bone/40 border border-hair rounded-2xl">
        <EmptyState
          icon={<Inbox size={28} strokeWidth={1.5} />}
          title="Your library is empty"
          description="Run a harvest to populate it."
          action={
            <Link to="/build/harvest">
              <Button variant="primary" size="md">
                Go to Harvest
              </Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="bg-bone/40 border border-hair rounded-2xl overflow-hidden h-full min-h-0 flex flex-col">
      <div className="flex items-center justify-between px-5 py-3 border-b border-hair shrink-0">
        <p className="font-sans text-xs text-muted">
          {loading ? (
            <Skeleton variant="line" width="14ch" className="inline-block align-middle" />
          ) : (
            `${sorted.length.toLocaleString()} of ${total.toLocaleString()} documents`
          )}
        </p>
      </div>
      {loading ? (
        <div className="flex-1 min-h-0 overflow-auto">
          <div style={{ minWidth: totalRowWidth }}>
            <div
              role="row"
              className="grid items-center gap-4 px-5 py-2 border-b border-hair bg-bone"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              <HeaderCell>Title</HeaderCell>
              <HeaderCell>Source</HeaderCell>
              <HeaderCell>Path</HeaderCell>
              <HeaderCell>Harvested</HeaderCell>
            </div>
            {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
              <SkeletonRow key={i} gridTemplate={gridTemplate} />
            ))}
          </div>
        </div>
      ) : (
        <div
          ref={parentRef}
          className="flex-1 min-h-0 overflow-auto"
        >
          {/* `minWidth` forces horizontal scrolling once the table area is
              narrower than the summed column widths. Sticky header stays
              pinned to the top of THIS scroll container, and because the
              inner wrapper has the same minWidth, header columns line up
              with row columns at any scroll offset. */}
          <div style={{ minWidth: totalRowWidth }}>
            <div
              role="row"
              className="sticky top-0 z-10 grid items-center gap-4 px-5 py-2 border-b border-hair bg-bone"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              <ResizableHeaderCell onResize={startResize(0)}>
                <SortHeader k="title" current={sortKey} dir={sortDir} onClick={toggleSort} ariaSort={ariaSortFor("title")}>Title</SortHeader>
              </ResizableHeaderCell>
              <ResizableHeaderCell onResize={startResize(1)}>
                <SortHeader k="source" current={sortKey} dir={sortDir} onClick={toggleSort} ariaSort={ariaSortFor("source")}>Source</SortHeader>
              </ResizableHeaderCell>
              <ResizableHeaderCell onResize={startResize(2)}>
                <HeaderCell>Path</HeaderCell>
              </ResizableHeaderCell>
              <ResizableHeaderCell onResize={startResize(3)}>
                <SortHeader k="harvested" current={sortKey} dir={sortDir} onClick={toggleSort} ariaSort={ariaSortFor("harvested")}>Harvested</SortHeader>
              </ResizableHeaderCell>
            </div>
            <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
              {rowVirtualizer.getVirtualItems().map((vrow) => {
                const doc = sorted[vrow.index];
                return (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => onSelect(doc.id)}
                    className={cn(
                      "absolute top-0 left-0 text-left grid items-center gap-4 px-5",
                      "border-b border-hair/50 hover:bg-cream/60 transition-colors",
                    )}
                    style={{
                      height: ROW_HEIGHT,
                      transform: `translateY(${vrow.start}px)`,
                      width: "100%",
                      gridTemplateColumns: gridTemplate,
                    }}
                  >
                    <div className="min-w-0">
                      <p className="font-serif text-sm text-ink truncate">{doc.title}</p>
                      {doc.excerpt && (
                        <p className="font-sans text-[11px] text-muted truncate mt-0.5">{doc.excerpt}</p>
                      )}
                    </div>
                    <SourceBadge source={doc.source} size="sm" />
                    <DocPathCell doc={doc} />
                    <span className="font-sans text-xs text-muted tabular-nums">
                      {doc.harvested_at ? relativeTime(doc.harvested_at) : "—"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function formatBytes(n: number): string {
  if (!n || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function emptyStateDescription(filters: DocFilters): string {
  // Surface the most restrictive filter first — a free-text search is more
  // specific than a category filter, so search wins when both are active.
  if (filters.search) {
    return `Your search for "${filters.search}" has no matches.`;
  }
  if (filters.sources.length === 1) {
    return `Try removing the Source: ${sourceMeta(filters.sources[0]).label} filter.`;
  }
  if (filters.sources.length > 1) {
    const labels = filters.sources.map((s) => sourceMeta(s).label).join(", ");
    return `Try removing one of the Source filters (${labels}).`;
  }
  return "Try adjusting your filters.";
}

function HeaderCell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      role="columnheader"
      className={cn(
        "font-sans uppercase tracking-eyebrow text-[10px] text-muted/90 flex items-center",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Wraps a header cell with a draggable handle on its right edge. The handle
 *  sits centered in the grid gap so it doesn't obscure adjacent content, and
 *  highlights on hover/drag. */
function ResizableHeaderCell({
  children,
  onResize,
}: {
  children: React.ReactNode;
  onResize: (e: React.PointerEvent) => void;
}) {
  return (
    <div className="relative flex items-center min-w-0">
      <div className="min-w-0 flex-1 flex items-center">{children}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        onPointerDown={onResize}
        className="absolute top-0 -right-3 h-full w-3 cursor-col-resize group flex items-center justify-center"
      >
        <span
          aria-hidden
          className="h-4 w-px bg-hair-strong/0 group-hover:bg-magenta/60 transition-colors"
        />
      </div>
    </div>
  );
}

function SortHeader({
  k, current, dir, onClick, className, children, ariaSort,
}: {
  k: SortKey; current: SortKey; dir: SortDir; onClick: (k: SortKey) => void;
  className?: string; children: React.ReactNode;
  ariaSort: "ascending" | "descending" | "none";
}) {
  const active = current === k;
  return (
    <button
      type="button"
      role="columnheader"
      aria-sort={ariaSort}
      onClick={() => onClick(k)}
      className={cn(
        "flex items-center gap-1 font-sans uppercase tracking-eyebrow text-[10px] transition-colors min-w-0",
        active ? "text-ink" : "text-muted/90 hover:text-ink",
        className,
      )}
    >
      <span className="truncate">{children}</span>
      {active && (dir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
    </button>
  );
}

function SkeletonRow({ gridTemplate }: { gridTemplate: string }) {
  return (
    <div
      className="grid items-center gap-4 px-5 border-b border-hair/50"
      style={{ height: ROW_HEIGHT, gridTemplateColumns: gridTemplate }}
      aria-hidden="true"
    >
      <div className="min-w-0 space-y-1.5">
        <Skeleton variant="line" width="60%" />
        <Skeleton variant="line" width="40%" className="text-[11px]" />
      </div>
      <Skeleton variant="line" width="70%" />
      <Skeleton variant="line" width="80%" />
      <Skeleton variant="line" width="70%" />
    </div>
  );
}

/** Render a doc's ancestor path as truncated breadcrumb. Shows only the last
 *  two segments inline (so the column reads well at any width) and the full
 *  chain on hover via the title attribute. Falls back to `doc.space` when
 *  no path is available — that's the legacy column the user used to see. */
function DocPathCell({ doc }: { doc: DocRow }) {
  const path = doc.path_titles ?? [];
  if (path.length === 0) {
    return <span className="font-sans text-xs text-ink/80 truncate">{doc.space || "—"}</span>;
  }
  const visible = path.length <= 2 ? path : ["…", ...path.slice(-2)];
  return (
    <span
      className="font-sans text-xs text-ink/80 truncate"
      title={path.join(" › ")}
    >
      {visible.join(" › ")}
    </span>
  );
}
