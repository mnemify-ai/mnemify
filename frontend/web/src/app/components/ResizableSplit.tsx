import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";

interface ResizableSplitProps {
  left: ReactNode;
  right: ReactNode;
  /** Initial fraction (0–1) given to the LEFT pane. */
  initialLeftFraction?: number;
  /** Minimum width (px) of each pane. */
  minLeft?: number;
  minRight?: number;
  /** localStorage key — when set, the chosen fraction persists. */
  storageKey?: string;
  className?: string;
}

/** Width of the divider band in px — `w-1.5` on the separator below. The
 *  clamp has to know it: the right pane is `flex-1`, so it gets whatever the
 *  left pane and the band leave behind, and a fraction that ignores the band
 *  starves the right pane by exactly this much. */
export const SPLIT_DIVIDER_PX = 6;

/**
 * Project a split fraction onto the range this container can actually honour.
 *
 * The single source of truth for all three inputs — drag, keyboard, render —
 * so the divider can never land somewhere one of them would refuse to put it.
 * Before the container has been measured (width 0 on the very first render)
 * the fraction passes through untouched.
 */
export function clampSplitFraction(
  fraction: number,
  containerWidth: number,
  minLeft: number,
  minRight: number,
  dividerWidth: number = SPLIT_DIVIDER_PX,
): number {
  if (!Number.isFinite(containerWidth) || containerWidth <= 0) return fraction;
  const minF = minLeft / containerWidth;
  const maxF = 1 - (minRight + dividerWidth) / containerWidth;
  if (minF > maxF) {
    // No fraction satisfies both minimums — i.e. minLeft + divider + minRight
    // exceeds the container. Honouring one minimum here would collapse the
    // other pane to a sliver, so instead hand each pane the same share of what
    // exists that its minimum asks for: both fall short by the same ratio, and
    // the layout degrades symmetrically instead of losing a pane.
    const total = minLeft + minRight;
    const share = total > 0 ? minLeft / total : 0.5;
    return (Math.max(0, containerWidth - dividerWidth) / containerWidth) * share;
  }
  return Math.min(Math.max(fraction, minF), maxF);
}

/**
 * Horizontal two-pane split with a draggable divider. Both panes stay
 * independently interactive (unlike a modal overlay). The divider is a thin
 * vertical band; hover/active states make it visible.
 */
export function ResizableSplit({
  left,
  right,
  initialLeftFraction = 0.4,
  minLeft = 280,
  minRight = 360,
  storageKey,
  className,
}: ResizableSplitProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // The *stored* fraction is the user's intent, kept verbatim even when this
  // container is currently too narrow to honour it — widen the window (or
  // close the Ask dock) and the split they chose comes back. Everything the
  // layout uses goes through `clampSplitFraction` first; that projection is
  // never written back.
  const [fraction, setFraction] = useState<number>(() => {
    if (storageKey && typeof window !== "undefined") {
      const raw = window.localStorage.getItem(storageKey);
      const parsed = raw ? parseFloat(raw) : NaN;
      if (Number.isFinite(parsed) && parsed > 0.1 && parsed < 0.9) return parsed;
    }
    return initialLeftFraction;
  });
  const [dragging, setDragging] = useState(false);
  const [containerWidth, setContainerWidth] = useState(0);

  // Measured before paint, so the first frame is already clamped rather than
  // flashing a starved pane. An observer rather than a window listener: the
  // Ask dock opening beside us narrows this container without the window ever
  // changing size.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setContainerWidth(el.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Drag and keyboard commit the clamped value as the new intent — an explicit
  // adjustment made at this size *is* what the user meant here. Only the
  // render path leaves the stored fraction alone.
  const clampAt = useCallback(
    (f: number, width: number) => clampSplitFraction(f, width, minLeft, minRight),
    [minLeft, minRight],
  );

  // Persist on change.
  useEffect(() => {
    if (storageKey && typeof window !== "undefined") {
      window.localStorage.setItem(storageKey, fraction.toFixed(3));
    }
  }, [fraction, storageKey]);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    setDragging(true);
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = e.clientX - rect.left;
      const width = rect.width;
      setFraction(clampAt(x / width, width));
    },
    [dragging, clampAt],
  );

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    setDragging(false);
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }, []);

  const displayFraction = clampAt(fraction, containerWidth);

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative flex w-full h-full min-h-0",
        dragging && "select-none cursor-col-resize",
        className,
      )}
    >
      <div
        className="min-w-0 min-h-0 overflow-hidden"
        style={{ flex: `0 0 ${displayFraction * 100}%` }}
      >
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panes"
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={(e) => {
          // Stepped off the fraction on screen, not the stored one, so an arrow
          // always moves the divider you can see.
          if (e.key === "ArrowLeft")
            setFraction(clampAt(displayFraction - 0.02, containerWidth));
          if (e.key === "ArrowRight")
            setFraction(clampAt(displayFraction + 0.02, containerWidth));
        }}
        className={cn(
          "relative shrink-0 w-1.5 cursor-col-resize group",
          "before:absolute before:inset-y-0 before:left-1/2 before:-translate-x-1/2 before:w-px before:bg-hair",
          "after:absolute after:inset-y-0 after:left-1/2 after:-translate-x-1/2 after:w-1 after:bg-transparent",
          "hover:after:bg-magenta/30 focus-visible:after:bg-magenta/40 focus:outline-none",
          dragging && "after:bg-magenta/50",
          "transition-colors",
        )}
      />
      <div className="flex-1 min-w-0 min-h-0 overflow-hidden">{right}</div>
    </div>
  );
}
