import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import type { RegionCard } from "../../api/regions";
import { firstSentence } from "../../../knowledgeMap/chrome/RegionHoverPreview";
import { levelColor } from "../../../knowledgeMap/chrome/panelShared";

/** Horizontal strip of child regions — every level is a workspace, so this
 *  is how you go down. Cards share the full width; past ~240px each the
 *  strip scrolls sideways instead of squeezing them. */
export function SubRegionStrip({ children, colorFor }: { children: RegionCard[]; colorFor: (id: string) => string }) {
  if (children.length === 0) return null;
  return (
    <section aria-label="Sub-regions">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="eyebrow">Sub-regions · {children.length}</p>
        <span className="font-sans text-xs text-muted">Open one to work inside it</span>
      </div>
      <div className="-mx-1 grid auto-cols-[minmax(240px,1fr)] grid-flow-col gap-3 overflow-x-auto px-1 pb-2">
        {children.map((c) => (
          <Link
            key={c.id}
            to={`/regions/${encodeURIComponent(c.id)}`}
            className="group flex min-w-0 flex-col gap-1.5 rounded-xl border border-hair bg-cream/70 p-3 transition-colors hover:border-magenta/40 hover:bg-bone/60"
          >
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: colorFor(c.id) }} aria-hidden />
              <span className="truncate font-sans text-sm font-semibold text-ink group-hover:text-magenta">{c.name}</span>
              {c.attention.level && c.attention.level !== "none" ? (
                <span className="ml-auto h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: levelColor(c.attention.level) }} title={`Attention: ${c.attention.level}`} />
              ) : null}
              <ChevronRight size={14} strokeWidth={1.5} className="shrink-0 text-muted" aria-hidden />
            </div>
            {c.summary ? <p className="line-clamp-2 font-sans text-xs leading-snug text-muted">{firstSentence(c.summary)}</p> : null}
            <p className="mt-auto font-sans text-[11px] text-muted">
              {c.note_count} doc{c.note_count === 1 ? "" : "s"}
              {c.children.length ? ` · ${c.children.length} sub-region${c.children.length === 1 ? "" : "s"}` : ""}
              {c.memory_count ? ` · ${c.memory_count} in memory` : ""}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
