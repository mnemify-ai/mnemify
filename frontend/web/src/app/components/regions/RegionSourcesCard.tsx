import { Link } from "react-router-dom";
import { ArrowRight, ChevronRight } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { SourceIcon } from "./SourceIcon";
import { sourceMeta } from "../SourceBadge";
import type { RegionSource } from "../../api/regions";

const DESCRIPTIONS: Record<string, string> = {
  confluence: "Pages, specs and meeting docs",
  notion: "Pages, databases and notes",
  localfiles: "Files from folders on this computer",
  obsidian: "Vault notes and links",
};

export function RegionSourcesCard({ sources }: { sources: RegionSource[] }) {
  return (
    <SectionCard
      title="Sources"
      description="Documents in this region, by source."
      action={
        <Link to="/build/sources" className="inline-flex items-center gap-1 text-magenta hover:underline underline-offset-4">
          Manage sources <ArrowRight size={14} strokeWidth={1.5} aria-hidden />
        </Link>
      }
    >
      {sources.length === 0 ? (
        <p className="font-sans text-sm text-muted">No documents land in this region yet.</p>
      ) : (
        <ul className="divide-y divide-hair/70">
          {sources.map((s) => (
            <li key={s.source}>
              <Link to={`/documents?source=${encodeURIComponent(s.source)}`} className="group flex items-center gap-3 py-3">
                <SourceIcon source={s.source} />
                <div className="min-w-0 flex-1">
                  <p className="font-sans text-sm font-semibold text-ink group-hover:text-magenta">{sourceMeta(s.source).label}</p>
                  <p className="font-sans text-xs text-muted">{DESCRIPTIONS[s.source] ?? `${s.count} notes in this region`}</p>
                </div>
                <span className="font-sans text-sm tabular-nums text-ink">{s.count}</span>
                <ChevronRight size={16} strokeWidth={1.5} className="text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
