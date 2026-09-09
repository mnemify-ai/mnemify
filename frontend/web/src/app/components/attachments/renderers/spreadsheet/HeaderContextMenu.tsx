// Context menu shown when the user right-clicks a column header or row
// gutter. Self-contained: orchestrator just stores `{kind, index, x, y}`
// state and renders <HeaderContextMenu /> when set. Radix Popover doesn't
// expose a cursor-anchored variant, so we portal a small panel positioned
// fixed at the click coords and handle outside-click + Esc ourselves.

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { ArrowDownAZ, ArrowUpZA, EyeOff, Filter, X } from "lucide-react";
import { cn } from "../../../../lib/cn";

export type ContextMenuTarget =
  | { kind: "col"; index: number; x: number; y: number }
  | { kind: "row"; index: number; x: number; y: number };

interface HeaderContextMenuProps {
  target: ContextMenuTarget;
  onClose: () => void;
  onHide: () => void;
  /** Sort handlers are only meaningful for columns; pass null for rows. */
  onSortAsc?: () => void;
  onSortDesc?: () => void;
  onClearSort?: () => void;
  isSorted?: "asc" | "desc" | null;
  onOpenFilter?: () => void;
  hasFilter?: boolean;
  onClearFilter?: () => void;
}

export function HeaderContextMenu({
  target,
  onClose,
  onHide,
  onSortAsc,
  onSortDesc,
  onClearSort,
  isSorted,
  onOpenFilter,
  hasFilter,
  onClearFilter,
}: HeaderContextMenuProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!panelRef.current?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  // Nudge off-screen panels back into the viewport.
  const adjusted = adjustToViewport(target.x, target.y);

  return createPortal(
    <div
      ref={panelRef}
      role="menu"
      className={cn(
        "fixed z-50 min-w-[200px]",
        "bg-cream border border-hair rounded-xl shadow-lg p-1.5",
        "font-sans text-sm text-ink animate-fade-in motion-reduce:animate-none",
      )}
      style={{ left: adjusted.x, top: adjusted.y }}
    >
      <Item
        icon={<EyeOff size={13} strokeWidth={1.75} aria-hidden />}
        label={target.kind === "col" ? "Hide column" : "Hide row"}
        onSelect={() => {
          onHide();
          onClose();
        }}
      />
      {target.kind === "col" && (
        <>
          <Divider />
          <Item
            icon={<ArrowDownAZ size={13} strokeWidth={1.75} aria-hidden />}
            label="Sort ascending"
            active={isSorted === "asc"}
            onSelect={() => {
              onSortAsc?.();
              onClose();
            }}
          />
          <Item
            icon={<ArrowUpZA size={13} strokeWidth={1.75} aria-hidden />}
            label="Sort descending"
            active={isSorted === "desc"}
            onSelect={() => {
              onSortDesc?.();
              onClose();
            }}
          />
          {isSorted && (
            <Item
              icon={<X size={13} strokeWidth={1.75} aria-hidden />}
              label="Clear sort"
              onSelect={() => {
                onClearSort?.();
                onClose();
              }}
            />
          )}
          <Divider />
          <Item
            icon={<Filter size={13} strokeWidth={1.75} aria-hidden />}
            label={hasFilter ? "Edit filter…" : "Filter…"}
            onSelect={() => {
              onOpenFilter?.();
              onClose();
            }}
          />
          {hasFilter && (
            <Item
              icon={<X size={13} strokeWidth={1.75} aria-hidden />}
              label="Clear filter"
              onSelect={() => {
                onClearFilter?.();
                onClose();
              }}
            />
          )}
        </>
      )}
    </div>,
    document.body,
  );
}

function Item({
  icon,
  label,
  active,
  onSelect,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md",
        "text-left text-sm text-ink hover:bg-bone/70 transition-colors",
        active && "text-magenta",
      )}
    >
      <span className="text-muted w-4 inline-flex justify-center">{icon}</span>
      {label}
    </button>
  );
}

function Divider() {
  return <div className="my-1 border-t border-hair" aria-hidden />;
}

const MENU_W = 220;
const MENU_H_EST = 280;

function adjustToViewport(x: number, y: number): { x: number; y: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const ax = Math.min(x, vw - MENU_W - 8);
  const ay = Math.min(y, vh - MENU_H_EST - 8);
  return { x: Math.max(8, ax), y: Math.max(8, ay) };
}
