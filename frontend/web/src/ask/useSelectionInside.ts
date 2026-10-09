import { useEffect, useState, type RefObject } from "react";
import { messageIdFor, normalizeSelection } from "./selection";

export type InsideSelection = {
  text: string;
  messageId: string;
  /** Position for the floating chip, relative to the scroll container. */
  top: number;
  left: number;
};

/**
 * Tracks a text selection made inside an assistant message within
 * `containerRef`. Resolves to the message's `data-message-id` and the
 * selection's end rect (container-relative) so a "Save selection" chip can
 * float next to it. Clears on scroll, on a click elsewhere, and when the
 * selection collapses.
 */
export function useSelectionInside(containerRef: RefObject<HTMLElement | null>): InsideSelection | null {
  const [sel, setSel] = useState<InsideSelection | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof document === "undefined") return;

    const read = () => {
      const s = document.getSelection();
      if (!s || s.rangeCount === 0 || s.isCollapsed) {
        setSel(null);
        return;
      }
      const text = normalizeSelection(s.toString());
      if (!text) {
        setSel(null);
        return;
      }
      const range = s.getRangeAt(0);
      const anchor = range.commonAncestorContainer;
      const el = anchor.nodeType === Node.ELEMENT_NODE ? (anchor as HTMLElement) : anchor.parentElement;
      const messageId = messageIdFor(
        el as unknown as { parentNode: unknown | null; dataset?: Record<string, string | undefined> },
        (n) => container.contains(n as Node),
      );
      if (!messageId) {
        setSel(null);
        return;
      }
      const rects = range.getClientRects();
      const last = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
      const box = container.getBoundingClientRect();
      setSel({
        text,
        messageId,
        top: last.bottom - box.top + container.scrollTop + 6,
        left: Math.max(8, Math.min(last.left - box.left, box.width - 200)),
      });
    };

    const onUp = () => window.setTimeout(read, 0);
    const clear = () => setSel(null);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("keyup", onUp);
    document.addEventListener("selectionchange", read);
    container.addEventListener("scroll", clear);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("keyup", onUp);
      document.removeEventListener("selectionchange", read);
      container.removeEventListener("scroll", clear);
    };
  }, [containerRef]);

  return sel;
}
