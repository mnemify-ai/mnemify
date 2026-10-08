import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Compass, FolderOpen } from "lucide-react";
import { PageShell } from "../../layouts/PageShell";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { RegionCard } from "../../components/regions/RegionCard";
import { useRegionsIndex, type RegionCard as RegionCardData } from "../../api/regions";
import { useMapData } from "../../data/MapDataProvider";
import { useRegionColors } from "./useRegionWorkspace";

/** /regions — every top-level region as a workspace card. */
export function RegionsIndexPage() {
  const navigate = useNavigate();
  const map = useMapData();
  const index = useRegionsIndex();
  const colorFor = useRegionColors();

  // Order as the map numbers them (bake order of the top-level regions).
  const ordered = useMemo(() => {
    const cards = index.data?.regions ?? [];
    const roots = map.data?.renderData.regions.filter((r) => r.parentIdx === -1) ?? [];
    const pos = new Map(roots.map((r, i) => [r.id, i]));
    return [...cards].sort((a, b) => (pos.get(a.id) ?? 999) - (pos.get(b.id) ?? 999));
  }, [index.data, map.data]);
  const numeralFor = (card: RegionCardData) => {
    const roots = map.data?.renderData.regions.filter((r) => r.parentIdx === -1) ?? [];
    const i = roots.findIndex((r) => r.id === card.id);
    return i >= 0 ? i + 1 : null;
  };

  return (
    <PageShell
      eyebrow="Workspaces"
      title="Regions"
      description="Every area of your map has a workspace: a brief, what changed, decisions and open questions, and the memory you keep there."
    >
      {map.empty || index.data === null ? (
        <EmptyState
          icon={<Compass size={28} strokeWidth={1.5} />}
          title="No compiled map yet"
          description="Regions emerge when your documents are compiled into the map. Run a compile first."
          action={<Button onClick={() => navigate("/build/compile")}>Go to Compile</Button>}
        />
      ) : index.isError ? (
        <ErrorState title="Couldn't load regions" description={String((index.error as Error)?.message ?? "")} onRetry={() => void index.refetch()} />
      ) : index.isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} variant="block" height={168} />)}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {ordered.map((r) => (
              <RegionCard key={r.id} region={r} numeral={numeralFor(r)} color={colorFor(r.id)} />
            ))}
          </div>
          {index.data && index.data.unassigned.length > 0 ? (
            <details className="mt-8 rounded-2xl border border-hair bg-bone/30 px-5 py-4">
              <summary className="cursor-pointer font-sans text-sm text-muted">
                Unassigned ({index.data.unassigned.length}) — memory from regions the last compile no longer has
              </summary>
              <ul className="mt-3 divide-y divide-hair/70">
                {index.data.unassigned.map((u) => (
                  <li key={u.region_key} className="flex items-center gap-3 py-2.5">
                    <FolderOpen size={16} strokeWidth={1.5} className="text-muted" aria-hidden />
                    <Link to={`/regions/unassigned/${encodeURIComponent(u.region_key)}`} className="font-sans text-sm text-ink hover:text-magenta">
                      {u.region_name}
                    </Link>
                    <span className="ml-auto font-sans text-xs text-muted">
                      {u.memory_count} in memory · {u.thread_count} conversation{u.thread_count === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </PageShell>
  );
}
