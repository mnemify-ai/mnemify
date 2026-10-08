import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Check, EyeOff, ListTodo, MoreHorizontal } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { Button } from "../ui/Button";
import { Pill } from "../ui/Pill";
import { Popover } from "../ui/Popover";
import { Skeleton } from "../ui/Skeleton";
import { useSetActionItemStatus, type ActionItemUserStatus } from "../../api/actionItems";
import type { RegionActionItem } from "../../api/regions";
import { cleanTitle, dueLabel } from "../../lib/actionItems";
import { toastError } from "../../lib/toast";

const MAX_ROWS = 5;

/** "Action items to review" — the subtree's open todos with the user's own
 *  verdict per item (checkbox = confirmed, kebab = dismiss). */
export function ActionItemsReviewCard({
  items,
  today,
  loading,
  onReviewEvidence,
}: {
  items: RegionActionItem[];
  today: string;
  loading: boolean;
  onReviewEvidence: (item: RegionActionItem) => void;
}) {
  const setStatus = useSetActionItemStatus();
  const [optimistic, setOptimistic] = useState<Record<string, ActionItemUserStatus>>({});
  const statusOf = (it: RegionActionItem) => optimistic[it.id] ?? it.user_status;
  const visible = items.filter((it) => statusOf(it) !== "dismissed");
  const unverified = visible.filter((it) => statusOf(it) === "unverified").length;

  const update = (it: RegionActionItem, status: ActionItemUserStatus) => {
    const before = statusOf(it);
    setOptimistic((o) => ({ ...o, [it.id]: status }));
    setStatus.mutate(
      { id: it.id, status },
      {
        onError: (e) => {
          setOptimistic((o) => ({ ...o, [it.id]: before }));
          toastError(e instanceof Error ? e.message : "Could not update the item.");
        },
      },
    );
  };

  return (
    <SectionCard
      eyebrow={
        <span className="inline-flex items-center gap-2">
          Action items to review
          {unverified > 0 ? (
            <span className="inline-grid h-5 min-w-[20px] place-items-center rounded-full bg-magenta px-1.5 font-sans text-[11px] font-semibold normal-case tracking-normal text-cream">
              {unverified}
            </span>
          ) : null}
        </span>
      }
      description="Extracted from sources. Current status needs confirmation."
      action={
        <Link to="/action-items" className="inline-flex items-center gap-1 text-magenta hover:underline underline-offset-4">
          View all action items <ArrowRight size={14} strokeWidth={1.5} aria-hidden />
        </Link>
      }
    >
      {loading && items.length === 0 ? (
        <div className="space-y-3"><Skeleton width="80%" /><Skeleton width="65%" /></div>
      ) : visible.length === 0 ? (
        <p className="flex items-center gap-2 font-sans text-sm text-muted">
          <ListTodo size={14} strokeWidth={1.5} aria-hidden /> Nothing left to review in this region.
        </p>
      ) : (
        <ul className="divide-y divide-hair/70">
          {visible.slice(0, MAX_ROWS).map((it) => {
            const status = statusOf(it);
            const due = dueLabel(it, today);
            return (
              <li key={it.id} className="flex items-center gap-3 py-3">
                <input
                  type="checkbox"
                  checked={status === "confirmed"}
                  onChange={(e) => update(it, e.target.checked ? "confirmed" : "unverified")}
                  aria-label={`Confirm: ${cleanTitle(it.title)}`}
                  className="h-4 w-4 shrink-0 cursor-pointer accent-magenta"
                />
                <div className="min-w-0 flex-1">
                  <p className="font-sans text-sm font-semibold leading-snug text-ink">{cleanTitle(it.title)}</p>
                  {it.summary ? <p className="mt-0.5 line-clamp-2 font-sans text-xs leading-relaxed text-muted">{it.summary}</p> : null}
                  {due || it.owner ? (
                    <p className="mt-0.5 font-sans text-[11px] text-muted">
                      {[due, it.owner ? `Owner: ${it.owner}` : null].filter(Boolean).join(" · ")}
                    </p>
                  ) : null}
                </div>
                <Pill tone={status === "confirmed" ? "success" : "warning"} dot className="shrink-0 px-2.5 py-1">
                  {status === "confirmed" ? "Confirmed" : "Status unverified"}
                </Pill>
                <Button variant="secondary" size="sm" onClick={() => onReviewEvidence(it)} className="shrink-0">
                  Review evidence
                </Button>
                <RowMenu
                  status={status}
                  onConfirm={() => update(it, status === "confirmed" ? "unverified" : "confirmed")}
                  onDismiss={() => update(it, "dismissed")}
                />
              </li>
            );
          })}
        </ul>
      )}
      {visible.length > MAX_ROWS ? (
        <p className="mt-2 font-sans text-xs text-muted">{visible.length - MAX_ROWS} more on the TODOs page.</p>
      ) : null}
    </SectionCard>
  );
}

function RowMenu({ status, onConfirm, onDismiss }: { status: ActionItemUserStatus; onConfirm: () => void; onDismiss: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger={
        <button type="button" aria-label="More actions" className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted hover:bg-bone hover:text-ink">
          <MoreHorizontal size={16} strokeWidth={1.75} />
        </button>
      }
    >
      <div className="w-48 py-1 font-sans text-sm">
        <button type="button" onClick={() => { onConfirm(); setOpen(false); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bone/60">
          <Check size={14} strokeWidth={1.5} aria-hidden /> {status === "confirmed" ? "Mark unverified" : "Mark confirmed"}
        </button>
        <button type="button" onClick={() => { onDismiss(); setOpen(false); }} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bone/60">
          <EyeOff size={14} strokeWidth={1.5} aria-hidden /> Dismiss
        </button>
        <Link to="/action-items" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bone/60">
          <ListTodo size={14} strokeWidth={1.5} aria-hidden /> Open in TODOs
        </Link>
      </div>
    </Popover>
  );
}
