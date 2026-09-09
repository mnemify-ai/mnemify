// Search panel for the spreadsheet viewer. Status text differs from PDF's
// version — when matches span sheets, we surface the active match's sheet
// name + A1 cell address (e.g. "Sheet 2 · B14") so the user knows where
// the highlighter is about to send them.

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { Tooltip } from "../../../ui/Tooltip";
import { cn } from "../../../../lib/cn";
import { columnLabel } from "./HideMenu";
import type { Match } from "./searchIndex";

interface SpreadsheetSearchPanelProps {
  query: string;
  openVersion: number;
  matches: Match[];
  activeIndex: number;
  /** True when the active match's row/col is currently hidden by a filter,
   *  a hide-column action, or a sort that didn't include it. The status text
   *  surfaces this so the user knows pressing Next isn't broken. */
  activeMatchHidden: boolean;
  sheetNames: string[];
  indexing: { done: number; total: number } | null;
  onQueryChange: (q: string) => void;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

const DEBOUNCE_MS = 150;

export function SpreadsheetSearchPanel({
  query,
  openVersion,
  matches,
  activeIndex,
  activeMatchHidden,
  sheetNames,
  indexing,
  onQueryChange,
  onNext,
  onPrev,
  onClose,
}: SpreadsheetSearchPanelProps) {
  const [draft, setDraft] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [openVersion]);

  useEffect(() => {
    if (draft === query) return;
    const id = window.setTimeout(() => onQueryChange(draft), DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [draft, query, onQueryChange]);

  useEffect(() => {
    setDraft(query);
  }, [query]);

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) onPrev();
      else onNext();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  return (
    <div
      role="search"
      aria-label="Search in spreadsheet"
      className={cn(
        "flex items-center gap-1.5 px-2 h-9 rounded-full",
        "bg-bone/60 border border-hair",
      )}
    >
      <Search size={13} strokeWidth={1.75} className="text-muted" aria-hidden />
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Find in sheet"
        aria-label="Search query"
        className={cn(
          "w-44 bg-transparent outline-none",
          "font-sans text-sm text-ink placeholder:text-muted",
        )}
      />
      <Status
        query={query}
        matches={matches}
        activeIndex={activeIndex}
        activeMatchHidden={activeMatchHidden}
        sheetNames={sheetNames}
        indexing={indexing}
      />
      <Tooltip content="Previous match (Shift+Enter)" side="bottom">
        <button
          type="button"
          aria-label="Previous match"
          onClick={onPrev}
          disabled={matches.length === 0}
          className={cn(
            "inline-flex items-center justify-center h-6 w-6 rounded-full",
            "text-muted hover:text-ink hover:bg-bone transition-colors",
            "disabled:opacity-disabled disabled:pointer-events-none",
          )}
        >
          <ChevronUp size={13} strokeWidth={1.75} aria-hidden />
        </button>
      </Tooltip>
      <Tooltip content="Next match (Enter)" side="bottom">
        <button
          type="button"
          aria-label="Next match"
          onClick={onNext}
          disabled={matches.length === 0}
          className={cn(
            "inline-flex items-center justify-center h-6 w-6 rounded-full",
            "text-muted hover:text-ink hover:bg-bone transition-colors",
            "disabled:opacity-disabled disabled:pointer-events-none",
          )}
        >
          <ChevronDown size={13} strokeWidth={1.75} aria-hidden />
        </button>
      </Tooltip>
      <Tooltip content="Close (Esc)" side="bottom">
        <button
          type="button"
          aria-label="Close search"
          onClick={onClose}
          className={cn(
            "inline-flex items-center justify-center h-6 w-6 rounded-full",
            "text-muted hover:text-ink hover:bg-bone transition-colors",
          )}
        >
          <X size={13} strokeWidth={1.75} aria-hidden />
        </button>
      </Tooltip>
    </div>
  );
}

function Status({
  query,
  matches,
  activeIndex,
  activeMatchHidden,
  sheetNames,
  indexing,
}: {
  query: string;
  matches: Match[];
  activeIndex: number;
  activeMatchHidden: boolean;
  sheetNames: string[];
  indexing: { done: number; total: number } | null;
}) {
  let text: string;
  let tone: "muted" | "warn" = "muted";
  if (!query) {
    text = indexing ? `Indexing ${indexing.done}/${indexing.total}` : "";
  } else if (matches.length === 0) {
    text = indexing ? `Indexing…` : "No matches";
  } else {
    const active = matches[activeIndex];
    const cursor = activeIndex >= 0 ? activeIndex + 1 : 1;
    if (activeMatchHidden) {
      text = `${cursor}/${matches.length} · hidden by filter`;
      tone = "warn";
    } else {
      const addr = active
        ? `${sheetNames[active.sheetIndex] ?? `Sheet ${active.sheetIndex + 1}`} · ${columnLabel(active.col)}${active.row}`
        : "";
      text =
        sheetNames.length > 1 && active
          ? `${cursor}/${matches.length} · ${addr}`
          : `${cursor} of ${matches.length}`;
    }
  }

  return (
    <span
      className={
        "font-mono tabular-nums text-[11px] px-1 min-w-[5ch] text-right truncate max-w-[220px] " +
        (tone === "warn" ? "text-magenta" : "text-muted")
      }
      aria-live="polite"
      title={text}
    >
      {text}
    </span>
  );
}
