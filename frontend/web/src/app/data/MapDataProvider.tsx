import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AttentionFile, RenderData, NotesFile } from "../../knowledgeMap/types";
import { apiUrl } from "../api/client";
import { qk } from "../api/keys";
import { buildIndexes } from "./indexes";
import type { MapIndexes } from "./types";

// The 3D map's data is now the *compiled* terrain — no baked demo.
const RENDER_DATA_URL = "/api/terrain/render-data";
const NOTES_URL = "/api/terrain/notes";
const ATTENTION_URL = "/api/terrain/attention";
const SUPPORTED_RENDER_VERSION = 3;

interface MapData {
  renderData: RenderData;
  notes: NotesFile;
  attention: AttentionFile | null;
  indexes: MapIndexes;
}

interface MapDataState {
  data: MapData | null;
  /** True once the fetch succeeded but there's no compiled map yet (404). */
  empty: boolean;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

const MapDataContext = createContext<MapDataState | null>(null);

const EMPTY_NOTES: NotesFile = { version: 2, generatedAt: null, notes: [] } as unknown as NotesFile;

export function MapDataProvider({ children }: { children: ReactNode }) {
  const query = useQuery<MapData | null>({
    queryKey: qk.mapData(),
    staleTime: Infinity,
    gcTime: Infinity,
    // External .mnemify/ wipes (e.g. `rm -rf` outside the app) leave
    // the cache stale. Refetch on window focus so coming back to the tab
    // catches a vanished render-data.json and flips to the empty state.
    refetchOnWindowFocus: true,
    queryFn: async (): Promise<MapData | null> => {
      const renderRes = await fetch(apiUrl(RENDER_DATA_URL));
      if (renderRes.status === 404) return null; // no compiled map yet
      if (!renderRes.ok) throw new Error(`HTTP ${renderRes.status} fetching render-data`);
      const renderData = (await renderRes.json()) as RenderData;
      if (renderData.version !== SUPPORTED_RENDER_VERSION) {
        throw new Error(
          `Unsupported render-data version ${renderData.version} (expected ${SUPPORTED_RENDER_VERSION})`,
        );
      }
      // Notes are written alongside render-data by the compiler; tolerate a miss.
      let notes: NotesFile = EMPTY_NOTES;
      try {
        const notesRes = await fetch(apiUrl(NOTES_URL));
        if (notesRes.ok) notes = (await notesRes.json()) as NotesFile;
      } catch {
        notes = EMPTY_NOTES;
      }
      let attention: AttentionFile | null = null;
      try {
        const attentionRes = await fetch(apiUrl(ATTENTION_URL));
        if (attentionRes.ok) attention = (await attentionRes.json()) as AttentionFile;
      } catch {
        attention = null;
      }
      return { renderData, notes, attention, indexes: buildIndexes(renderData, notes) };
    },
  });

  const value = useMemo<MapDataState>(
    () => ({
      data: query.data ?? null,
      empty: query.isSuccess && query.data === null,
      isLoading: query.isLoading,
      error: query.error as Error | null,
      refetch: () => void query.refetch(),
    }),
    [query.data, query.isSuccess, query.isLoading, query.error, query.refetch],
  );

  return <MapDataContext.Provider value={value}>{children}</MapDataContext.Provider>;
}

export function useMapData(): MapDataState {
  const ctx = useContext(MapDataContext);
  if (!ctx) throw new Error("useMapData must be used inside <MapDataProvider>");
  return ctx;
}

/** Throwing accessor — call inside components rendered only when data is ready. */
export function useMapDataReady(): MapData {
  const { data } = useMapData();
  if (!data) throw new Error("Map data not loaded yet");
  return data;
}
