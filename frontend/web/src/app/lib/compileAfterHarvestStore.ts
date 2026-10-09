import { create } from "zustand";
import type { CompileStartPayload } from "../api/terrain";

/**
 * "Harvest, then compile" (StaleHarvestNotice). The notice starts the harvest
 * and parks the compile here; CompileAfterHarvest (mounted once in
 * DashboardLayout) fires it when that harvest finishes, so the compile still
 * goes through `useStartCompile` — consent dialog, toasts and all — and the
 * chain survives the dialog closing or the user navigating away.
 */
type State = {
  /** The compile to run, or null when nothing is queued. */
  payload: CompileStartPayload | null;
  /** Epoch seconds when it was queued; only a harvest that finishes after
   *  this counts (the server's `finished_at` is in seconds too). */
  queuedAt: number | null;
  queue: (payload: CompileStartPayload) => void;
  clear: () => void;
};

export const useCompileAfterHarvest = create<State>((set) => ({
  payload: null,
  queuedAt: null,
  queue: (payload) => set({ payload, queuedAt: Date.now() / 1000 }),
  clear: () => set({ payload: null, queuedAt: null }),
}));
