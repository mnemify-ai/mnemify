import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  PanelLeftClose,
  PanelLeftOpen,
  Printer,
  RotateCw,
  Search,
} from "lucide-react";
import { Tooltip } from "../../../ui/Tooltip";
import { Kbd } from "../../../ui/Kbd";
import { cn } from "../../../../lib/cn";
import { ZoomMenu } from "./ZoomMenu";
import { SearchPanel } from "./SearchPanel";
import type { Match } from "./searchIndex";
import type { ZoomMode } from "./state";

interface PdfToolbarProps {
  numPages: number | null;
  currentPage: number;
  sidebarOpen: boolean;
  zoom: number;
  zoomMode: ZoomMode;
  searchOpen: boolean;
  searchOpenVersion: number;
  searchQuery: string;
  matches: Match[];
  activeMatchIndex: number;
  indexing: { done: number; total: number } | null;
  onToggleSidebar: () => void;
  onGoto: (page: number) => void;
  onRotateCurrentPage: () => void;
  onZoomChange: (value: number) => void;
  onZoomModeChange: (mode: ZoomMode) => void;
  onOpenSearch: () => void;
  onCloseSearch: () => void;
  onSearchQueryChange: (q: string) => void;
  onNextMatch: () => void;
  onPrevMatch: () => void;
  onOpenPrint: () => void;
}

export function PdfToolbar(props: PdfToolbarProps) {
  return (
    <div
      role="toolbar"
      aria-label="PDF tools"
      className={cn(
        "flex items-center gap-1.5 px-3 py-2",
        "border-b border-hair bg-cream/70 backdrop-blur-sm shrink-0",
      )}
    >
      <Tooltip
        content={
          <span className="inline-flex items-center gap-1.5">
            Page thumbnails
          </span>
        }
        side="bottom"
      >
        <IconButton
          aria-label="Toggle thumbnails"
          aria-pressed={props.sidebarOpen}
          onClick={props.onToggleSidebar}
        >
          {props.sidebarOpen ? (
            <PanelLeftClose size={15} strokeWidth={1.5} aria-hidden />
          ) : (
            <PanelLeftOpen size={15} strokeWidth={1.5} aria-hidden />
          )}
        </IconButton>
      </Tooltip>

      <Divider />

      <PageJumpInput
        currentPage={props.currentPage}
        numPages={props.numPages}
        onGoto={props.onGoto}
      />

      <div className="flex-1" />

      <ZoomMenu
        zoom={props.zoom}
        zoomMode={props.zoomMode}
        onZoomChange={props.onZoomChange}
        onZoomModeChange={props.onZoomModeChange}
      />

      <Tooltip content="Rotate current page" side="bottom">
        <IconButton
          aria-label="Rotate current page"
          onClick={props.onRotateCurrentPage}
        >
          <RotateCw size={15} strokeWidth={1.5} aria-hidden />
        </IconButton>
      </Tooltip>

      <Divider />

      {props.searchOpen ? (
        <SearchPanel
          query={props.searchQuery}
          openVersion={props.searchOpenVersion}
          matches={props.matches}
          activeIndex={props.activeMatchIndex}
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
          <IconButton aria-label="Find in document" onClick={props.onOpenSearch}>
            <Search size={15} strokeWidth={1.5} aria-hidden />
          </IconButton>
        </Tooltip>
      )}

      <Tooltip content="Print" side="bottom">
        <IconButton aria-label="Print" onClick={props.onOpenPrint}>
          <Printer size={15} strokeWidth={1.5} aria-hidden />
        </IconButton>
      </Tooltip>
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
        "aria-pressed:bg-bone aria-pressed:text-ink",
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

function PageJumpInput({
  currentPage,
  numPages,
  onGoto,
}: {
  currentPage: number;
  numPages: number | null;
  onGoto: (page: number) => void;
}) {
  const [draft, setDraft] = useState(String(currentPage));

  // Keep the input in sync as the user scrolls the main view.
  useEffect(() => {
    setDraft(String(currentPage));
  }, [currentPage]);

  function commit(value: string) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed) || !numPages) {
      setDraft(String(currentPage));
      return;
    }
    const clamped = Math.max(1, Math.min(numPages, parsed));
    onGoto(clamped);
    setDraft(String(clamped));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    commit(draft);
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setDraft(String(currentPage));
      (e.target as HTMLInputElement).blur();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="inline-flex items-center gap-1.5 font-mono tabular-nums text-[12px] text-ink"
      aria-label="Go to page"
    >
      <input
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={() => commit(draft)}
        onKeyDown={handleKey}
        onFocus={(e) => e.target.select()}
        aria-label="Current page"
        className={cn(
          "h-8 px-2 w-[5ch] text-center",
          "bg-bg border border-hair rounded-md",
          "focus:outline-none focus:border-magenta focus:ring-2 focus:ring-magenta/30",
        )}
      />
      <span className="text-muted">/</span>
      <span className="min-w-[3ch] text-muted">{numPages ?? "—"}</span>
    </form>
  );
}
