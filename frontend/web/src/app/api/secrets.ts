import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

/**
 * `/api/secrets` — the keys the *server* uses (compile embeddings, the
 * chat providers, the connector tokens the wizards write).
 *
 * The backend allowlists the names it will accept and never returns a value:
 * a row says whether a key is set and shows a masked `hint` like `…k3Fq`.
 * Nothing here should ever try to read a secret back — if you need to prove a
 * key works, that is what `useTestSecret` is for.
 *
 * Distinct from the chat key in `ask/askSettingsStore`, which lives in this
 * browser's localStorage and rides along as `Authorization: Bearer`. That one
 * is a per-browser override; these are the machine's configuration.
 */

// ─── Types ──────────────────────────────────────────────────────────────

export type SecretKind = "api_key" | "email" | "token";

export interface SecretRow {
  name: string;
  label: string;
  kind: SecretKind;
  /** Who the value authenticates against; null when it isn't a credential
   *  on its own (the Confluence account email). */
  provider: string | null;
  /** Whether `POST /api/secrets/{name}/test` can check this one. */
  testable: boolean;
  set: boolean;
  /** Masked tail of the stored value (`"…k3Fq"`), or null when unset. */
  hint: string | null;
}

export type TestSecretResult = { ok: true } | { ok: false; reason: string };

// ─── Pure helpers (unit-tested) ─────────────────────────────────────────

/** The server-side key name backing an Ask engine, or null when the engine
 *  needs none. `claude` drives the local CLI on the user's subscription. */
export function secretNameForAskProvider(provider: string): string | null {
  if (provider === "openai") return "OPENAI_API_KEY";
  if (provider === "claude" || provider === "anthropic") return "ANTHROPIC_API_KEY";
  return null;
}

export function findSecret(
  rows: SecretRow[] | undefined,
  name: string,
): SecretRow | undefined {
  return rows?.find((r) => r.name === name);
}

/** Is the key this Ask engine would use already stored on the server?
 *  Drives the "using the key saved in Settings" note in the chat form. */
export function isAskProviderKeySet(
  rows: SecretRow[] | undefined,
  provider: string,
): boolean {
  const name = secretNameForAskProvider(provider);
  if (!name) return false;
  return findSecret(rows, name)?.set === true;
}

/** Status-pill text. Kept out of the component so the "Set" / "Not set"
 *  wording has one definition and a test can pin it. */
export function describeSecretStatus(row: SecretRow | undefined): string {
  if (!row?.set) return "Not set";
  return row.hint ? `Set ${row.hint}` : "Set";
}

// ─── Query key ──────────────────────────────────────────────────────────

/** Inline, like `audit.ts` — these rows are their own small domain and don't
 *  need an entry in the shared `qk` map. */
export const secretsQueryKey = ["secrets"] as const;

// ─── Read ───────────────────────────────────────────────────────────────

export function useSecrets() {
  return useQuery({
    queryKey: secretsQueryKey,
    queryFn: () => apiFetch<SecretRow[]>("/api/secrets"),
    staleTime: 10_000,
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────

export function useSaveSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      apiFetch<SecretRow>(`/api/secrets/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: secretsQueryKey });
      // A newly-saved OPENAI_API_KEY changes whether a compile can run at
      // all, and the connections cards derive "connected" from the same
      // store — both need to re-read.
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

export function useDeleteSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<void>(`/api/secrets/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: secretsQueryKey });
      qc.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

/**
 * Ask the provider whether a key actually works. Pass `value` to check one
 * the user has typed but not saved; omit it to check the stored key.
 *
 * A rejected key resolves as `{ok: false, reason}` rather than throwing —
 * "your key is wrong" is an answer, not a request failure.
 */
export function useTestSecret() {
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value?: string }) =>
      apiFetch<TestSecretResult>(
        `/api/secrets/${encodeURIComponent(name)}/test`,
        { method: "POST", body: JSON.stringify({ value: value ?? "" }) },
      ),
  });
}
