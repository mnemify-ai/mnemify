import { useState } from "react";
import { ActionItemsReviewCard } from "../../components/regions/ActionItemsReviewCard";
import { EvidenceDrawer, type EvidenceTarget } from "../../components/regions/EvidenceDrawer";
import { PendingDocumentsBanner } from "../../components/regions/PendingDocumentsBanner";
import { RegionBriefCard } from "../../components/regions/RegionBriefCard";
import { RegionMemoryCard } from "../../components/regions/RegionMemoryCard";
import { RegionSourcesCard } from "../../components/regions/RegionSourcesCard";
import { SignalCard } from "../../components/regions/SignalCard";
import { SinceLastVisitCard } from "../../components/regions/SinceLastVisitCard";
import { SubRegionStrip } from "../../components/regions/SubRegionStrip";
import { useRegionChanges, type RegionActionItem, type RegionSignal } from "../../api/regions";
import { useMapData } from "../../data/MapDataProvider";
import { sourcesBreakdown } from "../../lib/regions";
import { useRegionWorkspaceContext } from "./useRegionWorkspace";

/** The workspace's main view. Sub-regions span the top as the way down;
 *  evidence and questions own the wide column;
 *  the brief sits above them collapsed, and what changed, memory and
 *  sources ride the side column. The map is one click away ("Open map" in
 *  the header) rather than a preview taking space here. */
export function RegionOverviewTab() {
  const { regionId, detail, loading, colorFor, previousVisit, askRegion } = useRegionWorkspaceContext();
  const map = useMapData().data;
  const [evidence, setEvidence] = useState<EvidenceTarget | null>(null);

  // "Since your last visit" needs the visit call to answer first, so the
  // boundary is right the first time rather than refetching twice.
  const since = previousVisit === undefined ? null : previousVisit ?? "last_compile";
  const changes = useRegionChanges(regionId, since ?? "last_compile", { enabled: since !== null });

  const today = new Date().toISOString().slice(0, 10);
  const subtreeNotes = map?.indexes.notesByRegionSubtree.get(regionId) ?? [];
  const sources = detail?.sources ?? sourcesBreakdown(subtreeNotes);
  const fallbackSummary = map?.attention?.regions[regionId]?.summary ?? null;

  const openSignalEvidence = (s: RegionSignal) =>
    setEvidence({ docId: s.source_doc_id, noteId: s.source_note_id, excerpt: s.summary || s.title, regionId });
  const openItemEvidence = (it: RegionActionItem) =>
    setEvidence({ docId: it.source_doc_id, noteId: it.source_note_ids[0] ?? null, excerpt: it.summary || it.title, regionId });

  return (
    <div className="flex flex-col gap-6">
      <SubRegionStrip children={detail?.children ?? []} colorFor={colorFor} />
      <PendingDocumentsBanner regionId={regionId} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="flex min-w-0 flex-col gap-6">
          <RegionBriefCard regionId={regionId} brief={detail?.brief} loading={loading} fallbackSummary={fallbackSummary} />
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <SignalCard kind="decision" title="Decisions" items={detail?.decisions.items ?? []} total={detail?.decisions.total ?? 0} loading={loading} onOpenEvidence={openSignalEvidence} />
            <SignalCard kind="open_question" title="Open questions" items={detail?.open_questions.items ?? []} total={detail?.open_questions.total ?? 0} loading={loading} onOpenEvidence={openSignalEvidence} />
          </div>
          <ActionItemsReviewCard items={detail?.action_items.items ?? []} today={today} loading={loading} onReviewEvidence={openItemEvidence} />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <SinceLastVisitCard data={changes.data} loading={changes.isLoading || since === null} firstVisit={previousVisit === null} />
          <RegionMemoryCard regionId={regionId} items={detail?.memory_preview ?? []} loading={loading} onAsk={askRegion} />
          <RegionSourcesCard sources={sources} />
        </div>
      </div>
      <EvidenceDrawer target={evidence} onClose={() => setEvidence(null)} />
    </div>
  );
}
