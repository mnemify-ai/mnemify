import { Check, PanelLeftClose } from "lucide-react";
import { Link } from "react-router-dom";
import { sourceMeta } from "./SourceBadge";
import { useMapData } from "../data/MapDataProvider";
import type { DocFilters } from "../lib/useDocFilters";
import { cn } from "../lib/cn";

interface DocFiltersPanelProps {
  filters: DocFilters;
  setFilters: (next: Partial<DocFilters>) => void;
  onClear: () => void;
  activeCount: number;
  /** Doc count per source, from `GET /api/documents/stats`. */
  bySource: Record<string, number>;
  /**
   * When true, renders without the sticky aside layout — for use inside the
   * mobile filters sheet where sticky positioning conflicts with the drawer.
   */
  inSheet?: boolean;
  /** When provided, render a collapse button inline with the Filters title. */
  onCollapse?: () => void;
}

export function DocFiltersPanel({
  filters,
  setFilters,
  onClear,
  activeCount,
  bySource,
  inSheet = false,
  onCollapse,
}: DocFiltersPanelProps) {
  const sources = Object.entries(bySource).sort(([a], [b]) => a.localeCompare(b));

  function toggleSource(src: string) {
    const next = filters.sources.includes(src)
      ? filters.sources.filter((s) => s !== src)
      : [...filters.sources, src];
    setFilters({ sources: next });
  }

  return (
    <aside
      className={
        inSheet ? "space-y-7" : "space-y-7 sticky top-20 self-start"
      }
    >
      <header className="flex items-center justify-between gap-2">
        <p className="eyebrow">Filters</p>
        <div className="flex items-center gap-2">
          {activeCount > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="font-sans text-[11px] text-magenta hover:underline"
            >
              Clear all ({activeCount})
            </button>
          )}
          {onCollapse && (
            <button
              type="button"
              onClick={onCollapse}
              aria-label="Collapse filters"
              className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-bone/60 transition-colors"
            >
              <PanelLeftClose size={14} strokeWidth={1.5} aria-hidden />
            </button>
          )}
        </div>
      </header>

      <Group label="Search">
        <input
          type="search"
          placeholder="Title…"
          value={filters.search}
          onChange={(e) => setFilters({ search: e.target.value })}
          className="w-full px-3 py-2 rounded-lg bg-bone/60 border border-hair font-sans text-sm placeholder:text-muted/60 focus:outline-none focus:border-magenta/60"
        />
      </Group>

      <Group label="Source">
        {sources.length === 0 ? (
          <p className="font-sans text-xs text-muted">Nothing harvested yet.</p>
        ) : (
          <ul className="space-y-1">
            {sources.map(([src, count]) => {
              const meta = sourceMeta(src);
              const checked = filters.sources.includes(src);
              return (
                <li key={src}>
                  <button
                    type="button"
                    onClick={() => toggleSource(src)}
                    className={cn(
                      "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md transition-colors",
                      checked ? "bg-magenta/10" : "hover:bg-bone/60",
                    )}
                  >
                    <span
                      className={cn(
                        "h-3.5 w-3.5 rounded border flex items-center justify-center shrink-0",
                        checked ? "bg-magenta border-magenta" : "border-line/30",
                      )}
                      aria-hidden
                    >
                      {checked && <Check size={10} strokeWidth={3} className="text-cream" />}
                    </span>
                    <span className={cn("h-2 w-2 rounded-full", meta.dotClass)} aria-hidden />
                    <span className="font-sans text-sm text-ink flex-1 text-left">{meta.label}</span>
                    <span className="font-sans text-[11px] text-muted tabular-nums">
                      {count.toLocaleString()}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Group>

      <RegionTagFilterStatus />
    </aside>
  );
}

/**
 * Region + tag filtering is gated on a doc→tag mapping the backend doesn't
 * expose yet — `DocRow` has no tag fields, and notes are keyed by a hashed
 * `n-XXXX` id with no reverse map to harvested-doc ids. Until the backend
 * extends `/api/documents` with `primary_tag_id`/`tag_ids`, the panel shows
 * an honest status with one of three messages:
 *
 *   • Map not yet compiled  → "Run a compile to surface tag and region
 *     filters" + Compile link.
 *   • Compiled but data unwired (current state)  → "Tag and region filters
 *     need a backend mapping that's still on the way."
 *   • Eventually: real controls.
 *
 * This is intentionally smaller than the Tier 3 plan called for; the original
 * design assumed `DocRow` already carried tag ids, which it doesn't.
 * Tracked in `docs/BACKLOG.md` (see "Documents: expose tag mappings").
 */
function RegionTagFilterStatus() {
  const { data, empty } = useMapData();
  if (empty || !data) {
    return (
      <section className="rounded-lg border border-hair-strong bg-bone/40 px-3 py-3">
        <p className="font-sans text-[11px] text-muted leading-relaxed">
          Region &amp; tag filters appear once your map is compiled.{" "}
          <Link to="/build/compile" className="text-magenta hover:underline">
            Compile now →
          </Link>
        </p>
      </section>
    );
  }
  return (
    <section className="rounded-lg border border-hair-strong bg-bone/40 px-3 py-3">
      <p className="font-sans text-[11px] text-muted leading-relaxed">
        Tag and region filters land here next — they need a doc→tag mapping
        the backend doesn&rsquo;t expose yet. The compile already worked out
        the structure; you can{" "}
        <Link to="/?tag=" className="text-magenta hover:underline">
          interrogate tags on the map
        </Link>{" "}
        in the meantime.
      </p>
    </section>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <p className="font-sans text-[11px] uppercase tracking-eyebrow text-muted/80 mb-2">
        {label}
      </p>
      {children}
    </section>
  );
}
