/**
 * `/api/system/*` + `/api/settings/server` + `/api/health` — the app's own
 * lifecycle: how long it waits before quitting itself, and quitting on demand.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

/** Every shutdown request carries this. A custom header forces a CORS
 *  preflight, and the server allows no cross-origin requests in a normal run —
 *  so a page open in another tab can't quit your Mnemify. */
export const CLIENT_HEADER = "X-Mnemify-Client";

export interface Health {
  ok: boolean;
  version: string;
  /** Short git sha, or null when running outside a checkout. */
  commit: string | null;
  /** Python's `sys.platform` — "darwin" | "win32" | "linux". */
  platform: string;
  paths: {
    layout: string;
    home: string;
    data_dir: string;
    yaml_file: string;
    env_file: string;
  };
}

/**
 * Whether the `claude` CLI compile mode can work on the machine running the
 * server. The CLI ships for macOS and Linux only, so on Windows that mode is
 * a dead end — the Anthropic API key (`anthropic` mode) is the equivalent.
 *
 * `platform` is Python's `sys.platform` from `/api/health`. While health is
 * still loading it is `undefined`, and an unknown platform means "show
 * everything" rather than hiding an option from a Mac user for a moment.
 *
 * Pure — unit-tested.
 */
export function isClaudeCliAvailable(platform: string | undefined | null): boolean {
  return !(platform ?? "").toLowerCase().startsWith("win");
}

/** Shown wherever {@link isClaudeCliAvailable} hides the CLI mode. */
export const CLAUDE_CLI_UNAVAILABLE_HINT =
  "Claude CLI mode is macOS/Linux only — use the Anthropic API key instead";

export interface ServerSettings {
  /** Minutes of inactivity before the server exits. 0 = never. */
  idle_timeout_minutes: number;
}

// ─── Read ───────────────────────────────────────────────────────────────

/** Version / commit / platform. Effectively constant for the life of the tab. */
export function useHealth() {
  return useQuery<Health>({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/api/health"),
    staleTime: 60 * 60_000,
    retry: false,
  });
}

export function useServerSettings() {
  return useQuery<ServerSettings>({
    queryKey: ["server-settings"],
    queryFn: () => apiFetch<ServerSettings>("/api/settings/server"),
    staleTime: 10_000,
  });
}

// ─── Write ──────────────────────────────────────────────────────────────

export function useUpdateServerSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ServerSettings) =>
      apiFetch<{ ok: boolean } & ServerSettings>("/api/settings/server", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["server-settings"] }),
  });
}

/** Quit Mnemify. The server answers *before* it stops, so a resolved promise
 *  means "it's on its way down", not "it's down". */
export function useShutdown() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; stopping: boolean }>("/api/system/shutdown", {
        method: "POST",
        headers: { [CLIENT_HEADER]: "web" },
        body: "{}",
      }),
  });
}

/** One heartbeat. Fire-and-forget: a failed beat just means the next one
 *  matters more, so it never surfaces an error to the user. */
export async function sendHeartbeat(): Promise<void> {
  try {
    await apiFetch<void>("/api/system/heartbeat", { method: "POST", body: "{}" });
  } catch {
    /* the server is down, or restarting — nothing useful to do here */
  }
}
