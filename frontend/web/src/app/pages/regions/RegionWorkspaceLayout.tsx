import { useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { Map as MapIcon, Sparkles } from "lucide-react";
import { PageShell } from "../../layouts/PageShell";
import { Button } from "../../components/ui/Button";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { RegionBreadcrumb } from "../../components/regions/RegionBreadcrumb";
import { RegionSwitcher } from "../../components/regions/RegionSwitcher";
import { RegionMapDialog } from "../../components/regions/RegionMapDialog";
import { MemoryItemRow } from "../../components/regions/MemoryItemRow";
import { MemoryEditDialog } from "../../components/regions/MemoryEditDialog";
import {
  describeStaleRegion,
  useDeleteMemory,
  useReassignUnassigned,
  useUnassignedRegion,
  type MemoryItem,
} from "../../api/regions";
import { useMapData } from "../../data/MapDataProvider";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/relativeTime";
import { toastError, toastInfo, toastSuccess } from "../../lib/toast";
import { resumeThread } from "../../../ask/threadSync";
import { useRegionWorkspace } from "./useRegionWorkspace";

const TABS = [
  { to: "", label: "Overview", end: true },
  { to: "memory", label: "Memory", end: false },
  { to: "activity", label: "Activity", end: false },
];

/** /regions/:regionId — the workspace frame: breadcrumb + switcher, tabs,
 *  a compact title row with "Open map" / "Ask region", then the tab bar. */
export function RegionWorkspaceLayout() {
  const { regionId = "" } = useParams();
  const ctx = useRegionWorkspace(regionId);
  const map = useMapData();
  const { detail, loading, error, entry } = ctx;
  const [mapOpen, setMapOpen] = useState(false);

  if (map.empty) return <Navigate to="/regions" replace />;

  const stale = error ? describeStaleRegion(error) : null;
  if (stale?.kind === "moved") {
    return <MovedRedirect to={stale.movedTo} />;
  }
  if (stale?.kind === "orphaned") {
    return <UnassignedRegionPage regionKey={stale.regionKey} regionName={stale.regionName} />;
  }
  if (stale?.kind === "unknown" && !entry) {
    return (
      <PageShell title="Region not found" eyebrow="Workspaces">
        <ErrorState
          title="This region isn't on the current map"
          description="It may have been merged into another region by a recompile. Pick a region to continue."
          action={<Button variant="secondary" onClick={() => undefined}><RegionSwitcher currentId={null} label="Choose a region" /></Button>}
        />
      </PageShell>
    );
  }
  if (error && !stale) {
    return (
      <PageShell title={entry?.name ?? "Region"} eyebrow="Workspaces">
        <ErrorState title="Couldn't load this workspace" description={String((error as Error)?.message ?? "")} />
      </PageShell>
    );
  }

  const name = detail?.region.name ?? entry?.name ?? "Region";
  const noteCount = detail?.region.note_count ?? map.data?.indexes.notesByRegionSubtree.get(regionId)?.length ?? 0;
  const sourceCount = detail?.sources.length ?? entry?.sources ?? 0;
  const touched = detail?.region.last_touched_at ?? null;
  const path = detail?.path ?? (map.data?.indexes.regionPathById.get(regionId) ?? []).map((r) => ({ id: r.id, name: r.name, level: r.level }));

  // A compact working header rather than PageShell's display heading: the
  // workspace should open on evidence and questions, not on a title block.
  // The brief (Overview) carries the region's description.
  return (
    <div className="max-w-page mx-auto px-[clamp(1.25rem,3vw,2.5rem)] pt-28 pb-20">
      <header className="mb-5 flex flex-col gap-5">
        <RegionBreadcrumb path={path} currentId={regionId} />
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1">
            <h1 className="display truncate pb-1 text-[clamp(1.75rem,2.6vw,2.5rem)] leading-[1.15] text-ink">{name}</h1>
            <div className="mt-2 font-sans text-sm text-muted">
              {loading && !detail ? <Skeleton width="16rem" /> : (
                <>
                  {noteCount} document{noteCount === 1 ? "" : "s"} · {sourceCount} source{sourceCount === 1 ? "" : "s"}
                  {touched ? ` · Updated ${relativeTime(touched)}` : ""}
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => setMapOpen(true)} className="gap-2">
              <MapIcon size={15} strokeWidth={1.75} aria-hidden />
              Open map
            </Button>
            <Button onClick={ctx.askRegion} className="gap-2">
              <Sparkles size={15} strokeWidth={1.75} aria-hidden />
              Ask region
            </Button>
          </div>
        </div>
      </header>
      <nav className="mb-6 flex items-center gap-1 border-b border-hair" aria-label="Workspace sections">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              cn(
                "relative -mb-px px-4 py-2.5 font-sans uppercase tracking-eyebrow text-[11px] transition-colors",
                "focus:outline-none focus-visible:!shadow-none focus-visible:!rounded-none",
                isActive ? "border-b-2 border-magenta text-ink" : "border-b-2 border-transparent text-muted hover:text-ink",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet context={ctx} />
      <RegionMapDialog regionId={regionId} regionName={name} open={mapOpen} onOpenChange={setMapOpen} />
    </div>
  );
}

function MovedRedirect({ to }: { to: string }) {
  useEffect(() => {
    toastInfo("This region was reshaped by a recompile — showing its current workspace.");
  }, []);
  return <Navigate to={`/regions/${encodeURIComponent(to)}`} replace />;
}

/** A region the last compile no longer has: its memory and conversations are
 *  kept, and the user can move them onto a current region. */
export function UnassignedRegionPage({ regionKey, regionName }: { regionKey: string; regionName: string }) {
  const navigate = useNavigate();
  const q = useUnassignedRegion(regionKey);
  const reassign = useReassignUnassigned(regionKey);
  const del = useDeleteMemory();
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const name = q.data?.region_name ?? regionName ?? "Unassigned region";

  return (
    <PageShell
      eyebrow="Unassigned region"
      title={name}
      description="This region no longer exists in the current map. The memory and conversations saved here are kept — move them onto a region that still does."
      actions={
        <RegionSwitcher
          currentId={null}
          label="Move everything to…"
          onPick={(id) =>
            reassign.mutate(id, {
              onSuccess: (r) => {
                toastSuccess(`Moved ${r.moved_memory} memory item${r.moved_memory === 1 ? "" : "s"} and ${r.moved_threads} conversation${r.moved_threads === 1 ? "" : "s"}.`);
                navigate(`/regions/${encodeURIComponent(r.region_id)}/memory`, { replace: true });
              },
              onError: (e) => toastError(e instanceof Error ? e.message : "Could not move."),
            })
          }
        />
      }
    >
      {q.isLoading ? (
        <div className="space-y-3"><Skeleton width="50%" /><Skeleton width="80%" /></div>
      ) : q.isError ? (
        <ErrorState title="Couldn't load this region's memory" onRetry={() => void q.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-hair bg-bone/40 px-5 py-4">
            <p className="eyebrow">Memory · {q.data?.items.length ?? 0}</p>
            {q.data && q.data.items.length > 0 ? (
              <ul className="divide-y divide-hair/70">
                {q.data.items.map((m) => (
                  <MemoryItemRow key={m.id} item={m} onEdit={setEditing} onDelete={(it) => del.mutate(it.id)} />
                ))}
              </ul>
            ) : <p className="mt-2 font-sans text-sm text-muted">Nothing saved here.</p>}
          </section>
          <section className="rounded-2xl border border-hair bg-bone/40 px-5 py-4">
            <p className="eyebrow">Conversations · {q.data?.threads.length ?? 0}</p>
            {q.data && q.data.threads.length > 0 ? (
              <ul className="divide-y divide-hair/70">
                {q.data.threads.map((t) => (
                  <li key={t.id}>
                    <button type="button" onClick={() => void resumeThread(t.id)} className="flex w-full items-center gap-3 py-2.5 text-left hover:text-magenta">
                      <span className="min-w-0 flex-1 truncate font-sans text-sm text-ink">{t.title}</span>
                      <span className="font-sans text-xs text-muted">{t.message_count} msgs · {relativeTime(t.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 font-sans text-sm text-muted">No conversations here.</p>}
          </section>
        </div>
      )}
      <MemoryEditDialog item={editing} onClose={() => setEditing(null)} />
    </PageShell>
  );
}

/** /regions/unassigned/:regionKey — route wrapper around the page above. */
export function UnassignedRegionRoute() {
  const { regionKey = "" } = useParams();
  return <UnassignedRegionPage regionKey={regionKey} regionName="" />;
}
