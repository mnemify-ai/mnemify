import { useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { Dialog, DialogClose } from "../ui/Dialog";
import { useUpdateMemory, type MemoryItem } from "../../api/regions";
import { toastError } from "../../lib/toast";

export function MemoryEditDialog({ item, onClose }: { item: MemoryItem | null; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const update = useUpdateMemory();
  useEffect(() => {
    if (item) {
      setTitle(item.title);
      setBody(item.body);
    }
  }, [item]);
  const save = async () => {
    if (!item || !title.trim() || !body.trim()) return;
    try {
      await update.mutateAsync({ id: item.id, title: title.trim(), body: body.trim() });
      onClose();
    } catch (e) {
      toastError(e instanceof Error ? e.message : "Could not save.");
    }
  };
  return (
    <Dialog open={item !== null} onOpenChange={(o) => !o && onClose()} ariaLabel="Edit memory" width="560px">
      <DialogClose onClose={onClose} />
      <div className="flex flex-col gap-4 overflow-y-auto p-7">
        <div>
          <p className="eyebrow mb-2">Edit memory</p>
          <h2 className="font-serif text-2xl text-ink">{item?.region_name ?? "Memory"}</h2>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-xs uppercase tracking-eyebrow text-muted">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className="rounded-lg border border-hair bg-cream px-3 py-2 font-sans text-sm text-ink outline-none focus:border-ink" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-xs uppercase tracking-eyebrow text-muted">What to remember</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={8} maxLength={20000} className="resize-y rounded-lg border border-hair bg-cream px-3 py-2 font-serif text-[15px] leading-relaxed text-ink outline-none focus:border-ink" />
        </label>
        <div className="mt-2 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={update.isPending}>Cancel</Button>
          <Button onClick={() => void save()} loading={update.isPending} disabled={!title.trim() || !body.trim()}>Save</Button>
        </div>
      </div>
    </Dialog>
  );
}
