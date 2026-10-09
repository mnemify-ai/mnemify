import { useState } from "react";
import { Bookmark, MoreHorizontal, Pencil, Trash2, TextQuote } from "lucide-react";
import { Popover } from "../ui/Popover";
import type { MemoryItem } from "../../api/regions";
import { relativeTime } from "../../lib/relativeTime";
import { cn } from "../../lib/cn";

export function MemoryItemRow({
  item,
  onEdit,
  onDelete,
  onMove,
  compact,
  showRegion,
}: {
  item: MemoryItem;
  onEdit: (item: MemoryItem) => void;
  onDelete: (item: MemoryItem) => void;
  onMove?: (item: MemoryItem) => void;
  compact?: boolean;
  showRegion?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const Icon = item.kind === "selection" ? TextQuote : Bookmark;
  const from = item.origin?.label ? `From ${item.origin.label}` : item.kind === "selection" ? "From a highlighted answer" : "From an answer";
  return (
    <li className="flex items-start gap-3 py-3">
      <span className="mt-0.5 inline-grid h-9 w-9 shrink-0 place-items-center rounded-full bg-magenta/10 text-magenta">
        <Icon size={15} strokeWidth={1.75} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-sans text-sm font-semibold leading-snug text-ink">{item.title}</p>
        <p className={cn("mt-1 whitespace-pre-wrap font-sans text-sm leading-relaxed text-muted", compact && "line-clamp-3")}>{item.body}</p>
        <p className="mt-1.5 font-sans text-[11px] text-muted">
          Saved {relativeTime(item.created_at)} · {from}
          {showRegion && item.region_name ? ` · ${item.region_name}` : ""}
        </p>
      </div>
      <Popover
        open={open}
        onOpenChange={setOpen}
        trigger={
          <button type="button" aria-label="Memory item actions" className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted hover:bg-bone hover:text-ink">
            <MoreHorizontal size={16} strokeWidth={1.75} />
          </button>
        }
      >
        <div className="w-44 py-1 font-sans text-sm">
          <button type="button" onClick={() => { setOpen(false); onEdit(item); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bone/60">
            <Pencil size={14} strokeWidth={1.5} aria-hidden /> Edit
          </button>
          {onMove ? (
            <button type="button" onClick={() => { setOpen(false); onMove(item); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bone/60">
              <Bookmark size={14} strokeWidth={1.5} aria-hidden /> Move to…
            </button>
          ) : null}
          <button type="button" onClick={() => { setOpen(false); onDelete(item); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-rose hover:bg-bone/60">
            <Trash2 size={14} strokeWidth={1.5} aria-hidden /> Delete
          </button>
        </div>
      </Popover>
    </li>
  );
}
