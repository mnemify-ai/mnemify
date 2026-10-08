import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionCard } from "./SectionCard";
import { SourceIcon } from "./SourceIcon";
import { Skeleton } from "../ui/Skeleton";
import { ChangePill, changeAttribution } from "../RecentChangesPanel";
import { sourceMeta } from "../SourceBadge";
import type { RegionChange, RegionChangesResponse } from "../../api/regions";
import { relativeTime } from "../../lib/relativeTime";

const MAX_ROWS = 5;

export function SinceLastVisitCard({
  data,
  loading,
  firstVisit,
}: {
  data: RegionChangesResponse | null | undefined;
  loading: boolean;
  firstVisit: boolean;
}) {
  const rows = data?.changes.slice(0, MAX_ROWS) ?? [];
  return (
    <SectionCard eyebrow={firstVisit ? "Since the last compile" : "Since your last visit"}>
      {loading && !data ? (
        <div className="space-y-3 py-1">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton variant="circle" size={32} />
              <div className="flex-1 space-y-1.5"><Skeleton width="55%" /><Skeleton width="35%" /></div>
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="font-sans text-sm text-muted">
          {firstVisit ? "Nothing changed here since the last compile." : "Nothing changed here since you last looked."}
        </p>
      ) : (
        <ul className="divide-y divide-hair/70">
          {rows.map((c) => <ChangeRow key={`${c.source}:${c.source_id}`} change={c} />)}
        </ul>
      )}
      {data && data.changes.length > MAX_ROWS ? (
        <p className="mt-2 font-sans text-xs text-muted">
          <Link to="activity" className="text-magenta hover:underline underline-offset-4">
            {data.changes.length - MAX_ROWS} more in Activity →
          </Link>
        </p>
      ) : null}
    </SectionCard>
  );
}

function ChangeRow({ change }: { change: RegionChange }) {
  const who = changeAttribution(change);
  const label = sourceMeta(change.source).label;
  const href = change.doc_id ? `/documents?id=${encodeURIComponent(change.doc_id)}` : null;
  const title = <span className="block truncate font-sans text-sm font-medium text-ink">{change.title}</span>;
  return (
    <li className="flex items-start gap-3 py-2.5">
      <SourceIcon source={change.source} size={28} />
      <div className="min-w-0 flex-1">
        {href ? <Link to={href} className="block hover:text-magenta">{title}</Link> : change.url ? (
          <a href={change.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-magenta">
            {title}<ExternalLink size={11} strokeWidth={1.5} className="shrink-0 text-muted" aria-hidden />
          </a>
        ) : title}
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 font-sans text-[11px] text-muted">
          <ChangePill change={change.change} />
          <span>{label} · {relativeTime(change.changed_at)}</span>
          {who ? <span>· {who}</span> : null}
        </div>
      </div>
    </li>
  );
}
