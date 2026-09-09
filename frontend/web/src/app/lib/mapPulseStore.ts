import { create } from "zustand";

/**
 * Which terrain regions the Ask agent is touching *right now*.
 *
 * While an answer streams, each `agent_step` event names the regions behind
 * the nodes it retrieved or explored. Mirroring those onto the 3D map turns
 * the terrain itself into the progress indicator — you watch the assistant
 * move across your knowledge instead of reading a list of tool calls.
 *
 * Module-level (like mapFocusStore) because the Ask dock lives in the app
 * shell, outside the route that renders the map, and unmounts when closed.
 * Pulses are transient and self-expiring, so nothing needs cleaning up when
 * a stream ends or the dock closes mid-answer.
 */

/** How long a single step's regions stay lit. Long enough to notice at a
 *  glance, short enough that a fast multi-step answer doesn't leave the whole
 *  terrain glowing. */
export const PULSE_TTL_MS = 6000;

/** region node id → epoch ms at which the pulse stops. */
export type PulseMap = Record<string, number>;

/** Add `ids` to `prev`, each expiring `ttl` from `now`. Re-pulsing a region
 *  already lit extends it. Returns `prev` unchanged when there's nothing to
 *  add, so subscribers don't re-render on empty steps. Pure. */
export function mergePulses(
  prev: PulseMap,
  ids: readonly string[] | undefined,
  now: number,
  ttl: number = PULSE_TTL_MS,
): PulseMap {
  if (!ids || ids.length === 0) return prev;
  const next = { ...prev };
  for (const id of ids) {
    if (id) next[id] = now + ttl;
  }
  return next;
}

/** Drop expired entries. Returns `prev` by identity when nothing expired —
 *  the prune timer fires repeatedly and must not churn state. Pure. */
export function prunePulses(prev: PulseMap, now: number): PulseMap {
  const live = Object.entries(prev).filter(([, expiresAt]) => expiresAt > now);
  if (live.length === Object.keys(prev).length) return prev;
  return Object.fromEntries(live);
}

/** Earliest expiry in the map, or null when empty — when the next prune is due. */
export function nextExpiry(pulses: PulseMap): number | null {
  let soonest: number | null = null;
  for (const expiresAt of Object.values(pulses)) {
    if (soonest === null || expiresAt < soonest) soonest = expiresAt;
  }
  return soonest;
}

type MapPulseState = {
  pulses: PulseMap;
  /** Light up the regions an agent step touched. No-op for an empty list. */
  pulseRegions: (ids: readonly string[] | undefined) => void;
  /** Drop anything past its expiry. Driven by the map's prune timer. */
  prune: () => void;
  clear: () => void;
};

export const useMapPulseStore = create<MapPulseState>((set, get) => ({
  pulses: {},
  pulseRegions: (ids) => {
    const next = mergePulses(get().pulses, ids, Date.now());
    if (next !== get().pulses) set({ pulses: next });
  },
  prune: () => {
    const next = prunePulses(get().pulses, Date.now());
    if (next !== get().pulses) set({ pulses: next });
  },
  clear: () => {
    if (Object.keys(get().pulses).length > 0) set({ pulses: {} });
  },
}));
