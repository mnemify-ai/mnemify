import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface Schedule {
  cron: string;
  enabled: boolean;
  next_run: string | null;
}

export interface SchedulesResponse {
  schedules: Record<string, Schedule>;
}

export function useSchedules() {
  return useQuery<SchedulesResponse>({
    queryKey: ["schedules"],
    queryFn: () => apiFetch<SchedulesResponse>("/api/schedules"),
    staleTime: 30_000,
  });
}

export function useUpsertSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ source, cron, enabled }: { source: string; cron: string; enabled: boolean }) =>
      apiFetch<Schedule & { source: string }>(`/api/schedules/${source}`, {
        method: "PUT",
        body: JSON.stringify({ cron, enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (source: string) =>
      apiFetch<{ ok: boolean }>(`/api/schedules/${source}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}
