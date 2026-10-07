import { create } from "zustand";

/**
 * The map's timeline cutoff, mirrored out of the per-mount KnowledgeMap store
 * so the Ask dock (which lives outside the map) can ask "as of" that date.
 * Written only by `useTimelineSync` while the scrubber is open; `null` means
 * the map shows the present and questions are asked normally.
 */
type MapTimelineState = {
  /** Epoch ms of the scrubber position, or null when it is closed. */
  asOf: number | null;
  setAsOf: (ms: number | null) => void;
};

export const useMapTimelineStore = create<MapTimelineState>((set) => ({
  asOf: null,
  setAsOf: (asOf) => set((s) => (s.asOf === asOf ? {} : { asOf })),
}));

/** `YYYY-MM-DD` for the wire (`as_of` on POST /api/ask), in UTC so the
 *  backend's end-of-day cutoff matches what the slider showed. */
export function asOfWireDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}
