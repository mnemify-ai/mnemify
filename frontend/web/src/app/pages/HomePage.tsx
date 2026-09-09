import { useEffect, useState, type CSSProperties } from "react";
import { useOutletContext } from "react-router-dom";
import { Layers } from "lucide-react";
import { KnowledgeMap } from "../../knowledgeMap";
import { FloatingSourcesPanel } from "../components/FloatingSourcesPanel";
import { MapEmptyState } from "../components/MapEmptyState";
import { DemoTerrain } from "../components/DemoTerrain";
import { MapInteractionHint } from "../components/MapInteractionHint";
import { BriefingCard } from "../components/BriefingCard";
import { SideDrawer } from "../components/ui/SideDrawer";
import { useMapFocusStore } from "../lib/mapFocusStore";
import { MAP_PANEL_GUTTER, useMapPanelStore } from "../lib/mapPanelStore";
import { useAskDockStore } from "../../ask/askDockStore";
import type { ShellOutletContext } from "../layouts/DashboardLayout";
import { useTagParam } from "../lib/useTagParam";
import { useMapData } from "../data/MapDataProvider";
import { useConnections } from "../api/connections";
import { useDocumentStats } from "../api/documents";
import { useTerrainReport } from "../api/terrain";
import { apiUrl } from "../api/client";

/**
 * Home — the 3D knowledge map (built from the compiled terrain) with floating
 * overlays. If nothing's compiled yet, show <MapEmptyState> instead.
 */
export function HomePage() {
  const [selectedTagId, setSelectedTagId] = useTagParam();
  // Region focus for citations that aren't a tag (region/note/entity/signal
  // "Show on terrain") — lives in a module-level store so the Ask dock
  // (mounted outside this page) can fly the camera, including requests made
  // from other routes that land here after a navigate("/").
  const focusRegionId = useMapFocusStore((s) => s.focusRegionId);
  const setFocusRegionId = useMapFocusStore((s) => s.setFocusRegion);
  // Two right-hand columns compete for the viewport when chat is open, so the
  // map's detail panel takes its compact width while the dock is showing.
  const askDockOpen = useAskDockStore((s) => s.open);
  // Maximized chat drops the route column out of layout, but the bottom bar
  // portals into a shell-owned row outside it — so withhold the slot too,
  // or map statistics linger under a full-window chat with no map.
  const dockMaximized = useAskDockStore((s) => s.open && s.wide);
  // The map's bottom bar renders into this shell-owned row so it spans the
  // whole window (past the Ask dock) instead of just the map column. It's
  // null until the shell's callback ref attaches — KnowledgeMap holds the bar
  // back for that one frame rather than flashing it inline.
  const { bottomBarSlot } = useOutletContext<ShellOutletContext>();
  // The detail panel's real width, published for chrome that floats beside it
  // (the briefing card below, the shell's Ask bubble). It's resizable, snaps
  // narrower with the dock, and collapses to a rail — so mirrored constants
  // go stale on first drag. Cleared on the way out: off Home there's no panel.
  const mapPanelWidth = useMapPanelStore((s) => s.width);
  const setMapPanelWidth = useMapPanelStore((s) => s.setWidth);
  useEffect(() => () => setMapPanelWidth(0), [setMapPanelWidth]);
  const mapData = useMapData();
  const connections = useConnections();
  const docStats = useDocumentStats();
  const report = useTerrainReport();
  // E7: on <md viewports the FloatingSourcesPanel is hidden in favor of a
  // pill-button that opens this drawer (the KnowledgeMap fills the screen on
  // mobile — there's no room for two fixed corner panels).
  const [sourcesDrawerOpen, setSourcesDrawerOpen] = useState(false);
  // Empty-state "feel the payoff first" preview (bundled sample terrain).
  const [demoMode, setDemoMode] = useState(false);

  // No compiled map yet → onboarding screen (or the sample-map preview).
  if (mapData.data === null) {
    if (mapData.isLoading) {
      return (
        <div className="relative min-h-dvh w-full overflow-hidden bg-cream flex items-center justify-center">
          <span className="font-serif text-muted animate-pulse motion-reduce:animate-none">Loading…</span>
        </div>
      );
    }
    if (demoMode) {
      return <DemoTerrain onExit={() => setDemoMode(false)} />;
    }
    const connected = (connections.data ?? []).some((c) => c.status === "connected");
    const harvested = (docStats.data?.total_documents ?? 0) > 0;
    const compiled = report.data?.exists === true;
    return (
      <div className="relative min-h-dvh w-full overflow-hidden">
        <MapEmptyState
          connected={connected}
          harvested={harvested}
          compiled={compiled}
          renderFailed={compiled && mapData.empty}
          onTryDemo={() => setDemoMode(true)}
        />
      </div>
    );
  }

  return (
    // `h-full`, not `min-h-dvh`: on Home the shell is a flex column and this
    // page fills the row above the full-width bottom bar.
    <div className="relative h-full w-full overflow-hidden">
      <div className="absolute inset-0 z-0">
        <KnowledgeMap
          dataUrl={apiUrl("/api/terrain/render-data")}
          notesUrl={apiUrl("/api/terrain/notes")}
          hideHeader
          hideBreadcrumb
          selectedTagId={selectedTagId}
          onTagSelect={setSelectedTagId}
          focusRegionId={focusRegionId}
          onFocusChange={setFocusRegionId}
          compactRightPanel={askDockOpen}
          onPanelWidthChange={setMapPanelWidth}
          bottomBarSlot={dockMaximized ? null : bottomBarSlot}
        />
      </div>
      {/* Mobile (<md): pill button opens a SideDrawer with the same panel —
          the structural right sidebar is hidden below `md` in KnowledgeMap. */}
      <div className="pointer-events-none absolute inset-0 z-20">
        <div className="pointer-events-auto absolute top-20 left-4 md:hidden animate-fade-in motion-reduce:animate-none">
          <button
            type="button"
            onClick={() => setSourcesDrawerOpen(true)}
            aria-label="Open sources panel"
            className="glass-panel rounded-full pl-3 pr-4 py-2 inline-flex items-center gap-1.5 font-sans text-xs text-ink shadow-sm"
          >
            <Layers size={14} strokeWidth={1.5} aria-hidden />
            Sources
          </button>
        </div>
        {/* First-interaction hint — top-center, clear of the right sidebar and
            the top-left mobile pill. Mouse-oriented copy, so desktop-only. */}
        <div className="pointer-events-auto absolute top-20 left-1/2 -translate-x-1/2 max-w-[calc(100vw-2rem)] hidden sm:block animate-fade-in motion-reduce:animate-none [animation-delay:80ms]">
          <MapInteractionHint selectedTagId={selectedTagId} />
        </div>
        {/* Daily briefing — top-right, clear of the map's detail sidebar. The
            inset tracks the sidebar's *actual* width (it narrows with the Ask
            dock, is drag-resizable, and collapses to a rail) instead of
            mirroring its constants, which desynced on the first drag. Below
            `md` the sidebar is hidden, so the plain `right-4` applies. Shows
            only post-first-interaction, so it never co-exists with the hint. */}
        <div
          className="pointer-events-auto absolute top-20 right-4 md:right-[var(--map-panel-inset)] max-w-[calc(100vw-2rem)] transition-[right] duration-base ease-out motion-reduce:transition-none animate-fade-in motion-reduce:animate-none [animation-delay:120ms]"
          style={
            {
              "--map-panel-inset": `${mapPanelWidth + MAP_PANEL_GUTTER}px`,
            } as CSSProperties
          }
        >
          <BriefingCard onTagSelect={setSelectedTagId} />
        </div>
      </div>
      <SideDrawer
        open={sourcesDrawerOpen}
        onOpenChange={setSourcesDrawerOpen}
        width="320px"
      >
        <div className="p-6 pt-12">
          <FloatingSourcesPanel />
        </div>
      </SideDrawer>
      {/* Ask lives in the shell: DashboardLayout mounts the floating bubble
          and the AskDock (⌘J / command palette), and the dock owns the
          citation SourceInspector. */}
    </div>
  );
}
