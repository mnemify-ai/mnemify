import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { Tooltip } from "../../../ui/Tooltip";
import { cn } from "../../../../lib/cn";
import type { Match } from "./searchIndex";

interface SearchPanelProps {
  query: string;
  /** Bumps every time the user invokes "open search" (e.g. Cmd-F). The panel
   *  re-focuses + selects the input on changes so repeat Cmd-F-while-open
   *  behaves like the browser's own find. */
  openVersion: number;
  matches: Match[];
  activeIndex: number;
  indexing: { done: number; total: number } | null;
  onQueryChange: (q: string) => void;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

const DEBOUNCE_MS = 150;

export function SearchPanel({
  query,
  openVersion,
  matches,
  activeIndex,
  indexing,
  onQueryChange,
  onNext,
  onPrev,
  onClose,
}: SearchPanelProps) {
  const [draft, setDraft] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus + select on mount AND every subsequent openVersion bump (repeat
  // Cmd-F when the panel is already open should behave like browser find).
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [openVersion]);

  // Debounce the upstream dispatch. Re-running the search on every keystroke
  // would re-index match positions and force a text-layer relayout for every
  // page that has matches — visibly janky on big docs.
  useEffect(() => {
    if (draft === query) return;
    const id = window.setTimeout(() => onQueryChange(draft), DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [draft, query, onQueryChange]);

  // Keep draft in sync if parent resets (e.g. on close-and-reopen).
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
      aria-label="Search in document"
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
        placeholder="Find in document"
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
  indexing,
}: {
  query: string;
  matches: Match[];
  activeIndex: number;
  indexing: { done: number; total: number } | null;
}) {
  // Distinct states drive distinct text — kept verbose for legibility.
  let text: string;
  if (!query) {
    text = indexing ? `Indexing ${indexing.done}/${indexing.total}` : "";
  } else if (matches.length === 0) {
    text = indexing ? `Indexing ${indexing.done}/${indexing.total}…` : "No matches";
  } else {
    const cursor = activeIndex >= 0 ? activeIndex + 1 : 1;
    text = indexing
      ? `${cursor} of ${matches.length}+`
      : `${cursor} of ${matches.length}`;
  }
  return (
    <span
      className="font-mono tabular-nums text-[11px] text-muted px-1 min-w-[5ch] text-right"
      aria-live="polite"
    >
      {text}
    </span>
  );
}
