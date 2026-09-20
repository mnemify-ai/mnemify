import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

// ─── Types (mirror backend src/api/routes_embeddings.py + local_embedder.py) ─

export type LocalEmbeddingsStatus = "idle" | "downloading" | "ready" | "failed";

export interface LocalEmbeddings {
  /** Settings value ("bge-small-en-v1.5"). */
  model: string;
  hf_model: string;
  dim: number;
  size_mb: number;
  languages: string;
  downloaded: boolean;
  status: LocalEmbeddingsStatus;
  error: string | null;
  path: string;
}

/** The on-device embedding model's settings value — keep in step with the
 *  backend LOCAL_EMBEDDING_MODEL. */
export const LOCAL_EMBEDDING_MODEL = "bge-small-en-v1.5" as const;

export const localEmbeddingsQueryKey = ["embeddings", "local"] as const;

export function fetchLocalEmbeddings(): Promise<LocalEmbeddings> {
  return apiFetch<LocalEmbeddings>("/api/embeddings/local");
}

/** Kick off (or re-report) the model download. `setDefault` also saves the
 *  local model as the compile default so later compiles and Ask queries stay
 *  in the same embedding space without asking again. */
export function prepareLocalEmbeddings(
  opts: { setDefault?: boolean; aiMode?: "claude" | "anthropic" } = {},
) {
  return apiFetch<LocalEmbeddings & { ok: boolean }>("/api/embeddings/local/prepare", {
    method: "POST",
    body: JSON.stringify({ set_default: opts.setDefault ?? false, ai_mode: opts.aiMode ?? null }),
  });
}

/** Poll until the download settles. Resolves with the final status; the
 *  caller decides what "failed" means for it. */
export async function waitForLocalEmbeddings(
  opts: { intervalMs?: number; signal?: AbortSignal } = {},
): Promise<LocalEmbeddings> {
  const interval = opts.intervalMs ?? 1500;
  for (;;) {
    const s = await fetchLocalEmbeddings();
    if (s.status === "ready" || s.status === "failed") return s;
    if (opts.signal?.aborted) return s;
    await new Promise((r) => setTimeout(r, interval));
  }
}

export function useLocalEmbeddings(opts: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: localEmbeddingsQueryKey,
    queryFn: fetchLocalEmbeddings,
    refetchInterval: (q) =>
      opts.poll !== false && q.state.data?.status === "downloading" ? 1500 : false,
    staleTime: 5_000,
  });
}

export function useInvalidateLocalEmbeddings() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: localEmbeddingsQueryKey });
}
