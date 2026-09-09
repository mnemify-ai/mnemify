// Top toolbar for the spreadsheet renderer. Mirrors the PDF toolbar's
// visual language (36×36 ghost icon buttons inside a cream/hair-bordered
// strip) so users get one consistent chrome across attachment types.

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { RotateCcw, Search } from "lucide-react";
import { Tooltip } from "../../../ui/Tooltip";
import { Kbd } from "../../../ui/Kbd";
import { cn } from "../../../../lib/cn";
import { HideMenu } from "./HideMenu";
import { SpreadsheetSearchPanel } from "./SpreadsheetSearchPanel";
import type { Match } from "./searchIndex";

interface SpreadsheetToolbarProps {
  searchOpen: boolean;
  searchOpenVersion: number;
  searchQuery: string;
  matches: Match[];
  activeMatchIndex: number;
  activeMatchHidden: boolean;
  sheetNames: string[];
  indexing: { done: number; total: number } | null;
  hiddenCols: number[];
  hiddenRows: number[];
  zoom: number;
  hasOverrides: boolean;
  onOpenSearch: () => void;
  onCloseSearch: () => void;
  onSearchQueryChange: (q: string) => void;
  onNextMatch: () => void;
  onPrevMatch: () => void;
  onShowCol: (col: number) => void;
  onShowRow: (row: number) => void;
  onShowAll: () => void;
  onZoomChange: (z: number) => void;
  onResetOverrides: () => void;
}

export function SpreadsheetToolbar(props: SpreadsheetToolbarProps) {
  return (
    <div
      role="toolbar"
      aria-label="Spreadsheet tools"
      className={cn(
        "flex items-center gap-1.5 px-3 py-2 shrink-0",
        "border-b border-hair bg-cream/70 backdrop-blur-sm",
      )}
    >
      <HideMenu
        hiddenCols={props.hiddenCols}
        hiddenRows={props.hiddenRows}
        onShowCol={props.onShowCol}
        onShowRow={props.onShowRow}
        onShowAll={props.onShowAll}
      />

      <Divider />

      <ZoomInput zoom={props.zoom} onZoomChange={props.onZoomChange} />

      <Tooltip content="Reset column widths + hidden + sort + filter" side="bottom">
        <IconButton
          aria-label="Reset overrides"
          onClick={props.onResetOverrides}
          disabled={!props.hasOverrides}
        >
          <RotateCcw size={15} strokeWidth={1.5} aria-hidden />
        </IconButton>
      </Tooltip>

      <div className="flex-1" />

      {props.searchOpen ? (
        <SpreadsheetSearchPanel
          query={props.searchQuery}
          openVersion={props.searchOpenVersion}
          matches={props.matches}
          activeIndex={props.activeMatchIndex}
          activeMatchHidden={props.activeMatchHidden}
          sheetNames={props.sheetNames}
          indexing={props.indexing}
          onQueryChange={props.onSearchQueryChange}
          onNext={props.onNextMatch}
          onPrev={props.onPrevMatch}
          onClose={props.onCloseSearch}
        />
      ) : (
        <Tooltip
          content={
            <span className="inline-flex items-center gap-1.5">
              Find <Kbd>⌘F</Kbd>
            </span>
          }
          side="bottom"
        >
          <IconButton aria-label="Find in sheet" onClick={props.onOpenSearch}>
            <Search size={15} strokeWidth={1.5} aria-hidden />
          </IconButton>
        </Tooltip>
      )}
    </div>
  );
}

function IconButton({
  children,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center justify-center h-9 w-9 rounded-full",
        "text-muted hover:text-ink hover:bg-bone/60 transition-colors",
        "disabled:opacity-disabled disabled:pointer-events-none",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <span className="h-5 w-px bg-hair" aria-hidden />;
}

const MIN_ZOOM_PCT = 25;
const MAX_ZOOM_PCT = 400;

function ZoomInput({
  zoom,
  onZoomChange,
}: {
  zoom: number;
  onZoomChange: (z: number) => void;
}) {
  const pct = Math.round(zoom * 100);
  const [draft, setDraft] = useState(String(pct));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setDraft(String(pct));
    }
  }, [pct]);

  function commit() {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(pct));
      return;
    }
    const clamped = Math.max(MIN_ZOOM_PCT, Math.min(MAX_ZOOM_PCT, parsed));
    onZoomChange(clamped / 100);
    setDraft(String(clamped));
  }

  function step(delta: number) {
    onZoomChange(
      Math.max(MIN_ZOOM_PCT / 100, Math.min(MAX_ZOOM_PCT / 100, zoom + delta)),
    );
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    inputRef.current?.blur();
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setDraft(String(pct));
      inputRef.current?.blur();
    }
  }

  return (
    <Tooltip content="Zoom" side="bottom">
      <form
        onSubmit={handleSubmit}
        className={cn(
          "inline-flex items-center h-9 rounded-full px-1.5",
          "hover:bg-bone/60 focus-within:bg-bone/60 transition-colors",
        )}
      >
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => step(-0.1)}
          className="inline-flex items-center justify-center h-6 w-6 rounded-full text-muted hover:text-ink hover:bg-bone transition-colors"
        >
          −
        </button>
        <input
          ref={inputRef}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={draft}
          onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
          onFocus={(e) => e.target.select()}
          onBlur={commit}
          onKeyDown={handleKey}
          aria-label="Zoom percent"
          className={cn(
            "w-[3.5ch] mx-0.5 bg-transparent border-0 outline-none",
            "font-mono tabular-nums text-[12px] text-ink text-center",
          )}
        />
        <span
          className="font-mono tabular-nums text-[12px] text-muted select-none mr-0.5"
          aria-hidden
        >
          %
        </span>
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => step(0.1)}
          className="inline-flex items-center justify-center h-6 w-6 rounded-full text-muted hover:text-ink hover:bg-bone transition-colors"
        >
          +
        </button>
      </form>
    </Tooltip>
  );
}
