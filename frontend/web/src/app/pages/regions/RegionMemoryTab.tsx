import { useMemo, useState } from "react";
import { Bookmark } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { MemoryEditDialog } from "../../components/regions/MemoryEditDialog";
import { MemoryItemRow } from "../../components/regions/MemoryItemRow";
import { RegionSwitcher } from "../../components/regions/RegionSwitcher";
import { useDeleteMemory, useRegionMemory, useUpdateMemory, type MemoryItem } from "../../api/regions";
import { useMapDataReady } from "../../data/MapDataProvider";
import { groupMemoryBySubregion } from "../../lib/regions";
import { toastError, toastSuccess } from "../../lib/toast";
import { useRegionWorkspaceContext } from "./useRegionWorkspace";

export function RegionMemoryTab() {
  const { regionId, askRegion } = useRegionWorkspaceContext();
  const { indexes } = useMapDataReady();
  const q = useRegionMemory(regionId);
  const del = useDeleteMemory();
  const move = useUpdateMemory();
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [deleting, setDeleting] = useState<MemoryItem | null>(null);
  const [moving, setMoving] = useState<MemoryItem | null>(null);

  const sections = useMemo(
    () => groupMemoryBySubregion(q.data?.groups ?? [], regionId, indexes.childrenByRegionId, indexes.regionPathById),
    [q.data, regionId, indexes],
  );
  const total = sections.reduce((n, s) => n + s.items.length, 0);

  if (q.isLoading) return <div className="space-y-3"><Skeleton width="40%" /><Skeleton width="85%" /><Skeleton width="70%" /></div>;
  if (q.isError) return <ErrorState title="Couldn't load memory" onRetry={() => void q.refetch()} />;

  return (
    <div className="flex flex-col gap-6">
      {total === 0 ? (
        <EmptyState
          icon={<Bookmark size={28} strokeWidth={1.5} />}
          title="Nothing in memory yet"
          description="Ask this region a question, then save the answer — or a highlighted part of it — and it will be kept here and folded into future answers."
          action={<Button onClick={askRegion}>Ask region</Button>}
        />
      ) : (
        sections.map((s) =>
          s.items.length === 0 && !s.isSelf ? null : (
            <section key={s.id} className="rounded-2xl border border-hair bg-bone/40 px-5 py-4">
              <p className="eyebrow">{s.title} · {s.items.length}</p>
              {s.items.length === 0 ? (
                <p className="mt-2 font-sans text-sm text-muted">Nothing saved directly in this region — the sections below roll up from its sub-regions.</p>
              ) : (
                <ul className="divide-y divide-hair/70">
                  {s.items.map((m) => (
                    <MemoryItemRow key={m.id} item={m} onEdit={setEditing} onDelete={setDeleting} onMove={setMoving} showRegion={!s.isSelf && m.region_id !== s.id} />
                  ))}
                </ul>
              )}
            </section>
          ),
        )
      )}
      <MemoryEditDialog item={editing} onClose={() => setEditing(null)} />
      <AlertDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this memory?"
        description={deleting ? `“${deleting.title}” will be removed.` : undefined}
        confirmLabel="Delete"
        tone="destructive"
        confirming={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: (e) => toastError(e instanceof Error ? e.message : "Could not delete.") })}
      />
      <AlertDialog
        open={moving !== null}
        onOpenChange={(o) => !o && setMoving(null)}
        title="Move to another region"
        description={moving ? `Choose where “${moving.title}” should live.` : undefined}
        confirmLabel="Close"
        onConfirm={() => setMoving(null)}
      >
        <div className="mt-4">
          <RegionSwitcher
            currentId={moving?.region_id ?? null}
            onPick={(id) => {
              if (!moving) return;
              move.mutate({ id: moving.id, region_id: id }, {
                onSuccess: (item) => { toastSuccess(`Moved to ${item.region_name ?? "the region"}.`); setMoving(null); },
                onError: (e) => toastError(e instanceof Error ? e.message : "Could not move."),
              });
            }}
          />
        </div>
      </AlertDialog>
    </div>
  );
}
