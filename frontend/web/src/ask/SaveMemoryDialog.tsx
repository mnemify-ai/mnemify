import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bookmark } from "lucide-react";
import { Button } from "../app/components/ui/Button";
import { Dialog, DialogClose } from "../app/components/ui/Dialog";
import { useCreateMemory, type MemoryKind, type MemoryOrigin } from "../app/api/regions";
import { toastError, toastSuccess } from "../app/lib/toast";
import type { Citation } from "./types";

export type SaveMemoryDraft = {
  regionId: string;
  regionName: string;
  title: string;
  body: string;
  kind: MemoryKind;
  citations: Citation[];
  sourceNoteIds: string[];
  origin: MemoryOrigin;
};

/**
 * "Save to memory" — promote a chat answer (or a highlighted span of one)
 * into the region's memory. The user can edit the title and body before it
 * lands; the citations the answer carried travel along untouched.
 */
export function SaveMemoryDialog({
  draft,
  onClose,
}: {
  draft: SaveMemoryDraft | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const create = useCreateMemory(draft?.regionId ?? "");

  useEffect(() => {
    if (draft) {
      setTitle(draft.title);
      setBody(draft.body);
    }
  }, [draft]);

  const submit = async () => {
    if (!draft) return;
    const t = title.trim();
    const b = body.trim();
    if (!t || !b) return;
    try {
      await create.mutateAsync({
        title: t,
        body: b,
        kind: draft.kind,
        citations: draft.citations,
        source_note_ids: draft.sourceNoteIds,
        origin: draft.origin,
      });
      toastSuccess(`Saved to ${draft.regionName} memory.`, {
        action: {
          label: "View memory",
          onClick: () => navigate(`/regions/${encodeURIComponent(draft.regionId)}/memory`),
        },
      });
      onClose();
    } catch (e) {
      toastError(e instanceof Error ? e.message : "Could not save to memory.");
    }
  };

  return (
    <Dialog open={draft !== null} onOpenChange={(o) => !o && onClose()} ariaLabel="Save to memory" width="560px">
      <DialogClose onClose={onClose} />
      <div className="p-7 flex flex-col gap-4 overflow-y-auto">
        <div>
          <p className="eyebrow mb-2 flex items-center gap-2">
            <Bookmark size={12} strokeWidth={1.75} aria-hidden />
            Save to memory
          </p>
          <h2 className="font-serif text-2xl text-ink">{draft?.regionName}</h2>
          <p className="font-sans text-sm text-muted mt-1">
            {draft?.kind === "selection"
              ? "Keep just the highlighted finding. Edit it however you like before saving."
              : "Keep this answer as something the region should remember. Edit it before saving."}
          </p>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-xs uppercase tracking-eyebrow text-muted">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            className="rounded-lg border border-hair bg-cream px-3 py-2 font-sans text-sm text-ink outline-none focus:border-ink"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-xs uppercase tracking-eyebrow text-muted">What to remember</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={8}
            maxLength={20000}
            className="rounded-lg border border-hair bg-cream px-3 py-2 font-serif text-[15px] leading-relaxed text-ink outline-none focus:border-ink resize-y"
          />
        </label>
        {draft && draft.citations.length > 0 ? (
          <p className="font-sans text-xs text-muted">
            {draft.citations.length} source citation{draft.citations.length === 1 ? "" : "s"} will be kept with it.
          </p>
        ) : null}
        <div className="flex items-center justify-end gap-2 mt-2">
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>Cancel</Button>
          <Button onClick={() => void submit()} loading={create.isPending} disabled={!title.trim() || !body.trim()}>
            Save to memory
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
