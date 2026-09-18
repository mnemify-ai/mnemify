/**
 * Tells the server a human still has the app on screen.
 *
 * The backend quits itself after `server.idle_timeout_minutes` with no API
 * traffic (Settings → General). A tab that is open but quiet — the map on a
 * second monitor — is *not* idle, so it beats on a timer while visible and
 * goes quiet the moment the tab is hidden: a forgotten background tab should
 * not keep a server alive forever.
 *
 * Mounted once, in the shell (`layouts/DashboardLayout`).
 */
import { useEffect } from "react";
import { sendHeartbeat } from "../api/system";

/**
 * Twice per watchdog tick.
 *
 * The server's idle watchdog wakes every 60 s and compares `idle >= timeout`,
 * so a 60 s beat and a 60 s tick can drift into a tie at a 1-minute timeout:
 * the beat lands just after the tick reads the clock and the tab is declared
 * idle while someone is looking at it. Beating every 30 s means a visible tab
 * always has a beat inside the window the tick measures.
 */
export const HEARTBEAT_INTERVAL_MS = 30_000;

export interface HeartbeatPlan {
  /** Send a beat right now. */
  beat: boolean;
  /** Whether the repeating timer should be running after this transition. */
  running: boolean;
}

/**
 * The whole scheduling decision, as a pure function.
 *
 * `wasRunning` is "is a timer live right now", which doubles as "have we
 * already beaten for this visible stretch" — so becoming visible beats
 * immediately, while a repeated `visibilitychange` that doesn't change
 * anything does not.
 */
export function planHeartbeat(visible: boolean, wasRunning: boolean): HeartbeatPlan {
  if (!visible) return { beat: false, running: false };
  return { beat: !wasRunning, running: true };
}

export function useHeartbeat(intervalMs: number = HEARTBEAT_INTERVAL_MS): void {
  useEffect(() => {
    if (typeof document === "undefined") return;
    let timer: ReturnType<typeof setInterval> | null = null;

    const apply = () => {
      const plan = planHeartbeat(document.visibilityState === "visible", timer !== null);
      if (plan.beat) void sendHeartbeat();
      if (plan.running && timer === null) {
        timer = setInterval(() => void sendHeartbeat(), intervalMs);
      } else if (!plan.running && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    apply();
    document.addEventListener("visibilitychange", apply);
    return () => {
      document.removeEventListener("visibilitychange", apply);
      if (timer !== null) clearInterval(timer);
    };
  }, [intervalMs]);
}
