import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../app/api/client";

/** Backend-side Claude Code detection (GET /api/ask/claude-status).
 *  `authenticated` is null when login state can't be read from disk. */
export type ClaudeStatus = { installed: boolean; authenticated: boolean | null };

export const claudeStatusQueryKey = ["ask", "claude-status"] as const;

/** Is Claude Code usable on this machine? Shared by the Settings form and
 *  the composer pill so both say the same thing; the server caches the probe
 *  itself, this just keeps one in-flight request per tab. `undefined` while
 *  loading, `null` when the probe failed. */
export function useClaudeStatus(): ClaudeStatus | null | undefined {
  const q = useQuery({
    queryKey: claudeStatusQueryKey,
    queryFn: () => apiFetch<ClaudeStatus>("/api/ask/claude-status"),
    staleTime: 60_000,
    retry: false,
  });
  if (q.isError) return null;
  return q.data;
}

export function isClaudeReady(status: ClaudeStatus | null | undefined): boolean {
  return status?.installed === true && status.authenticated !== false;
}
