import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";

// ─── Types ──────────────────────────────────────────────────────────────

export interface Connection {
  source: string;
  status: "connected" | "not_connected";
  workspace_name: string | null;
  last_harvest_at: string | null;
  doc_count: number;
  scope_summary: string | null;
  /** Raw "what to harvest" list — Notion page/db ids, Confluence space keys,
   *  Obsidian / local-folder watch folders, Jira project keys. */
  scope: string[];
  /** Configured scope ids that have no harvested docs yet. Non-zero after a
   *  Manage Scope edit until the user clicks Harvest. */
  pending_scope_count: number;
  /** Local files only: every linked folder. `scope` for this source is the
   *  flat `<root>::<entry>` form (`<root>::` = the whole folder). */
  roots?: LocalRoot[];
}

export interface LocalRoot {
  /** Resolved absolute path — the key every scope id and document uses. */
  path: string;
  name: string;
  watch_folders: string[];
  exists: boolean;
}

/** Split a local-files scope id into its root and root-relative entry. */
export function splitLocalScopeId(id: string): { root: string; entry: string } | null {
  const i = id.indexOf("::");
  if (i <= 0) return null;
  return { root: id.slice(0, i), entry: id.slice(i + 2) };
}

export type ValidateResult =
  | { ok: true; workspace_name: string; visible_count: number }
  | { ok: false; reason: string };

export type ObsidianValidateResult =
  | { ok: true; file_count: number; has_obsidian_dir: true }
  | { ok: false; reason: string; file_count?: number; has_obsidian_dir?: boolean };

export type LocalFilesValidateResult =
  | { ok: true; file_count: number; by_format: Record<string, number>; root_path?: string }
  | { ok: false; reason: string; file_count?: number; by_format?: Record<string, number> };

export interface DiscoverItem {
  id: string;
  title: string;
  /** Secondary line: per-format counts for a folder, format + size for a file. */
  subtitle?: string | null;
  kind: string; // 'page' | 'database' | 'space' | 'personal_space' | 'folder' | 'file'
  /** Parent's id, or null for top-level items. Powers the tree picker. */
  parent_id?: string | null;
  count: number;
}

export interface DiscoverResult {
  items: DiscoverItem[];
  total_accessible: number;
  /** Local folder only: supported files under the root, and per-format counts. */
  file_count?: number;
  by_format?: Record<string, number>;
  error?: string | null;
}

// ─── Read ───────────────────────────────────────────────────────────────

export function useConnections() {
  return useQuery({
    queryKey: qk.connections(),
    queryFn: () => apiFetch<Connection[]>("/api/connections"),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

// ─── Validate (mutations) ───────────────────────────────────────────────

export function useValidateNotion() {
  return useMutation({
    mutationFn: (token: string) =>
      apiFetch<ValidateResult>("/api/connections/notion/validate", {
        method: "POST",
        body: JSON.stringify({ token }),
      }),
  });
}

export interface ConfluenceCreds {
  base_url: string;
  email: string;
  token: string;
}

export function useValidateConfluence() {
  return useMutation({
    mutationFn: (creds: ConfluenceCreds) =>
      apiFetch<ValidateResult>("/api/connections/confluence/validate", {
        method: "POST",
        body: JSON.stringify(creds),
      }),
  });
}

export function useValidateObsidian() {
  return useMutation({
    mutationFn: (vault_path: string) =>
      apiFetch<ObsidianValidateResult>("/api/connections/obsidian/validate", {
        method: "POST",
        body: JSON.stringify({ vault_path }),
      }),
  });
}

export function useValidateLocalFiles() {
  return useMutation({
    mutationFn: (root_path: string) =>
      apiFetch<LocalFilesValidateResult>("/api/connections/localfiles/validate", {
        method: "POST",
        body: JSON.stringify({ root_path }),
      }),
  });
}

// ─── Discover (queries — enabled on demand) ────────────────────────────

/** Discover Notion pages/databases. Pass `token === null` to discover with the
 *  *saved* token (the backend falls back to `.env`) — used by the manage-scope
 *  dialog for an already-connected source. The caller owns `enabled`. */
export function useDiscoverNotion(token: string | null, enabled: boolean) {
  return useQuery({
    queryKey: qk.notionDiscover(token),
    queryFn: () =>
      apiFetch<DiscoverResult>("/api/connections/notion/discover", {
        method: "POST",
        body: JSON.stringify({ token }),
      }),
    enabled,
    staleTime: 60_000,
  });
}

/** Discover Obsidian vault folders. Pass `vaultPath === null` to discover with
 *  the *saved* vault (used by Manage Scope). */
export function useDiscoverObsidian(vaultPath: string | null, enabled: boolean) {
  return useQuery({
    queryKey: qk.obsidianDiscover(vaultPath),
    queryFn: () =>
      apiFetch<DiscoverResult>("/api/connections/obsidian/discover", {
        method: "POST",
        body: JSON.stringify({ vault_path: vaultPath }),
      }),
    enabled,
    staleTime: 60_000,
  });
}

/** Discover a local folder's sub-folders. Pass `rootPath === null` to use
 *  the *saved* folder (Manage Scope). */
export function useDiscoverLocalFiles(rootPath: string | null, enabled: boolean) {
  return useQuery({
    queryKey: qk.localFilesDiscover(rootPath),
    queryFn: () =>
      apiFetch<DiscoverResult>("/api/connections/localfiles/discover", {
        method: "POST",
        body: JSON.stringify({ root_path: rootPath }),
      }),
    enabled,
    staleTime: 60_000,
  });
}

/** Discover Confluence spaces. Pass `creds === null` to discover with the
 *  *saved* credentials (`.env` fallback). The caller owns `enabled`. */
export function useDiscoverConfluence(creds: ConfluenceCreds | null, enabled: boolean) {
  return useQuery({
    queryKey: qk.confluenceDiscover(
      creds
        ? { baseUrl: creds.base_url, email: creds.email, token: creds.token }
        : null,
    ),
    queryFn: () =>
      apiFetch<DiscoverResult>("/api/connections/confluence/discover", {
        method: "POST",
        body: JSON.stringify(creds),
      }),
    enabled,
    staleTime: 60_000,
  });
}

// ─── Save (mutations) ──────────────────────────────────────────────────

export interface NotionSavePayload {
  token: string;
  scope: string[];
}
export interface ConfluenceSavePayload extends ConfluenceCreds {
  scope: string[];
}
export interface ObsidianSavePayload {
  vault_path: string;
  scope: string[]; // watch_folders
}
export interface LocalFilesSavePayload {
  root_path: string;
  scope: string[]; // watch_folders
}

export function useSaveNotion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: NotionSavePayload) =>
      apiFetch<{ ok: true }>("/api/connections/notion/save", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

export function useSaveConfluence() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConfluenceSavePayload) =>
      apiFetch<{ ok: true }>("/api/connections/confluence/save", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

export function useSaveObsidian() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ObsidianSavePayload) =>
      apiFetch<{ ok: true }>("/api/connections/obsidian/save", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

export function useSaveLocalFiles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: LocalFilesSavePayload) =>
      apiFetch<{ ok: true; root_path: string; root_count: number }>("/api/connections/localfiles/save", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

/** Unlink one local folder. Its documents fall out of scope on the next
 *  harvest; nothing on disk is touched. */
export function useRemoveLocalFilesRoot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (root_path: string) =>
      apiFetch<{ ok: true; root_count: number }>("/api/connections/localfiles/remove-root", {
        method: "POST",
        body: JSON.stringify({ root_path }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

// ─── Folder browser (Obsidian + local-folder wizards) ─────────────────

export interface BrowseDirEntry {
  name: string;
  is_vault: boolean;
  /** Supported files (.md / .txt / .pdf) directly inside, non-recursive. */
  file_count?: number;
}

export interface BrowseDirResult {
  path: string;
  parent: string | null;
  entries: BrowseDirEntry[];
  /** True when the currently-listed directory itself is a vault. */
  is_self_vault?: boolean;
  /** Supported files directly in the listed directory. */
  file_count?: number;
  /** Those files, for display (capped server-side). */
  files?: { name: string; format: string; size: string }[];
  error?: string;
}

export function useBrowseDir(path: string | null) {
  return useQuery({
    queryKey: ["browse-dir", path],
    queryFn: () =>
      apiFetch<BrowseDirResult>("/api/connections/browse-dir", {
        method: "POST",
        body: JSON.stringify({ path: path ?? "~" }),
      }),
    enabled: path !== null,
    staleTime: 5_000,
  });
}

// ─── Manage scope for an already-connected source ──────────────────────

/** Re-pick what a connected source harvests (no creds needed). */
export function useUpdateScope() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ source, scope }: { source: string; scope: string[] }) =>
      apiFetch<{ ok: true; scope: string[] }>(`/api/connections/${source}/scope`, {
        method: "POST",
        body: JSON.stringify({ scope }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.connections() }),
  });
}

// ─── Disconnect ────────────────────────────────────────────────────────

export function useDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (source: string) =>
      apiFetch<{ ok: true }>(`/api/connections/${source}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.connections() });
      qc.invalidateQueries({ queryKey: qk.harvestCurrent() });
    },
  });
}
