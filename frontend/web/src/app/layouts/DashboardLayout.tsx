import { useMemo, useState, type CSSProperties } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useMapData } from "../data/MapDataProvider";
import { TopBar } from "../components/TopBar";
import { CommandPalette } from "../components/CommandPalette";
import { AskDock } from "../../ask/AskDock";
import { AskBubble } from "../../ask/AskBubble";
import { useAskDockStore } from "../../ask/askDockStore";
import { MAP_PANEL_GUTTER, useMapPanelStore } from "../lib/mapPanelStore";
import { useHeartbeat } from "../lib/useHeartbeat";
import { cn } from "../lib/cn";

/** What the shell hands its routes through `<Outlet context>`. */
export type ShellOutletContext = {
  /** Full-window row under the shell's content row (Home only). The knowledge
   *  map portals its bottom bar in here so the bar spans the whole window —
   *  past the Ask dock — while staying inside KnowledgeMap's React tree. */
  bottomBarSlot: HTMLElement | null;
};

/**
 * The floating Ask launcher. Shell-level, so every route keeps a visible way
 * into chat now that the TopBar pill is gone (⌘J and the command palette are
 * the other two). Fixed bottom-right, offset past the map's detail
 * panel on Home so it lands where it always did — inside the canvas column,
 * clear of the panel's scrolling content — rather than on top of it. Off the
 * map the reported panel width is 0, so this is a plain `right-6`.
 *
 * Its own component so the shell itself doesn't subscribe to the panel-width
 * store: a re-render up here would cascade through <Outlet> into the 3D
 * canvas on every collapse toggle and drag release.
 */
function ShellAskBubble({ isHome }: { isHome: boolean }) {
  const mapPanelWidth = useMapPanelStore((s) => s.width);
  return (
    <div
      className={cn(
        // Above page content, below the TopBar (z-40) and dialogs/drawers
        // (z-40/z-50). The bubble hides itself whenever the dock is open, so
        // it never competes with the dock column (z-30) either.
        "fixed z-30 right-6 md:right-[var(--ask-bubble-inset)]",
        "transition-[right] duration-base ease-out motion-reduce:transition-none",
        // Home hangs a full-window bottom bar under the content row; sit well
        // above it, the way the old on-map orb did.
        isHome ? "bottom-24" : "bottom-6",
      )}
      style={
        {
          "--ask-bubble-inset": `${mapPanelWidth + MAP_PANEL_GUTTER}px`,
        } as CSSProperties
      }
    >
      <AskBubble />
    </div>
  );
}

export function DashboardLayout() {
  const { data, isLoading, error } = useMapData();
  const location = useLocation();
  const isHome = location.pathname === "/";
  // No compiled map ⇒ nothing to ask about. Chat (launcher + dock) stays out
  // of the way until there is a map to show, so the empty state has one job.
  const hasMap = data !== null;
  // Callback ref, not useRef: routes render off this element, so the first
  // render must be followed by a re-render once it exists.
  const [barSlot, setBarSlot] = useState<HTMLDivElement | null>(null);
  const outletCtx = useMemo<ShellOutletContext>(
    () => ({ bottomBarSlot: barSlot }),
    [barSlot],
  );
  // Maximized dock ⇒ the route column steps out of the row entirely. Not just
  // cosmetic: a flex child squeezed to 0 width still lays out (text wrapping
  // one word per line), which on a scrolling route would balloon the page
  // height behind the dock. Only from `md` up — below it the dock itself is
  // display:none, so the route must keep the screen.
  //
  // That's also why "maximized" and "a document open beside the chat" are
  // mutually exclusive states rather than a layout to be solved: there is no
  // beside. Opening either kind of document surface un-maximizes the dock
  // (SideDrawer's `avoidAskDock` for the drawers, AskDock's `viewSource` for
  // the /documents pane), and `askDockStore.overlays` keeps Maximize disabled
  // while a drawer holds that slot. `display:none` here also takes any
  // `position: fixed` descendant with it, so a route that anchors to the
  // viewport (DocumentsPage's two-pane layout) disappears with the column
  // instead of stranding itself under the dock.
  const dockMaximized = useAskDockStore((s) => s.open && s.wide) && hasMap;

  // The shell is the one component mounted on every route, so this is the one
  // place the "a human is watching" beat belongs. Above the early returns:
  // the loading and error states are still an open tab.
  useHeartbeat();

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <p className="eyebrow text-rose mb-3">Couldn't load map data</p>
          <p className="font-serif text-2xl text-ink mb-2">{error.message}</p>
          <p className="text-sm text-muted">
            Check that the backend is running and{" "}
            <code className="font-mono text-xs">/api/terrain/render-data</code> is reachable —
            you may just need to compile (Build → Compile).
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="font-serif text-3xl text-ink/70 animate-pulse">Loading the map…</div>
          <p className="eyebrow mt-3">Reading your compiled map</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={
        isHome ? "flex h-dvh w-full flex-col overflow-hidden" : "min-h-screen"
      }
    >
      <TopBar />
      {/* Shell row: route content + the persistent Ask dock. The dock is a
          structural column (mounted once, on every route) so an in-flight
          conversation survives navigation by construction. On Home the row is
          a fixed-height flex child so the map's bottom bar can sit below it,
          spanning the window; elsewhere the page scrolls as before. */}
      <div className={cn("flex w-full", isHome && "min-h-0 flex-1 overflow-hidden")}>
        <div className={cn("min-w-0 flex-1", dockMaximized && "md:hidden")}>
          <Outlet context={outletCtx} />
        </div>
        {hasMap && <AskDock />}
      </div>
      {/* Full-width bottom-bar row — filled by the map via a portal. */}
      {isHome && <div ref={setBarSlot} className="shrink-0" />}
      {hasMap && <ShellAskBubble isHome={isHome} />}
      <CommandPalette />
    </div>
  );
}
