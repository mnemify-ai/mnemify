import { toast as sonner } from "sonner";

/**
 * Toast micro-moment kit — Track D anthropomorphic copy.
 *
 * Wraps `sonner` with named helpers so the spec'd "voice" of the app
 * (synapse-formed / harvest-complete / memory-wiped / schedule-on) stays
 * consistent wherever it's used. For generic uses, the pass-through
 * `toastSuccess` / `toastError` / `toastInfo` exports are fine.
 */

/** Fired on the first time a source connects in the wizards. */
export const toastSynapse = (source: string) =>
  sonner.success("A new connection is live.", {
    description: `${source} is now part of your Knowledge Map.`,
  });

/** Fired when a harvest run completes — the map "learned" N memories. */
export const toastHarvestComplete = (count: number) =>
  sonner.success(
    `Your map learned ${count.toLocaleString()} new ${count === 1 ? "memory" : "memories"}.`,
  );

/** Fired after a `mnemify reset` — danger-zone, but reassuring copy. */
export const toastReset = () =>
  sonner.success("Memory wiped. Ready when you are.");

/** Fired after the lighter `reset harvested data` action — keeps the source
 *  connections, but clears the map. Matches the wider voice without
 *  overpromising (this isn't a full reset). */
export const toastHarvestReset = () =>
  sonner.success("Map cleared. Your connections stayed.");

/** Fired when toggling a schedule to enabled. */
export const toastScheduleOn = (source: string, cron: string) =>
  sonner.success("Schedule on.", {
    description: `${source} will run on ${cron} (UTC).`,
  });

// Pass-throughs for non-anthropomorphic uses.
export const toastSuccess = sonner.success;
export const toastError = sonner.error;
export const toastInfo = sonner.info;
