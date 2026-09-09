import { useMemo } from "react";
import { useMapDataReady } from "./MapDataProvider";
import type { Note } from "../../knowledgeMap/types";
import type { TagInfo } from "./types";

/** Convert `tag.ocr-accuracy` → "OCR Accuracy". */
export function tagIdToLabel(tagId: string): string {
  const slug = tagId.replace(/^tag\./, "");
  return slug
    .split(/[-_]+/)
    .map((part) => {
      // Keep all-caps acronyms (OCR, API, SQL, BIM) all caps if 4 chars or less and all letters.
      if (part.length <= 4 && /^[a-z]+$/.test(part) && /^(ocr|api|sql|bim|ml|ai|ui|ux|qa|csv|pdf|cli|sdk|jwt|oss|ios|cpu|gpu|ram|orm|jvm|rgb|svg|css|tcp|udp|dns|rss|seo|crm|erp|hr|kpi|okr|gtm|cto|cfo|coo|ceo)$/.test(part)) {
        return part.toUpperCase();
      }
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

export function useTagInfo(tagId: string | null | undefined): TagInfo | null {
  const data = useMapDataReady();
  return useMemo(() => {
    if (!tagId) return null;
    const { renderData, indexes } = data;
    const idx = indexes.tagIdToIdx.get(tagId);
    if (idx === undefined) return null;
    const recencyScore = renderData.tagRecency[idx] ?? 0;
    const height = indexes.tagHeights.get(tagId) ?? 0;
    const leafRegion = indexes.regionByTagId.get(tagId) ?? null;
    const regionPath = leafRegion ? indexes.regionPathById.get(leafRegion.id) ?? [] : [];
    const topRegion = regionPath[0] ?? null;
    const frequency = indexes.notesByTagId.get(tagId)?.length ?? 0;

    const arcs = indexes.arcsByTagId.get(tagId) ?? [];
    const relatedTagIds = arcs.map((a) => (a.fromTagId === tagId ? a.toTagId : a.fromTagId));
    const crossesInto: { tagId: string; regionName: string }[] = [];
    arcs.forEach((a) => {
      const other = a.fromTagId === tagId ? a.toTagId : a.fromTagId;
      const otherTop = indexes.topLevelRegionByTagId.get(other);
      if (otherTop && (!topRegion || otherTop.id !== topRegion.id)) {
        crossesInto.push({ tagId: other, regionName: otherTop.name });
      }
    });

    const isGod = renderData.highlights.godTagIds.includes(tagId);
    const isBridge = renderData.highlights.bridgeTagIds.includes(tagId);
    const isTrending = renderData.highlights.trendingTagIds.includes(tagId);

    return {
      id: tagId,
      label: indexes.tagLabelById.get(tagId) ?? tagIdToLabel(tagId),
      recencyScore,
      height,
      regionPath,
      topRegion,
      leafRegion,
      frequency,
      relatedTagIds,
      crossesInto,
      isGod,
      isBridge,
      isTrending,
    };
  }, [tagId, data]);
}

export function useNotesForTag(tagId: string | null | undefined): Note[] {
  const { indexes } = useMapDataReady();
  return useMemo(() => {
    if (!tagId) return [];
    return indexes.notesByTagId.get(tagId) ?? [];
  }, [tagId, indexes]);
}
