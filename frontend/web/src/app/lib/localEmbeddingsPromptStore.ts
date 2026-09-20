import { create } from "zustand";
import type { CompileStartPayload, CompileStartResult } from "../api/terrain";

/**
 * Hand-off between `useStartCompile` and the LocalEmbeddingsDialog.
 *
 * The backend refuses a compile with `code: "openai_key_missing"` when the
 * Claude engine has no OpenAI key for embeddings. Rather than every compile
 * button growing its own dialog, the mutation parks the request here and
 * awaits the user's decision; the dialog (mounted once in DashboardLayout)
 * resolves it. Resolution values:
 *   - `"local"` — download the on-device model (if needed) and retry the
 *     compile with `embedding_model: "bge-small-en-v1.5"`.
 *   - `null`   — the user dismissed; the mutation resolves `{ok:false,
 *     dismissed:true}` and callers show no error toast.
 */

export type LocalEmbeddingsDecision = "local" | null;

export interface LocalEmbeddingsRequest {
  payload: CompileStartPayload;
  refusal: CompileStartResult;
  resolve: (decision: LocalEmbeddingsDecision) => void;
}

type State = {
  request: LocalEmbeddingsRequest | null;
  ask: (payload: CompileStartPayload, refusal: CompileStartResult) => Promise<LocalEmbeddingsDecision>;
  settle: (decision: LocalEmbeddingsDecision) => void;
};

export const useLocalEmbeddingsPrompt = create<State>((set, get) => ({
  request: null,
  ask: (payload, refusal) =>
    new Promise<LocalEmbeddingsDecision>((resolve) => {
      // A second compile click while the dialog is up: answer it the same
      // way the first one is answered, don't stack dialogs.
      const prev = get().request;
      set({
        request: {
          payload,
          refusal,
          resolve: (d) => {
            prev?.resolve(d);
            resolve(d);
          },
        },
      });
    }),
  settle: (decision) => {
    const req = get().request;
    set({ request: null });
    req?.resolve(decision);
  },
}));
