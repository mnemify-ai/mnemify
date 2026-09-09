import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowUp } from "lucide-react";
import { SourceDot } from "./SourceBadge";
import { cn } from "../lib/cn";
import type { StreamLogEntry } from "../sse/useHarvestStream";

interface LiveLogTailProps {
  entries: StreamLogEntry[];
  /** Auto-scroll to newest on new entries unless the user scrolled away. */
  autoScroll?: boolean;
  /** Total height of the viewport. */
  height?: number;
}

const ROW_HEIGHT = 56;
// Pixel slack used when deciding whether the user is "at" an edge of the
// scroll container. Anything within this many px counts as "pinned".
const EDGE_EPSILON = 8;

export function LiveLogTail({
  entries,
  autoScroll = true,
  height = 480,
}: LiveLogTailProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  // Track both edges so we can show scroll-shadows on the side(s) where there
  // is more content out of view. `atTop` doubles as the auto-scroll gate: if
  // the user has scrolled away from the newest (top) row, we pause.
  const [atTop, setAtTop] = useState(true);
  const [atBottom, setAtBottom] = useState(true);

  const rowVirtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  });

  // Auto-scroll to top on new entry (entries are newest-first). Paused while
  // the user is anywhere other than the top edge.
  useEffect(() => {
    if (!autoScroll || !atTop) return;
    if (parentRef.current) {
      parentRef.current.scrollTop = 0;
    }
  }, [entries.length, autoScroll, atTop]);

  function handleScroll() {
    const el = parentRef.current;
    if (!el) return;
    const nextAtTop = el.scrollTop <= EDGE_EPSILON;
    const nextAtBottom =
      el.scrollTop + el.clientHeight >= el.scrollHeight - EDGE_EPSILON;
    setAtTop(nextAtTop);
    setAtBottom(nextAtBottom);
  }

  function jumpToLatest() {
    if (parentRef.current) parentRef.current.scrollTop = 0;
    setAtTop(true);
  }

  if (entries.length === 0) {
    return (
      <div
        className="bg-bone/40 border border-hair rounded-2xl flex items-center justify-center"
        style={{ height }}
      >
        <p className="font-sans text-sm text-muted">
          No log events yet — they'll stream in as the harvester picks up documents.
        </p>
      </div>
    );
  }

  // Scroll-shadows: only render the edge that has more content beyond view.
  // Implemented as absolutely-positioned overlays inside the relative wrapper
  // (sibling of the scroll container) so they sit on top of content without
  // intercepting wheel/touch events.
  const showTopShadow = !atTop;
  const showBottomShadow = !atBottom;
  // "Paused" indicator: any time the user is not pinned to the newest row.
  const paused = !atTop;

  return (
    <div className="relative">
      <div
        ref={parentRef}
        onScroll={handleScroll}
        aria-live="polite"
        aria-atomic="false"
        aria-relevant="additions"
        aria-label="Harvest log"
        className="bg-bone/40 border border-hair rounded-2xl overflow-y-auto"
        style={{ height }}
      >
        <div
          style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}
        >
          {rowVirtualizer.getVirtualItems().map((vrow) => {
            const e = entries[vrow.index];
            const isError = e.level === "error";
            return (
              <div
                key={e.key}
                className={cn(
                  "absolute top-0 left-0 w-full px-4 flex items-start gap-3",
                  "border-b border-hair/40",
                )}
                style={{
                  height: ROW_HEIGHT,
                  transform: `translateY(${vrow.start}px)`,
                }}
              >
                <span className="font-mono text-[10px] text-muted/70 mt-1.5 tabular-nums w-14 shrink-0">
                  {formatTime(e.ts)}
                </span>
                <SourceDot source={e.source} size="md" className="mt-2 shrink-0" />
                <div className="flex-1 min-w-0 py-2">
                  <p
                    className={cn(
                      "font-serif text-sm truncate",
                      isError ? "text-rose" : "text-ink",
                    )}
                  >
                    {e.title || e.docId || "(no title)"}
                  </p>
                  <p
                    className={cn(
                      "font-sans text-[11px] truncate mt-0.5",
                      isError ? "text-rose" : "text-muted",
                    )}
                  >
                    {e.msg}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Scroll-shadows. Pointer-events-none so they don't swallow scroll. */}
      {showTopShadow && (
        <div
          aria-hidden
          className="pointer-events-none absolute top-0 left-0 right-0 h-8 rounded-t-2xl"
          style={{
            background:
              "linear-gradient(to bottom, rgb(var(--c-bg) / 0.85), rgb(var(--c-bg) / 0))",
          }}
        />
      )}
      {showBottomShadow && (
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-0 left-0 right-0 h-8 rounded-b-2xl"
          style={{
            background:
              "linear-gradient(to top, rgb(var(--c-bg) / 0.85), rgb(var(--c-bg) / 0))",
          }}
        />
      )}

      {/* Auto-scroll paused chip. "Latest" lives at the top of this list
       *  (newest-first), so the chip is anchored top-center and an up-arrow
       *  conveys the jump direction. */}
      {paused && (
        <button
          type="button"
          onClick={jumpToLatest}
          className={cn(
            "absolute top-3 left-1/2 -translate-x-1/2 z-10",
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full",
            "bg-cream border border-hair shadow-sm",
            "font-sans text-[11px] text-ink hover:bg-bone",
            "animate-fade-in",
          )}
        >
          <ArrowUp size={11} strokeWidth={1.5} aria-hidden />
          Auto-scroll paused · Jump to latest
        </button>
      )}
    </div>
  );
}

function formatTime(ms: number): string {
  if (!ms) return "—";
  const d = new Date(ms);
  return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
