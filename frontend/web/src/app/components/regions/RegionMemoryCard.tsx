import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Bookmark } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { MemoryItemRow } from "./MemoryItemRow";
import { MemoryEditDialog } from "./MemoryEditDialog";
import { AlertDialog } from "../ui/AlertDialog";
import { Skeleton } from "../ui/Skeleton";
import { useDeleteMemory, type MemoryItem } from "../../api/regions";
import { toastError } from "../../lib/toast";

const MAX_ROWS = 3;

export function RegionMemoryCard({ regionId, items, loading, onAsk }: { regionId: string; items: MemoryItem[]; loading: boolean; onAsk: () => void }) {
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [deleting, setDeleting] = useState<MemoryItem | null>(null);
  const del = useDeleteMemory();
  return (
    <SectionCard
      title="Region memory"
      description="Key notes, insights and context you chose to keep."
      action={
        <Link to={`/regions/${encodeURIComponent(regionId)}/memory`} className="inline-flex items-center gap-1 text-magenta hover:underline underline-offset-4">
          View memory <ArrowRight size={14} strokeWidth={1.5} aria-hidden />
        </Link>
      }
    >
      {loading && items.length === 0 ? (
        <div className="space-y-2"><Skeleton width="60%" /><Skeleton width="90%" /></div>
      ) : items.length === 0 ? (
        <div className="font-sans text-sm text-muted">
          <p className="flex items-center gap-2"><Bookmark size={14} strokeWidth={1.5} aria-hidden /> Nothing saved yet.</p>
          <p className="mt-1">
            <button type="button" onClick={onAsk} className="text-magenta hover:underline underline-offset-4">Ask this region</button> and save an answer to start its memory.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-hair/70">
          {items.slice(0, MAX_ROWS).map((m) => (
            <MemoryItemRow key={m.id} item={m} compact showRegion={m.region_id !== regionId} onEdit={setEditing} onDelete={setDeleting} />
          ))}
        </ul>
      )}
      <MemoryEditDialog item={editing} onClose={() => setEditing(null)} />
      <AlertDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this memory?"
        description={deleting ? `“${deleting.title}” will be removed from the region's memory.` : undefined}
        confirmLabel="Delete"
        tone="destructive"
        confirming={del.isPending}
        onConfirm={() => {
          if (!deleting) return;
          del.mutate(deleting.id, {
            onSuccess: () => setDeleting(null),
            onError: (e) => toastError(e instanceof Error ? e.message : "Could not delete."),
          });
        }}
      />
    </SectionCard>
  );
}
