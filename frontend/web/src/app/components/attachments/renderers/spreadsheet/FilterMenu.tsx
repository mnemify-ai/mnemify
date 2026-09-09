// Filter Popover for a single column. Triggered from the HeaderContextMenu
// or from the small Funnel icon in the column header. Lists the unique
// values in the column (capped at 1000 to keep render light), each with a
// checkbox; user can search the list. Apply / Clear actions at the bottom.
//
// Mount location matters: this renders inline within SpreadsheetRenderer
// (no portal to document.body). Portaling outside the Radix Dialog's content
// tree makes Radix treat every click on this menu as an "outside" click and
// closes the modal. Fixed positioning still lands the menu where the trigger
// asked — we get the coordinates from the trigger's getBoundingClientRect.

import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { cn } from "../../../../lib/cn";
import { columnLabel } from "./HideMenu";

const VALUE_CAP = 1000;

interface FilterMenuProps {
  col: number;
  x: number;
  y: number;
  /** All values from that column in the unsorted source order. */
  allValues: string[];
  /** Currently-checked values (subset of unique values). Empty array means
   *  no filter is active for the column. */
  selected: string[];
  onApply: (values: string[]) => void;
  onClear: () => void;
  onClose: () => void;
}

export function FilterMenu({
  col,
  x,
  y,
  allValues,
  selected,
  onApply,
  onClear,
  onClose,
}: FilterMenuProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState("");

  // Unique sorted values (capped). Memoized so re-keystrokes don't recompute
  // on every keypress.
  const allUnique = useMemo(() => {
    const set = new Set(allValues);
    const arr = Array.from(set).sort((a, b) => a.localeCompare(b));
    return arr;
  }, [allValues]);

  const visibleUnique = useMemo(() => {
    const q = filter.toLowerCase();
    const filtered = q
      ? allUnique.filter((v) => v.toLowerCase().includes(q))
      : allUnique;
    return filtered.slice(0, VALUE_CAP);
  }, [allUnique, filter]);

  // Local draft of checked set; commit on Apply.
  const initialSet = useMemo(
    () =>
      selected.length === 0
        ? new Set(allUnique) // no filter ⇒ all checked
        : new Set(selected),
    [selected, allUnique],
  );
  const [draft, setDraft] = useState<Set<string>>(initialSet);

  // Outside-click + Esc close.
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

  function toggle(value: string) {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  function selectAll() {
    setDraft(new Set(visibleUnique));
  }

  function selectNone() {
    setDraft(new Set());
  }

  function apply() {
    // Empty filter array means "no filter" (everything visible); convention
    // matches the reducer's clearFilter when nothing's excluded.
    if (draft.size === allUnique.length) onClear();
    else onApply(Array.from(draft));
    onClose();
  }

  const adjusted = adjustToViewport(x, y);
  const truncated = allUnique.length > VALUE_CAP;

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label={`Filter column ${columnLabel(col)}`}
      className={cn(
        "fixed z-[60] w-[280px] max-h-[80vh]",
        "bg-cream border border-hair rounded-xl shadow-lg",
        "font-sans text-sm text-ink animate-fade-in motion-reduce:animate-none",
        "flex flex-col",
      )}
      style={{ left: adjusted.x, top: adjusted.y }}
    >
      <div className="px-3 pt-3 pb-2 border-b border-hair">
        <p className="eyebrow mb-1">Filter</p>
        <h3 className="font-serif text-base text-ink leading-tight">
          Column {columnLabel(col)}
        </h3>
      </div>
      <div className="px-3 py-2 border-b border-hair">
        <label
          className="flex items-center gap-2 h-8 px-2 rounded-full bg-bone/50 border border-hair focus-within:border-magenta"
        >
          <Search
            size={12}
            strokeWidth={1.75}
            className="text-muted"
            aria-hidden
          />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search values"
            aria-label="Search values"
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted"
          />
        </label>
      </div>
      <div className="px-3 py-1.5 flex items-center justify-between border-b border-hair">
        <button
          type="button"
          onClick={selectAll}
          className="font-sans text-[11px] text-magenta hover:underline"
        >
          Select all
        </button>
        <button
          type="button"
          onClick={selectNone}
          className="font-sans text-[11px] text-muted hover:text-ink"
        >
          Select none
        </button>
      </div>
      <ul className="flex-1 min-h-0 max-h-[280px] overflow-y-auto px-1 py-1">
        {visibleUnique.length === 0 && (
          <li className="px-3 py-4 text-center text-sm text-muted">
            No values match.
          </li>
        )}
        {visibleUnique.map((value) => (
          <li key={value}>
            <label
              className={cn(
                "flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer",
                "hover:bg-bone/70 transition-colors",
              )}
            >
              <input
                type="checkbox"
                checked={draft.has(value)}
                onChange={() => toggle(value)}
                className="accent-magenta"
              />
              <span className="font-mono text-[12px] truncate" title={value}>
                {value || <span className="text-muted">(empty)</span>}
              </span>
            </label>
          </li>
        ))}
        {truncated && (
          <li className="px-3 py-2 text-center font-mono text-[11px] text-muted">
            +{allUnique.length - VALUE_CAP} more (refine via search)
          </li>
        )}
      </ul>
      <div className="px-3 py-2 border-t border-hair flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => {
            onClear();
            onClose();
          }}
          className="font-sans text-[12px] text-muted hover:text-ink px-2 py-1"
        >
          Clear filter
        </button>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onClose}
            className="font-sans text-[12px] text-muted hover:text-ink px-3 py-1.5 rounded-full"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={apply}
            className={cn(
              "font-sans text-[12px] text-cream bg-magenta px-3 py-1.5 rounded-full",
              "hover:bg-magenta/90 transition-colors",
            )}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}

const MENU_W = 280;
const MENU_H_EST = 420;

function adjustToViewport(x: number, y: number): { x: number; y: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const ax = Math.min(x, vw - MENU_W - 8);
  const ay = Math.min(y, vh - MENU_H_EST - 8);
  return { x: Math.max(8, ax), y: Math.max(8, ay) };
}
