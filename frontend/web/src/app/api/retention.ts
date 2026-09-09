import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type RetentionPolicy = "keep" | "purge";

export interface RetentionSettings {
  on_source_delete: RetentionPolicy;
  purge_grace_days: number;
  deleted_count: number;
}

export function useRetention() {
  return useQuery<RetentionSettings>({
    queryKey: ["retention"],
    queryFn: () => apiFetch<RetentionSettings>("/api/settings/retention"),
    staleTime: 10_000,
  });
}

export function useUpdateRetention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { on_source_delete: RetentionPolicy; purge_grace_days: number }) =>
      apiFetch<{ ok: boolean } & typeof body>("/api/settings/retention", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["retention"] }),
  });
}

export function usePurgeNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; purged: number; eligible: number; skipped: number }>(
        "/api/settings/retention/purge-now",
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retention"] });
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
