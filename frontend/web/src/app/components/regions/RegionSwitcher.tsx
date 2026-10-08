import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import { ChevronDown, Search } from "lucide-react";
import { Popover } from "../ui/Popover";
import { useMapDataReady } from "../../data/MapDataProvider";
import { cn } from "../../lib/cn";
import { computeSiblingInfo, regionShadeHex } from "../../../knowledgeMap/util/regionShade";

/**
 * The workspace's region dropdown: every region in the map, indented by
 * level, filterable. Picking one navigates to its workspace (or calls
 * `onPick` when used as a plain picker, e.g. "Move to…").
 */
export function RegionSwitcher({
  currentId,
  label,
  onPick,
  className,
}: {
  currentId: string | null;
  label?: string;
  onPick?: (regionId: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { renderData, indexes } = useMapDataReady();
  const rows = useMemo(() => {
    const sib = computeSiblingInfo(renderData.regions);
    const out: { id: string; name: string; level: number; color: string; path: string }[] = [];
    const walk = (parentIdx: number) => {
      renderData.regions.forEach((r, i) => {
        if (r.parentIdx !== parentIdx) return;
        out.push({
          id: r.id,
          name: r.name,
          level: r.level,
          color: regionShadeHex(r.color, sib.depth[i], sib.siblingIdx[i], sib.siblingCount[i]),
          path: (indexes.regionPathById.get(r.id) ?? []).map((p) => p.name).join(" › "),
        });
        walk(i);
      });
    };
    walk(-1);
    return out;
  }, [renderData.regions, indexes.regionPathById]);
  const current = currentId ? indexes.regionsById.get(currentId) : null;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      side="bottom"
      align="start"
      className="p-0"
      trigger={
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          className={cn(
            "inline-flex max-w-[320px] items-center gap-2 rounded-full border border-hair bg-cream px-3 py-1.5 font-sans text-sm text-ink transition-colors hover:bg-bone/60",
            open && "bg-bone/60",
            className,
          )}
        >
          <span className="truncate">{label ?? current?.name ?? "Choose a region"}</span>
          <ChevronDown size={14} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
        </button>
      }
    >
      <Command label="Regions" className="w-[360px]">
        <div className="flex items-center gap-2 border-b border-hair px-3 py-2">
          <Search size={14} strokeWidth={1.5} className="text-muted" aria-hidden />
          <Command.Input autoFocus placeholder="Find a region…" className="w-full bg-transparent font-sans text-sm outline-none placeholder:text-muted" />
        </div>
        <Command.List className="max-h-80 overflow-y-auto p-1">
          <Command.Empty className="px-3 py-4 font-sans text-sm text-muted">No region matches.</Command.Empty>
          {rows.map((r) => (
            <Command.Item
              key={r.id}
              value={`${r.name} ${r.path}`}
              onSelect={() => {
                setOpen(false);
                if (onPick) onPick(r.id);
                else navigate(`/regions/${encodeURIComponent(r.id)}`);
              }}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 font-sans text-sm text-ink aria-selected:bg-bone/70",
                r.id === currentId && "text-magenta",
              )}
              style={{ paddingLeft: 8 + r.level * 14 }}
            >
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: r.color }} aria-hidden />
              <span className="truncate">{r.name}</span>
            </Command.Item>
          ))}
        </Command.List>
      </Command>
    </Popover>
  );
}
