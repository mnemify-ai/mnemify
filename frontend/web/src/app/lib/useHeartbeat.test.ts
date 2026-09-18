import { describe, expect, it } from "vitest";
import { HEARTBEAT_INTERVAL_MS, planHeartbeat } from "./useHeartbeat";

describe("planHeartbeat", () => {
  it("beats immediately and starts the timer on a visible mount", () => {
    expect(planHeartbeat(true, false)).toEqual({ beat: true, running: true });
  });

  it("does not double-beat while the timer is already running", () => {
    expect(planHeartbeat(true, true)).toEqual({ beat: false, running: true });
  });

  it("stops without beating when the tab is hidden", () => {
    expect(planHeartbeat(false, true)).toEqual({ beat: false, running: false });
  });

  it("stays quiet when hidden and already stopped", () => {
    expect(planHeartbeat(false, false)).toEqual({ beat: false, running: false });
  });

  it("beats again on hidden → visible", () => {
    // hide (timer cleared) …
    const hidden = planHeartbeat(false, true);
    expect(hidden.running).toBe(false);
    // … then show: the timer is gone, so this transition beats.
    expect(planHeartbeat(true, hidden.running)).toEqual({ beat: true, running: true });
  });

  it("beats twice per watchdog tick", () => {
    // The watchdog ticks every 60 s and tests `idle >= timeout`, so a 60 s beat
    // can tie with the tick and lose at a 1-minute timeout. Half the tick means
    // a visible tab always has a beat inside the window the tick measures.
    expect(HEARTBEAT_INTERVAL_MS).toBe(30_000);
  });
});
