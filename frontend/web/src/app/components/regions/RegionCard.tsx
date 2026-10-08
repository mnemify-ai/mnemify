import { Link } from "react-router-dom";
import { Bookmark, ChevronRight, FileText } from "lucide-react";
import type { RegionCard as RegionCardData } from "../../api/regions";
import { relativeTime } from "../../lib/relativeTime";
import { firstSentence } from "../../../knowledgeMap/chrome/RegionHoverPreview";
import { toRoman } from "../../../knowledgeMap/util/roman";

/** One top-level region on the /regions index. */
export function RegionCard({
  region,
  numeral,
  color,
}: {
  region: RegionCardData;
  numeral: number | null;
  color: string;
}) {
  const sources = region.counts.sources ?? 0;
  return (
    <Link
      to={`/regions/${encodeURIComponent(region.id)}`}
      className="group flex flex-col gap-3 rounded-2xl border border-hair bg-bone/40 p-5 transition-colors hover:border-magenta/40 hover:bg-bone/70"
    >
      <div className="flex items-center gap-2.5">
        {numeral !== null ? (
          <span className="inline-grid h-[22px] min-w-[22px] place-items-center rounded-full border border-line/[0.35] bg-cream/60 px-[5px] font-serif text-[11px] italic font-semibold text-ink">
            {toRoman(numeral)}
          </span>
        ) : null}
        <span className="h-3 w-3 shrink-0 rounded-[3px]" style={{ background: color }} aria-hidden />
        <span className="font-serif text-xl leading-tight text-ink group-hover:text-magenta">{region.name}</span>
        <ChevronRight size={16} strokeWidth={1.5} className="ml-auto shrink-0 text-muted" aria-hidden />
      </div>
      {region.summary ? (
        <p className="font-sans text-sm leading-relaxed text-muted line-clamp-3">{firstSentence(region.summary)}</p>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 font-sans text-xs text-muted">
        <span className="inline-flex items-center gap-1">
          <FileText size={12} strokeWidth={1.5} aria-hidden />
          {region.note_count} document{region.note_count === 1 ? "" : "s"}
        </span>
        {sources ? <span>· {sources} source{sources === 1 ? "" : "s"}</span> : null}
        {region.children.length ? <span>· {region.children.length} sub-region{region.children.length === 1 ? "" : "s"}</span> : null}
        {region.memory_count ? (
          <span className="inline-flex items-center gap-1 text-magenta">
            <Bookmark size={12} strokeWidth={1.5} aria-hidden />
            {region.memory_count} in memory
          </span>
        ) : null}
        {region.last_touched_at ? <span className="ml-auto">Updated {relativeTime(region.last_touched_at)}</span> : null}
      </div>
    </Link>
  );
}
