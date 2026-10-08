import { useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { recordVisit, useRegion, type RegionDetail } from "../../api/regions";
import { useMapData } from "../../data/MapDataProvider";
import type { RegionEntry } from "../../data/types";
import { useAskDockStore } from "../../../ask/askDockStore";
import { useAskThreadStore } from "../../../ask/askThreadStore";
import { recolorRegions } from "../../../knowledgeMap/util/regionColors";
import { computeSiblingInfo, regionShadeHex } from "../../../knowledgeMap/util/regionShade";

/** What the workspace layout hands its tabs through `<Outlet context>`. */
export type RegionWorkspaceContext = {
  regionId: string;
  detail: RegionDetail | null;
  loading: boolean;
  error: unknown;
  entry: RegionEntry | null;
  colorFor: (regionId: string) => string;
  numeral: number | null;
  /** `undefined` until the visit call answers; then the previous stamp or null. */
  previousVisit: string | null | undefined;
  askRegion: () => void;
};

export function useRegionWorkspaceContext(): RegionWorkspaceContext {
  return useOutletContext<RegionWorkspaceContext>();
}

/** Colours as the 3D map paints them (client-side recolour + sibling shade),
 *  so the workspace's swatches match what the user sees on the terrain. */
export function useRegionColors(): (regionId: string) => string {
  const data = useMapData().data;
  return useMemo(() => {
    if (!data) return () => "#9CA3AF";
    const recolored = recolorRegions(data.renderData);
    const sib = computeSiblingInfo(recolored.regions);
    const byId = new Map<string, string>();
    recolored.regions.forEach((r, i) => {
      byId.set(r.id, regionShadeHex(r.color, sib.depth[i], sib.siblingIdx[i], sib.siblingCount[i]));
    });
    return (id: string) => byId.get(id) ?? "#9CA3AF";
  }, [data]);
}

export function useRegionWorkspace(regionId: string): RegionWorkspaceContext {
  const map = useMapData().data;
  const query = useRegion(regionId);
  const colorFor = useRegionColors();
  const entry = map?.indexes.regionsById.get(regionId) ?? null;
  const numeral = useMemo(() => {
    if (!map || !entry || entry.parentIdx !== -1) return null;
    const roots = map.renderData.regions.filter((r) => r.parentIdx === -1);
    const i = roots.findIndex((r) => r.id === regionId);
    return i >= 0 ? i + 1 : null;
  }, [map, entry, regionId]);

  // One visit stamp per region mount (StrictMode double-invokes effects, so
  // guard on the id we last stamped rather than on mount alone).
  const [previousVisit, setPreviousVisit] = useState<string | null | undefined>(undefined);
  const stampedRef = useRef<string | null>(null);
  useEffect(() => {
    if (stampedRef.current === regionId) return;
    stampedRef.current = regionId;
    setPreviousVisit(undefined);
    let cancelled = false;
    recordVisit(regionId)
      .then((v) => {
        if (!cancelled) setPreviousVisit(v.previous_visited_at);
      })
      .catch(() => {
        if (!cancelled) setPreviousVisit(null);
      });
    return () => {
      cancelled = true;
    };
  }, [regionId]);

  const askRegion = () => {
    useAskThreadStore.getState().newThreadForRegion(regionId);
    useAskDockStore.getState().openDock();
  };

  return {
    regionId,
    detail: query.data ?? null,
    loading: query.isLoading,
    error: query.error,
    entry,
    colorFor,
    numeral,
    previousVisit,
    askRegion,
  };
}
