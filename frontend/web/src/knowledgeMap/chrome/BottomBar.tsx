// Permanent bottom bar below the 3D canvas: corpus + map stats on the left, a
// compact per-source harvested-doc summary on the right. Lives in its own grid
// row so drei <Html> tag labels can't overlap it.

import { StatsPanel } from './StatsPanel';
import { useConnections } from '../../app/api/connections';
import { useDocumentStats } from '../../app/api/documents';
import { useTerrainReport } from '../../app/api/terrain';
import { relativeTime } from '../../app/lib/relativeTime';
import { sourceMeta } from '../../app/components/SourceBadge';
import type { RenderData } from '../types';

export function BottomBar({ data }: { data: RenderData }) {
  return (
    <div className="flex items-center gap-[22px] px-6 py-3 border-t border-line/[0.18] bg-cream shrink-0">
      {/* Trust line: how much knowledge is here + how fresh. The cartography
          counts (StatsPanel) describe the map's structure; this describes the
          underlying corpus, which nothing else on the map surfaces. Desktop
          only — the bar is too cramped on phones, where provenance is reachable
          via the Sources drawer instead. */}
      <KnowledgeSummary />
      <span className="hidden sm:block w-px self-stretch bg-line/20" aria-hidden />
      <StatsPanel data={data} />
      <div className="flex-1" />
      <SourcesStrip />
    </div>
  );
}

function KnowledgeSummary() {
  const stats = useDocumentStats();
  const report = useTerrainReport();
  const totalDocs = stats.data?.total_documents ?? null;
  const sourceCount = stats.data?.sources_connected ?? null;
  const compiledAt = report.data?.generated_at ?? null;
  if (totalDocs === null) return null;
  const docLabel = `${totalDocs.toLocaleString()} doc${totalDocs === 1 ? '' : 's'}`;
  const srcLabel =
    sourceCount !== null && sourceCount > 0
      ? `${sourceCount} source${sourceCount === 1 ? '' : 's'}`
      : null;
  const freshLabel = compiledAt ? `refreshed ${relativeTime(compiledAt)}` : null;
  // SR-friendly single label; the visible pieces are split for styling.
  const aria = ['Knowledge map:', docLabel, srcLabel, freshLabel]
    .filter(Boolean)
    .join(' ');
  return (
    <div
      className="hidden sm:flex items-baseline gap-2 font-serif text-[13px] whitespace-nowrap"
      aria-label={aria}
    >
      <span className="font-medium text-ink" aria-hidden>{docLabel}</span>
      {srcLabel && (
        <>
          <span className="text-muted/60" aria-hidden>·</span>
          <span className="text-muted" aria-hidden>{srcLabel}</span>
        </>
      )}
      {freshLabel && (
        <>
          <span className="text-muted/60" aria-hidden>·</span>
          <span className="text-muted" aria-hidden>{freshLabel}</span>
        </>
      )}
    </div>
  );
}

function SourcesStrip() {
  const connections = useConnections();
  const connected = (connections.data ?? []).filter((c) => c.status === 'connected');
  if (connected.length === 0) return null;
  return (
    <div
      className="flex items-center gap-[18px] font-[ui-serif,Georgia,'Times_New_Roman',serif] text-[11px] text-ink/80"
      aria-label="Harvested sources"
    >
      {connected.map((c) => (
        <span key={c.source} className="inline-flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full inline-block ${sourceMeta(c.source).dotClass}`} />
          {sourceMeta(c.source).label}
          <span className="text-muted">{c.doc_count} docs</span>
        </span>
      ))}
    </div>
  );
}
