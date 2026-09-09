// The Ask dock — chat as a first-class, app-wide surface. Mounted once in
// DashboardLayout as a structural right column (never an overlay), so the
// conversation survives navigation by construction. Three states persisted
// across sessions: closed (TopBar pill only) / docked (freely resizable, from
// 380px up to nearly the full window) / maximized (fills the shell row).
// The old OracleOrb's cartographer art language (compass glyph, contour
// backdrop) lives on in the header and empty backdrop here.

import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  History,
  Maximize2,
  Minimize2,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { AskPanel } from "./AskPanel";
import { SourceInspector, type SourceInspectorTarget } from "./SourceInspector";
import { useAskSession } from "./useAskSession";
import { useAskThreadStore } from "./askThreadStore";
import {
  DOCK_MIN_WIDTH,
  dockDragMaxWidth,
  useAskDockStore,
} from "./askDockStore";
import type { TerrainFocusTarget } from "./citationDisplay";
import { useMapFocusStore } from "../app/lib/mapFocusStore";
import { useTagParam } from "../app/lib/useTagParam";
import { relativeTime } from "../app/lib/relativeTime";
import { toastInfo } from "../app/lib/toast";
import { Popover } from "../app/components/ui/Popover";
import { Tooltip } from "../app/components/ui/Tooltip";
import { cn } from "../app/lib/cn";

export function AskDock() {
  const { open, wide, width, overlays, closeDock, toggleWide, setWidth } =
    useAskDockStore();
  const session = useAskSession();
  const navigate = useNavigate();
  const location = useLocation();
  const onHome = location.pathname === "/";
  const [, setTagParam] = useTagParam();
  const setFocusRegion = useMapFocusStore((s) => s.setFocusRegion);
  const [inspector, setInspector] = useState<SourceInspectorTarget | null>(null);
  const asideRef = useRef<HTMLElement>(null);

  // ⌘J / Ctrl+J toggles the dock from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        useAskDockStore.getState().toggleDock();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The dock survives navigation, and so did the drawer it owns — which meant
  // walking from any route onto /documents with an inspector open produced two
  // document surfaces at once, the second one narrower than the first. That
  // page renders the source in its own pane (see `viewSource`), so hand over.
  useEffect(() => {
    if (location.pathname.startsWith("/documents")) setInspector(null);
  }, [location.pathname]);

  // Per-route citation actions:
  // "Show on terrain" — live on the map; navigate there from anywhere else.
  const focusTerrain = (target: TerrainFocusTarget) => {
    if (target.kind === "tag") {
      if (onHome) {
        setTagParam(target.id);
      } else {
        navigate(`/?tag=${encodeURIComponent(target.id)}`);
        toastInfo("Showing on the map.");
      }
    } else {
      setFocusRegion(target.id);
      if (!onHome) {
        navigate("/");
        toastInfo("Showing on the map.");
      }
    }
  };

  // "View source" — on Documents, open the doc in the page's own viewer (that
  // page's document pane *is* the source view, so a drawer on top of it would
  // be a second, smaller copy of the same thing); everywhere else, the
  // evidence drawer. Either way the document lands to the left of this dock,
  // never over it.
  const viewSource = (target: SourceInspectorTarget) => {
    if (location.pathname.startsWith("/documents") && target.docId) {
      // A maximized dock drops the route column out of the shell row, so the
      // viewer we're navigating to would render into nothing. Restore the
      // docked width first — the drawer branch does the same via SideDrawer's
      // `avoidAskDock`.
      useAskDockStore.getState().unmaximizeDock();
      const params = new URLSearchParams(location.search);
      params.set("id", target.docId);
      navigate(`${location.pathname}?${params.toString()}`);
    } else {
      setInspector(target);
    }
  };

  // Drag the left edge to resize (docked mode). Mutates width during the
  // drag, commits to the store on release — same pattern as KnowledgeMap's aside.
  // The upper bound is the viewport, not a fixed constant: the dock can be
  // pulled almost all the way left, leaving just a sliver of the app behind.
  const startResize = (e: React.PointerEvent) => {
    if (wide) return;
    e.preventDefault();
    const onMove = (ev: PointerEvent) => {
      const w = Math.max(
        DOCK_MIN_WIDTH,
        Math.min(dockDragMaxWidth(window.innerWidth), window.innerWidth - ev.clientX),
      );
      if (asideRef.current) asideRef.current.style.width = `${w}px`;
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (asideRef.current) {
        setWidth(asideRef.current.getBoundingClientRect().width);
      }
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  if (!open) return null;

  return (
    <>
      <aside
        ref={asideRef}
        className={cn(
          "z-30 hidden flex-col bg-cream md:flex",
          // On Home the shell row is a fixed-height flex row (the map's bottom
          // bar spans the window below it), so the dock stretches to the row.
          // Everywhere else the page scrolls and the dock sticks to the top.
          onHome
            ? "relative h-full min-h-0 border-l border-line/[0.18]"
            : "sticky top-0 h-dvh border-l border-hair",
          // Maximized: take the whole row. The shell drops the sibling Outlet
          // column out of layout while this is on (two `flex-1` siblings would
          // just split the row 50/50), so growing is all that's left to do.
          wide ? "min-w-0 flex-1" : "shrink-0",
        )}
        style={
          wide
            ? undefined
            : // The stored width is clamped only to a generous static ceiling,
              // so re-clamp it to *this* viewport here — same formula as the
              // drag, in CSS so it follows window resizes for free.
              { width, maxWidth: "min(92vw, calc(100vw - 420px))" }
        }
        aria-label="Ask Mnemify"
      >
        <div
          onPointerDown={startResize}
          title="Drag to resize"
          className={cn(
            "absolute inset-y-0 left-0 z-10 w-1.5",
            wide ? "" : "cursor-col-resize hover:bg-magenta/30",
          )}
          aria-hidden
        />
        {/* Controls row sits under the fixed 64px TopBar. */}
        <div className="mt-16 flex shrink-0 items-center justify-between border-b border-hair px-3 py-2">
          <div className="flex items-center gap-1.5">
            <AskGlyph />
            <ThreadSwitcher />
          </div>
          <div className="flex items-center gap-1">
            <NewThreadButton />
            <button
              type="button"
              onClick={toggleWide}
              // Maximizing takes the whole shell row, which would put the
              // conversation back on top of whatever document surface asked
              // to sit beside it. Held shut while any of them is open.
              disabled={!wide && overlays > 0}
              aria-label={wide ? "Restore Ask panel" : "Maximize Ask panel"}
              className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-lavender/60 hover:text-ink disabled:pointer-events-none disabled:opacity-disabled"
            >
              {wide ? (
                <Minimize2 size={14} strokeWidth={1.75} />
              ) : (
                <Maximize2 size={14} strokeWidth={1.75} />
              )}
            </button>
            <button
              type="button"
              onClick={closeDock}
              aria-label="Close Ask"
              aria-keyshortcuts="Meta+J Control+J"
              className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-lavender/60 hover:text-ink"
            >
              <X size={15} strokeWidth={1.75} />
            </button>
          </div>
        </div>
        <div className="relative min-h-0 flex-1">
          <AskBackdrop />
          <div className="relative z-[1] h-full">
            <AskPanel
              session={session}
              onFocusTerrain={focusTerrain}
              onViewSource={viewSource}
            />
          </div>
        </div>
      </aside>
      {/* Citation evidence drawer — right side like every other drawer in the
          app, but inset by this dock's width (`avoidAskDock`) so the source
          lands beside the answer that cited it rather than on top of it. */}
      <SourceInspector
        target={inspector}
        onClose={() => setInspector(null)}
        onShowOnTerrain={focusTerrain}
      />
    </>
  );
}

/** Toggle helper for surfaces that can't import the store hook (rare). */
export function toggleAskDock() {
  useAskDockStore.getState().toggleDock();
}

/**
 * Start a fresh conversation. Promoted out of the thread popover and into the
 * header: it was the first row of a menu behind a glyph, which meant the two
 * things people look for first in a chat (start over, go back) were both
 * invisible until you found the glyph.
 */
function NewThreadButton() {
  const newThread = useAskThreadStore((s) => s.newThread);
  return (
    <Tooltip content="New chat" side="bottom">
      <button
        type="button"
        onClick={newThread}
        aria-label="New chat"
        className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-lavender/60 hover:text-ink"
      >
        <Plus size={15} strokeWidth={1.75} />
      </button>
    </Tooltip>
  );
}

function ThreadSwitcher() {
  const [open, setOpen] = useState(false);
  const threads = useAskThreadStore((s) => s.threads);
  const activeThreadId = useAskThreadStore((s) => s.activeThreadId);
  const { switchThread, deleteThread, newThread } = useAskThreadStore.getState();

  const active = threads.find((t) => t.id === activeThreadId);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      side="bottom"
      align="start"
      trigger={
        // Reads as a control, not a heading. The bare title + glyph it used to
        // be looked exactly like the panel's own label, so nobody clicked it
        // and the thread history stayed undiscovered: hence the chevron, the
        // resting outline, and the focus ring.
        <button
          type="button"
          className={cn(
            "flex max-w-[240px] items-center gap-1.5 rounded-full border border-hair px-2 py-1",
            "font-sans text-[13px] text-ink transition-colors hover:border-transparent hover:bg-lavender/60",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-magenta/40",
            open && "border-transparent bg-lavender/60",
          )}
          aria-label="Conversation threads"
          aria-haspopup="dialog"
          aria-expanded={open}
        >
          <History size={13} strokeWidth={1.5} aria-hidden className="shrink-0 text-muted" />
          <span className="truncate">{active?.title ?? "Ask Mnemify"}</span>
          <ChevronDown size={12} strokeWidth={1.75} aria-hidden className="shrink-0 text-muted" />
        </button>
      }
    >
      <div className="w-72 py-1 font-sans text-sm">
        <button
          type="button"
          onClick={() => {
            newThread();
            setOpen(false);
          }}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-ink hover:bg-bone/60"
        >
          <Plus size={14} strokeWidth={1.5} aria-hidden />
          New thread
        </button>
        {threads.length > 0 ? <div className="my-1 border-t border-hair" /> : null}
        <div className="max-h-80 overflow-y-auto">
          {threads.map((t) => (
            <div
              key={t.id}
              className={cn(
                "group flex items-center gap-2 px-3 py-1.5 hover:bg-bone/60",
                t.id === activeThreadId ? "bg-bone/40" : "",
              )}
            >
              <button
                type="button"
                onClick={() => {
                  switchThread(t.id);
                  setOpen(false);
                }}
                className="min-w-0 flex-1 text-left"
              >
                <span className="block truncate text-ink">{t.title}</span>
                <span className="block text-[11px] text-muted">
                  {relativeTime(new Date(t.updatedAt).toISOString())}
                </span>
              </button>
              <button
                type="button"
                onClick={() => deleteThread(t.id)}
                aria-label={`Delete thread: ${t.title}`}
                className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted opacity-0 transition-opacity hover:text-rose group-hover:opacity-100"
              >
                <Trash2 size={13} strokeWidth={1.5} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </Popover>
  );
}

/** Compass-rose glyph — the Ask brand mark, carried over from the orb. */
export function AskGlyph({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className="text-ink"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9.2" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1" />
      <path
        d="M12 2.4 L13.4 10.6 L21.6 12 L13.4 13.4 L12 21.6 L10.6 13.4 L2.4 12 L10.6 10.6 Z"
        fill="currentColor"
        fillOpacity="0.9"
      />
      <path
        d="M6 6 L11.2 11.2 M18 6 L12.8 11.2 M18 18 L12.8 12.8 M6 18 L11.2 12.8"
        stroke="currentColor"
        strokeOpacity="0.4"
        strokeWidth="0.8"
      />
      <circle cx="12" cy="12" r="1.7" fill="currentColor" />
    </svg>
  );
}

// Faint contour-ring + glow watermark behind the panel, echoing the map's
// cartographer paper (carried over from the orb's bloom popover).
function AskBackdrop() {
  return (
    <div aria-hidden className="absolute inset-0 z-0 overflow-hidden opacity-[0.5]">
      <div
        className="absolute -right-16 -top-20 h-72 w-72 rounded-full"
        style={{ background: "radial-gradient(circle, rgb(var(--c-magenta) / 0.12), transparent 70%)" }}
      />
      <svg className="absolute -bottom-10 -left-8 text-line" width="220" height="220" viewBox="0 0 220 220" fill="none">
        {[40, 62, 84, 106].map((r) => (
          <circle key={r} cx="60" cy="160" r={r} stroke="currentColor" strokeOpacity="0.18" strokeWidth="1" strokeDasharray="2 6" />
        ))}
      </svg>
    </div>
  );
}
