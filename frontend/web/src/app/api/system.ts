/**
 * `/api/system/*` + `/api/settings/server` + `/api/health` — the app's own
 * lifecycle: how long it waits before quitting itself, and quitting on demand.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, CLIENT_HEADER } from "./client";

/** Re-exported for callers that imported it from here. Every `apiFetch`
 *  call now sends it (see client.ts); the server requires it on anything
 *  that mutates, not just shutdown. */
export { CLIENT_HEADER };

export interface Health {
  ok: boolean;
  version: string;
  /** Short git sha, or null when running outside a checkout. */
  commit: string | null;
  /** Python's `sys.platform` — "darwin" | "win32" | "linux". */
  platform: string;
  /** The `claude` CLI is on the server's PATH (`ai_mode="claude"` can run).
   *  Optional so a tab talking to an older server still type-checks. */
  claude_cli?: boolean;
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
 * server: the backend probes its own PATH for the binary and reports it as
 * `claude_cli` on `/api/health`. The CLI ships for macOS, Linux *and*
 * Windows, so this is never a platform guess — only "is it installed here".
 *
 * While health is still loading `health` is `undefined`, and that means
 * "show everything" rather than hiding an option from a user for a moment.
 * An old server that doesn't report the field is treated the same way.
 *
 * Pure — unit-tested.
 */
export function isClaudeCliAvailable(
  health: Pick<Health, "claude_cli"> | undefined | null,
): boolean {
  return health?.claude_cli !== false;
}

/** Shown wherever {@link isClaudeCliAvailable} disables the CLI mode. */
export const CLAUDE_CLI_UNAVAILABLE_HINT =
  "The `claude` CLI isn't installed on this computer (not on PATH) — install Claude Code, or use the Anthropic API key instead";

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

/** `POST /api/system/shutdown`. `stopping` is false when no server process
 *  is registered to stop — the `mnemify up --reload` dev path, where the
 *  reloader owns the process and only Ctrl+C in the terminal ends it. */
export interface ShutdownResponse {
  ok: boolean;
  stopping: boolean;
}

/** Shown when a shutdown request succeeded but nothing is stopping. */
export const SHUTDOWN_NOT_STOPPING_HINT =
  "The server didn't stop — in --reload mode use Ctrl+C in the terminal.";

/** Did the shutdown actually begin? A 200 with `stopping: false` is not a
 *  stop, and the UI must not tell the user the app is gone. Pure — tested. */
export function isShuttingDown(res: ShutdownResponse | null | undefined): boolean {
  return res?.ok === true && res.stopping === true;
}

/** Quit Mnemify. The server answers *before* it stops, so a resolved promise
 *  means "it's on its way down" (when `stopping` is true), not "it's down". */
export function useShutdown() {
  return useMutation({
    mutationFn: () =>
      apiFetch<ShutdownResponse>("/api/system/shutdown", {
        method: "POST",
        headers: { [CLIENT_HEADER]: "web" },
        body: "{}",
      }),
  });
}

/** `POST /api/system/open-home` — the server opens the data folder in the
 *  OS file manager (the browser cannot). Always `paths.home()`; the route
 *  takes no input. 501 means no opener on that machine — show the path. */
export interface OpenHomeResponse {
  ok: boolean;
  path: string;
}

export function useOpenHome() {
  return useMutation({
    mutationFn: () =>
      apiFetch<OpenHomeResponse>("/api/system/open-home", {
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
