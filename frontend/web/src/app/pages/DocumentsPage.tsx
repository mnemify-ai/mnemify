import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import { PanelLeftOpen, SlidersHorizontal } from "lucide-react";
import { PageShell } from "../layouts/PageShell";
import { DocFiltersPanel } from "../components/DocFiltersPanel";
import { DocTable } from "../components/DocTable";
import { DocViewerPane } from "../components/DocViewerPane";
import { ResizableSplit } from "../components/ResizableSplit";
import { FilterChips } from "../components/FilterChips";
import { SideDrawer } from "../components/ui/SideDrawer";
import { Button } from "../components/ui/Button";
import { cn } from "../lib/cn";
import { useDocFilters } from "../lib/useDocFilters";
import { useDocuments, useDocumentStats } from "../api/documents";
import {
  dockInsetCss,
  dockOverlayInset,
  useAskDockStore,
} from "../../ask/askDockStore";

const PAGE_LIMIT = 10000;

const FILTERS_COLLAPSED_KEY = "mnemify.docs.filtersCollapsed";

/** Split minimums, reconciled against the width the Ask dock leaves behind.
 *  The dock's own contract (`dockDragMaxWidth`) only promises 420px of app
 *  behind it, and the tightest desktop case we support is a 1280px window
 *  with a 460px dock — 820px. The previous 560/420 pair summed to 986px with
 *  the divider and so overflowed there *and* at 1440/460 (980px). 420 + 6 +
 *  360 = 786 clears both, and the filters rail auto-collapses on the way in
 *  (below) so the table still gets ~312px at the floor rather than ~156px. */
const SPLIT_MIN_LEFT = 420;
const SPLIT_MIN_RIGHT = 360;

export function DocumentsPage() {
  const { filters, setFilters, clear, activeCount } = useDocFilters();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("id");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [filtersCollapsed, setFiltersCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(FILTERS_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(FILTERS_COLLAPSED_KEY, filtersCollapsed ? "1" : "0");
    } catch {
      /* ignore — private mode etc. */
    }
  }, [filtersCollapsed]);

  const stats = useDocumentStats();
  const apiSource = filters.sources.length === 1 ? filters.sources[0] : null;
  const docs = useDocuments({
    source: apiSource,
    search: filters.search || null,
    page: 0,
    limit: PAGE_LIMIT,
  });

  const rows = useMemo(() => {
    const all = docs.data?.rows ?? [];
    if (filters.sources.length <= 1) return all;
    const set = new Set(filters.sources);
    return all.filter((r) => set.has(r.source));
  }, [docs.data, filters.sources]);

  const total = docs.data?.total ?? 0;
  const totalDocs = stats.data?.total_documents ?? 0;

  function selectDoc(id: string | null) {
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        if (id === null) out.delete("id");
        else out.set("id", id);
        return out;
      },
      { replace: false },
    );
  }

  const viewerOpen = selectedId !== null;

  // How far the fixed two-pane layout below must stop short of the viewport's
  // right edge so the Ask dock (a z-30 flex column in the shell row) lands
  // beside it instead of over it. This container is viewport-anchored, so
  // without the inset the dock painted across its right portion — the doc
  // sitting *behind* the chat with a useless sliver showing.
  const dockInset = useAskDockStore((s) => dockOverlayInset(s));
  const dockOpen = useAskDockStore((s) => s.open);

  // Space is genuinely tight once the dock and a document share the row, so
  // fold the filters rail down to its 44px stub the first time both are on
  // screen — the same "snap to the matching default when the Ask dock opens"
  // move KnowledgeMap makes with its detail panel. One-shot, guarded by the
  // previous value: re-expanding sticks, and re-renders don't re-collapse.
  const wasTightRef = useRef(false);
  useEffect(() => {
    const tight = viewerOpen && dockOpen;
    if (tight && !wasTightRef.current) setFiltersCollapsed(true);
    wasTightRef.current = tight;
  }, [viewerOpen, dockOpen]);

  // The viewer below is `position: fixed` inside the shell's route column, and
  // a maximized dock drops that column out of layout entirely (`md:hidden` in
  // DashboardLayout) — which takes the fixed viewer with it, document and all.
  // So claim an overlay slot for as long as the viewer is open, exactly as
  // SideDrawer does for the evidence drawers: the dock un-maximizes on the way
  // in and Maximize stays disabled until we let go. AskDock's `viewSource`
  // un-maximizes eagerly so the column exists by the time we mount; this is
  // what keeps it that way, and what covers the other ways in (a row click, a
  // pasted `?id=` URL). The cleanup releases the slot on close, on navigation
  // away and on unmount — balanced, so a StrictMode double-invoke nets zero.
  useEffect(() => {
    if (!viewerOpen) return;
    const { openOverlay, closeOverlay } = useAskDockStore.getState();
    openOverlay();
    return closeOverlay;
  }, [viewerOpen]);

  if (viewerOpen) {
    // Full-height two-pane layout: bypass PageShell so the viewer can extend
    // all the way to the top nav. Only the TopBar (h-16 / 64px) sits above
    // us now — the old sticky sub-nav is gone.
    //
    // Exactly two panes: the list and the document. A citation's "View
    // source" routes here via `?id=` (see AskDock) rather than opening the
    // drawer, so the chat and the table drive the same single viewer.
    return (
      <div
        className={cn(
          // Below the dock's z-30 on purpose: they no longer overlap, but the
          // inset transition and the dock's instant mount can cross for a
          // frame, and chat-briefly-over-document beats the reverse.
          "fixed left-0 right-0 bottom-0 z-10 flex md:right-[var(--ask-dock-inset)]",
          "transition-[right] duration-base ease-out motion-reduce:transition-none",
        )}
        style={
          {
            top: "4rem",
            // Re-clamped to this viewport, exactly the way the dock clamps
            // its own aside — see `dockInsetCss`. Without it a width dragged
            // wide on a big monitor would push `right` past `left-0` here and
            // blank the page on a laptop.
            "--ask-dock-inset": dockInsetCss(dockInset),
          } as CSSProperties
        }
      >
        <ResizableSplit
          left={
            <div className="h-full flex flex-col min-w-0 min-h-0 bg-cream">
              <header className="px-8 pt-5 pb-3 border-b border-hair shrink-0">
                <p className="font-serif text-lg text-ink leading-tight">
                  Documents
                </p>
                <p className="font-sans text-[11px] text-muted mt-0.5">
                  {totalDocs.toLocaleString()} harvested
                </p>
              </header>
              <div className="flex-1 min-h-0 flex">
                {filtersCollapsed ? (
                  <aside className="w-11 shrink-0 border-r border-hair px-2 py-4 flex justify-center">
                    <button
                      type="button"
                      onClick={() => setFiltersCollapsed(false)}
                      aria-label="Expand filters"
                      className="self-start flex flex-col items-center gap-2 px-2 py-3 rounded-xl border border-hair bg-bone/40 hover:bg-bone/70 text-muted hover:text-ink transition-colors"
                    >
                      <PanelLeftOpen size={16} strokeWidth={1.5} aria-hidden />
                      {activeCount > 0 && (
                        <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-magenta text-cream text-[10px] font-medium tabular-nums">
                          {activeCount}
                        </span>
                      )}
                    </button>
                  </aside>
                ) : (
                  <aside className="w-64 shrink-0 border-r border-hair px-5 py-4 overflow-y-auto">
                    <DocFiltersPanel
                      filters={filters}
                      setFilters={setFilters}
                      onClear={clear}
                      activeCount={activeCount}
                      bySource={stats.data?.by_source ?? {}}
                      inSheet
                      onCollapse={() => setFiltersCollapsed(true)}
                    />
                  </aside>
                )}
                <div className="flex-1 min-w-0 px-8 py-4 flex flex-col min-h-0 gap-3">
                  <FilterChips filters={filters} setFilters={setFilters} onClear={clear} />
                  <DocTable
                    rows={rows}
                    total={total}
                    loading={docs.isLoading}
                    onSelect={selectDoc}
                    filters={filters}
                    activeFilterCount={activeCount}
                    onClearFilters={clear}
                  />
                </div>
              </div>
            </div>
          }
          right={
            <DocViewerPane
              key={selectedId ?? "none"}
              docId={selectedId!}
              onClose={() => selectDoc(null)}
            />
          }
          initialLeftFraction={0.55}
          minLeft={SPLIT_MIN_LEFT}
          minRight={SPLIT_MIN_RIGHT}
          // v2: fractions chosen against the old 560/420 minimums (and against
          // a container that ran under the dock) would restore into a starved
          // pane here. ResizableSplit now re-clamps stored fractions at render
          // time too, but the bumped key keeps the old values out regardless.
          storageKey="mnemify.docViewerSplit.v2"
        />
      </div>
    );
  }

  return (
    <PageShell
      title="Documents"
      description={
        totalDocs > 0
          ? `${totalDocs.toLocaleString()} document${totalDocs === 1 ? "" : "s"} harvested. Filter by source or search the titles.`
          : "Nothing harvested yet — connect a source on the Connections page and run a harvest."
      }
    >
      {/* Mobile filters trigger */}
      <div className="md:hidden mb-3 flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setMobileFiltersOpen(true)}
        >
          <SlidersHorizontal size={14} strokeWidth={1.5} />
          Filters
          {activeCount > 0 && (
            <span className="ml-1 inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-magenta text-cream text-[10px] font-medium tabular-nums">
              {activeCount}
            </span>
          )}
        </Button>
      </div>

      <div
        className={cn(
          "grid grid-cols-1 gap-8 transition-[grid-template-columns] duration-base ease-out",
          filtersCollapsed
            ? "md:grid-cols-[44px_1fr]"
            : "md:grid-cols-[clamp(220px,20vw,280px)_1fr]",
        )}
      >
        <div className="hidden md:block">
          {filtersCollapsed ? (
            <button
              type="button"
              onClick={() => setFiltersCollapsed(false)}
              aria-label="Expand filters"
              className="sticky top-20 self-start flex flex-col items-center gap-2 px-2 py-3 rounded-xl border border-hair bg-bone/40 hover:bg-bone/70 text-muted hover:text-ink transition-colors"
            >
              <PanelLeftOpen size={16} strokeWidth={1.5} aria-hidden />
              {activeCount > 0 && (
                <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-magenta text-cream text-[10px] font-medium tabular-nums">
                  {activeCount}
                </span>
              )}
            </button>
          ) : (
            <DocFiltersPanel
              filters={filters}
              setFilters={setFilters}
              onClear={clear}
              activeCount={activeCount}
              bySource={stats.data?.by_source ?? {}}
              onCollapse={() => setFiltersCollapsed(true)}
            />
          )}
        </div>
        <div className="space-y-3 min-w-0">
          <FilterChips filters={filters} setFilters={setFilters} onClear={clear} />
          <div className="h-[600px]">
            <DocTable
              rows={rows}
              total={total}
              loading={docs.isLoading}
              onSelect={selectDoc}
              filters={filters}
              activeFilterCount={activeCount}
              onClearFilters={clear}
            />
          </div>
          {total > PAGE_LIMIT && (
            <p className="font-sans text-xs text-muted text-center">
              Showing the first {PAGE_LIMIT.toLocaleString()} of {total.toLocaleString()} — narrow the search to see more.
            </p>
          )}
        </div>
      </div>

      <SideDrawer
        open={mobileFiltersOpen}
        onOpenChange={setMobileFiltersOpen}
        width="320px"
      >
        <div className="p-6 pt-12 overflow-y-auto h-full">
          <DocFiltersPanel
            filters={filters}
            setFilters={setFilters}
            onClear={clear}
            activeCount={activeCount}
            bySource={stats.data?.by_source ?? {}}
            inSheet
          />
        </div>
      </SideDrawer>
    </PageShell>
  );
}
