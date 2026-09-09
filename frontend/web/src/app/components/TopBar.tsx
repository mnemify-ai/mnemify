import { useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Moon, Search, Settings, Sun } from "lucide-react";
import { cn } from "../lib/cn";
import { useTerrainCurrent } from "../api/terrain";
import { useHarvestCurrent } from "../api/harvest";
import { totalChanges, type ChangesResponse } from "../api/changes";
import { apiFetch } from "../api/client";
import { toastInfo, toastSuccess } from "../lib/toast";
import { qk } from "../api/keys";
import { useCommandPalette } from "../lib/commandPalette";
import { useThemeMode } from "../lib/useThemeMode";
import { BrandMark } from "./BrandMark";
import { Kbd } from "./ui/Kbd";
import { OpsPill } from "./OpsPill";

/**
 * Global watcher: when any compile finishes (even one running in the
 * background), drop the cached map data + report so the map and compile page
 * reload the freshly written render-data.json. MapDataProvider caches with
 * staleTime: Infinity, so without this the 3D map shows the previous compile's
 * tags/names until a full reload. Lives in the always-mounted TopBar so it
 * fires regardless of the current route. Reuses the poll MinimizedCompilePill
 * already runs — no extra request.
 */
function useRefreshMapDataOnCompileComplete() {
  const qc = useQueryClient();
  const { data } = useTerrainCurrent({ poll: true });
  const prev = useRef<string | undefined>(data?.status);
  useEffect(() => {
    const before = prev.current;
    prev.current = data?.status;
    if (before === "running" && data?.status === "complete") {
      qc.invalidateQueries({ queryKey: qk.mapData() });
      qc.invalidateQueries({ queryKey: qk.terrainReport() });
      qc.invalidateQueries({ queryKey: qk.terrainRuns() });
      qc.invalidateQueries({ queryKey: qk.actionItems() });
      // A compile moves the "since last compile" boundary — pending changes
      // are now part of the map, so the pill/feed must recount (to zero).
      qc.invalidateQueries({ queryKey: ["changes"] });
    }
  }, [data?.status, qc]);
}

/**
 * Same idea for harvests: when one finishes, the pending-changes count is
 * stale (new docs just landed). Reuses the poll MinimizedHarvestPill already
 * runs on the same query key — no extra request. On a successful run it also
 * fires the global "N pages changed — compile?" toast, so scheduled harvests
 * surface their news even when the user is nowhere near the harvest page.
 */
function useRefreshChangesOnHarvestComplete() {
  const qc = useQueryClient();
  // Slow idle heartbeat: a scheduled harvest can start AND finish between
  // visits, so we can't rely on ever observing status === "running".
  const { data } = useHarvestCurrent({ poll: true, idlePollMs: 60_000 });
  // Track finished_at instead of status: a new terminal finished_at means a
  // run completed since the last snapshot, even if we never saw it running.
  // Starts undefined so the first snapshot after mount never toasts — the
  // BriefingCard owns the "you arrived after a harvest" moment.
  const prevFinished = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (!data) return; // query still loading — don't consume the first-snapshot guard
    const before = prevFinished.current;
    prevFinished.current = data.finished_at;
    if (data.status !== "complete" && data.status !== "cancelled") return;
    if (before === undefined) return;
    if (data.finished_at === before) return;
    qc.invalidateQueries({ queryKey: ["changes"] });
    if (data.status !== "complete") return;
    void qc
      .fetchQuery({
        queryKey: qk.changes(),
        queryFn: () => apiFetch<ChangesResponse>("/api/changes?since=last_compile"),
      })
      .then((changes) => {
        const total = totalChanges(changes.summary);
        if (changes.compile_running) {
          toastInfo("Harvest complete — compiling your map now.");
        } else if (total > 0) {
          toastSuccess(
            `${total.toLocaleString()} page${total === 1 ? "" : "s"} changed since your last compile.`,
            {
              description: "Compile to fold them into your map.",
              action: {
                label: "Compile",
                onClick: () =>
                  void apiFetch("/api/terrain/build", {
                    method: "POST",
                    body: JSON.stringify({}),
                  }).then(() => qc.invalidateQueries({ queryKey: qk.terrainCurrent() })),
              },
            },
          );
        }
      })
      .catch(() => undefined);
  }, [data?.status, data?.finished_at, qc]);
}

// Ordered by usage frequency: daily surfaces first, occasional pipeline ops
// behind one tab, rare Settings demoted to the gear icon on the right.
/** Light/dark toggle. The Settings→General picker remains the canonical
 *  control; both stay in sync via useThemeMode's class-list observer. */
function ThemeToggle() {
  const [mode, setMode] = useThemeMode();
  const dark = mode === "dark";
  return (
    <button
      type="button"
      onClick={() => setMode(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="grid h-9 w-9 place-items-center rounded-full border border-hair bg-bone/40 text-muted transition-colors hover:bg-bone hover:text-ink"
    >
      {dark ? (
        <Sun size={15} strokeWidth={1.75} aria-hidden />
      ) : (
        <Moon size={15} strokeWidth={1.75} aria-hidden />
      )}
    </button>
  );
}

// TODOs sits second: it's the surface with the most time-sensitive content
// (overdue / due-soon deadlines), so it earns the slot right after the map.
// Label matches the page's own heading (ActionItemsPage title="TODOs").
const NAV_ITEMS = [
  { to: "/", label: "Map", end: true },
  { to: "/action-items", label: "TODOs" },
  { to: "/documents", label: "Documents" },
  { to: "/build", label: "Build" },
];

export function TopBar() {
  const { pathname } = useLocation();
  const isHome = pathname === "/";
  const openPalette = useCommandPalette((s) => s.setOpen);
  useRefreshMapDataOnCompileComplete();
  useRefreshChangesOnHarvestComplete();

  return (
    <header
      className={cn(
        "fixed top-0 inset-x-0 z-40 h-16 flex items-center transition-colors duration-300",
        isHome
          ? "bg-cream/55 backdrop-blur-md border-b border-hair/60"
          : "bg-cream/95 backdrop-blur-md border-b border-hair",
      )}
    >
      <div className="w-full max-w-page mx-auto px-6 lg:px-10 flex items-center justify-between gap-6">
        <div className="flex items-center gap-10">
          <BrandMark />
          <nav className="hidden md:flex items-center gap-1" aria-label="Primary">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "font-sans uppercase tracking-eyebrow text-[13px] px-3 py-2 transition-colors",
                    isActive ? "text-ink" : "text-muted hover:text-ink",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => openPalette(true)}
            aria-label="Search notes and tags"
            aria-keyshortcuts="Meta+K Control+K"
            className={cn(
              "group inline-flex items-center gap-2 h-9 rounded-full",
              "border border-hair bg-bone/40 hover:bg-bone",
              "text-muted hover:text-ink transition-colors",
              "pl-2.5 pr-2.5 md:pr-2",
            )}
          >
            <Search size={15} strokeWidth={1.75} aria-hidden />
            <span className="hidden md:inline font-sans text-[13px]">Search</span>
            <Kbd className="hidden md:inline-flex ml-0.5">⌘K</Kbd>
          </button>
          <OpsPill />
          <ThemeToggle />
          <NavLink
            to="/settings"
            aria-label="Settings"
            className={({ isActive }) =>
              cn(
                "grid h-9 w-9 place-items-center rounded-full border border-hair transition-colors",
                isActive
                  ? "bg-lavender/60 text-ink"
                  : "bg-bone/40 text-muted hover:bg-bone hover:text-ink",
              )
            }
          >
            <Settings size={15} strokeWidth={1.75} aria-hidden />
          </NavLink>
        </div>
      </div>
    </header>
  );
}
