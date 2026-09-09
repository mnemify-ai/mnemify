import { useEffect, useRef } from "react";
import { Page } from "react-pdf";
import { useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "../../../../lib/cn";
import type { Rotation } from "./state";

interface ThumbnailSidebarProps {
  numPages: number;
  currentPage: number;
  rotations: Record<number, Rotation>;
  /** First page's intrinsic /Rotate. react-pdf's `rotate` prop is absolute and
   *  overrides intrinsic rotation, so we must re-apply it (+ any user rotation)
   *  here too — otherwise rotated PDFs render sideways in the sidebar. */
  naturalRotation: Rotation;
  onSelect: (pageNumber: number) => void;
}

// Visual dimensions. Width = thumbnail page render width; row height is the
// rendered page height plus a label strip and gap. We let pages render at a
// fixed width and rely on the virtualizer to remeasure if a thumbnail's
// natural aspect differs (rotated pages will swap dimensions).
const THUMB_WIDTH = 140;
const ESTIMATED_ROW_HEIGHT = 200;
const SIDEBAR_WIDTH = 180;

export function ThumbnailSidebar({
  numPages,
  currentPage,
  rotations,
  naturalRotation,
  onSelect,
}: ThumbnailSidebarProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: numPages,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 3,
  });

  // Keep the current page visible in the sidebar as the main view scrolls.
  useEffect(() => {
    virtualizer.scrollToIndex(currentPage - 1, { align: "center" });
    // We intentionally don't include `virtualizer` in deps — its identity is
    // stable across renders, and listing it confuses ESLint about whether
    // the effect cares about it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage]);

  return (
    <aside
      ref={scrollRef}
      role="navigation"
      aria-label="Page thumbnails"
      className={cn(
        "overflow-y-auto overflow-x-hidden",
        "bg-bone/40 border-r border-hair",
      )}
      style={{ width: SIDEBAR_WIDTH }}
    >
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: "100%",
          position: "relative",
        }}
      >
        {virtualizer.getVirtualItems().map((v) => {
          const pageNumber = v.index + 1;
          const isCurrent = pageNumber === currentPage;
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
              }}
              className="px-4 pt-3"
            >
              <button
                type="button"
                onClick={() => onSelect(pageNumber)}
                aria-label={`Go to page ${pageNumber}`}
                aria-current={isCurrent ? "page" : undefined}
                data-current={isCurrent || undefined}
                className={cn(
                  "pdf-thumb block w-full overflow-hidden rounded-md",
                  "transition-shadow",
                )}
              >
                <Page
                  pageNumber={pageNumber}
                  width={THUMB_WIDTH}
                  rotate={
                    ((naturalRotation + (rotations[pageNumber] ?? 0)) %
                      360) as Rotation
                  }
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  loading={<ThumbSkeleton />}
                />
              </button>
              <p
                className={cn(
                  "mt-1 text-center font-mono text-[10px] tabular-nums",
                  isCurrent ? "text-magenta" : "text-muted",
                )}
              >
                {pageNumber}
              </p>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function ThumbSkeleton() {
  return (
    <div
      className="pdf-page-skeleton rounded-md animate-skeleton-pulse motion-reduce:animate-none"
      style={{ width: THUMB_WIDTH, height: THUMB_WIDTH * 1.3 }}
      aria-hidden
    />
  );
}
