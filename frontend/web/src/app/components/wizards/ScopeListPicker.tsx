import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Check, Database, FileText, Bookmark, Search, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";

export interface ScopeItem {
  id: string;
  title: string;
  subtitle?: string;
  kind?: string;
}

interface ScopeListPickerProps {
  items: ScopeItem[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  emptyMessage?: string;
  /** Max height of the scrollable list. Default 320px. */
  maxHeight?: number;
}

const ROW_HEIGHT = 48;

function kindIcon(kind: string | undefined): LucideIcon {
  if (kind === "database") return Database;
  if (kind === "space") return Bookmark;
  if (kind === "personal_space") return User;
  return FileText;
}

function kindLabel(kind: string | undefined): string | undefined {
  if (!kind) return undefined;
  if (kind === "personal_space") return "personal space";
  // Existing kinds ("space", "database", "page") are already user-friendly
  // as-is. Underscore-y new kinds get humanized here.
  return kind;
}

export function ScopeListPicker({
  items,
  selectedIds,
  onChange,
  emptyMessage = "Nothing to pick yet.",
  maxHeight = 320,
}: ScopeListPickerProps) {
  const [search, setSearch] = useState("");
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.title.toLowerCase().includes(q) ||
        (it.subtitle?.toLowerCase().includes(q) ?? false) ||
        it.id.toLowerCase().includes(q),
    );
  }, [items, search]);

  function toggle(id: string) {
    const next = new Set(selectedSet);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next]);
  }

  function selectAll() {
    onChange(filtered.map((it) => it.id));
  }
  function deselectAll() {
    onChange([]);
  }

  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="relative flex-1">
          <Search
            size={14}
            strokeWidth={1.5}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter…"
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-bone/60 border border-hair font-sans text-sm placeholder:text-muted/60 focus:outline-none focus:border-magenta/60"
          />
        </div>
        <div className="flex items-center gap-1 text-xs">
          <button
            type="button"
            onClick={selectAll}
            className="font-sans text-[11px] text-muted hover:text-magenta px-2 py-1 rounded"
          >
            Select all
          </button>
          <span className="text-muted/40" aria-hidden>·</span>
          <button
            type="button"
            onClick={deselectAll}
            className="font-sans text-[11px] text-muted hover:text-magenta px-2 py-1 rounded"
          >
            Deselect
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between font-sans text-[11px] text-muted mb-2">
        <span>
          {selectedSet.size.toLocaleString()} / {items.length.toLocaleString()} selected
        </span>
        {search && (
          <span className="tabular-nums">
            {filtered.length.toLocaleString()} matches
          </span>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="bg-bone/40 border border-hair rounded-xl py-12 text-center font-sans text-sm text-muted">
          {items.length === 0 ? emptyMessage : "No matches for that filter."}
        </div>
      ) : (
        <div
          ref={parentRef}
          className="bg-bone/40 border border-hair rounded-xl overflow-y-auto"
          style={{ maxHeight }}
        >
          <div
            style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}
          >
            {rowVirtualizer.getVirtualItems().map((vrow) => {
              const item = filtered[vrow.index];
              const Icon = kindIcon(item.kind);
              const checked = selectedSet.has(item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => toggle(item.id)}
                  className={cn(
                    "absolute top-0 left-0 w-full text-left flex items-center gap-3 px-3",
                    "border-b border-hair/40 hover:bg-cream/60 transition-colors",
                    checked && "bg-magenta/5",
                  )}
                  style={{
                    height: ROW_HEIGHT,
                    transform: `translateY(${vrow.start}px)`,
                  }}
                >
                  <span
                    className={cn(
                      "h-4 w-4 rounded border flex items-center justify-center shrink-0",
                      checked ? "bg-magenta border-magenta" : "border-line/30 bg-cream",
                    )}
                    aria-hidden
                  >
                    {checked && <Check size={11} strokeWidth={3} className="text-cream" />}
                  </span>
                  <Icon size={14} strokeWidth={1.5} className="text-muted shrink-0" aria-hidden />
                  <span className="flex-1 min-w-0">
                    <span className="block font-serif text-sm text-ink truncate">
                      {item.title}
                    </span>
                    {item.subtitle && (
                      <span className="block font-mono text-[10px] text-muted truncate mt-0.5">
                        {item.subtitle}
                      </span>
                    )}
                  </span>
                  {kindLabel(item.kind) && (
                    <span className="font-sans text-[10px] text-muted uppercase tracking-eyebrow shrink-0">
                      {kindLabel(item.kind)}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
