import { X } from "lucide-react";
import { Pill } from "./ui/Pill";
import { sourceMeta } from "./SourceBadge";
import type { DocFilters } from "../lib/useDocFilters";
import { cn } from "../lib/cn";

interface FilterChipsProps {
  filters: DocFilters;
  setFilters: (next: Partial<DocFilters>) => void;
  onClear: () => void;
  className?: string;
}

interface ChipDescriptor {
  key: string;
  label: string;
  value: string;
  remove: () => void;
}

/**
 * Sticky row of removable chips shown above the DocTable whenever any
 * filter is active. Each chip is a single button so the whole surface is
 * keyboard-focusable; the ✕ icon is purely visual but cursor-pointer is
 * applied to the whole chip via the underlying <button>.
 */
export function FilterChips({ filters, setFilters, onClear, className }: FilterChipsProps) {
  const chips: ChipDescriptor[] = [];

  if (filters.search) {
    chips.push({
      key: "search",
      label: "Search",
      value: filters.search,
      remove: () => setFilters({ search: "" }),
    });
  }

  for (const src of filters.sources) {
    chips.push({
      key: `source:${src}`,
      label: "Source",
      value: sourceMeta(src).label,
      remove: () =>
        setFilters({ sources: filters.sources.filter((s) => s !== src) }),
    });
  }

  if (chips.length === 0) return null;

  return (
    <div
      className={cn(
        "sticky top-0 z-[1]",
        "flex flex-wrap items-center gap-1 px-3 py-2",
        "bg-cream border border-hair rounded-xl shadow-sm",
        className,
      )}
    >
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.remove}
          aria-label={`Remove ${chip.label.toLowerCase()} filter: ${chip.value}`}
          className="group"
        >
          <Pill className="px-3 py-1 text-sm text-ink transition-colors group-hover:bg-cream/70">
            <span className="font-sans">
              <span className="text-muted">{chip.label}:</span>{" "}
              <span className="text-ink">{chip.value}</span>
            </span>
            <X
              size={12}
              strokeWidth={2.5}
              className="text-muted group-hover:text-ink transition-colors"
              aria-hidden
            />
          </Pill>
        </button>
      ))}
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onClear();
        }}
        className="ml-2 font-sans text-xs text-muted hover:text-ink transition-colors duration-200"
      >
        Clear all
      </a>
    </div>
  );
}
