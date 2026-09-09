import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";

// ─── Types (mirror backend src/api/routes_documents.py) ─────────────────

export interface DocRow {
  id: string;
  source: string;
  source_id: string;
  title: string;
  /** Confluence space key / Notion parent title / "—". */
  space: string;
  /** "page" | "database" | … */
  type: string;
  size_bytes: number;
  /** ISO-ish strings (may be null). */
  updated_at: string | null;
  harvested_at: string | null;
  excerpt: string;
  raw_path: string | null;
  /** Ancestor titles, root-first, *excluding* the document itself. Empty
   *  when the doc is top-level or the source has no hierarchy. Examples:
   *  Obsidian path "Projects/Notes/Plan.md" → ["Projects", "Notes"];
   *  Notion nested page → list of ancestor page titles up to the workspace;
   *  Confluence page → [space_name, ...ancestor_titles]. */
  path_titles?: string[];
  /** Doc IDs matching path_titles 1:1 (or empty string when an ancestor
   *  wasn't itself harvested). Lets the viewer make breadcrumb segments
   *  clickable when the ancestor is available. */
  path_ids?: string[];
  /** Source-side structured fields (Notion database-row props, etc.).
   * Empty object when the document has none. */
  properties?: Record<string, DocProperty>;
}

export interface DocProperty {
  /** Notion-derived type tag: "str", "list", "number", "bool", "date", … */
  type: string;
  /** Whatever the harvester resolved — primitive, list of primitives, or null. */
  value: unknown;
}

export interface DocListResponse {
  total: number;
  page: number;
  limit: number;
  rows: DocRow[];
}

export interface DocStats {
  total_documents: number;
  total_bytes: number;
  sources_connected: number;
  last_harvest_at: string | null;
  by_source: Record<string, number>;
  timeseries: { date: string; count: number }[];
}

export interface DocContent {
  id: string;
  content: string;
  format: string;
}

export interface DocAttachment {
  name: string;
  size_bytes: number;
  mime: string;
  is_image: boolean;
  url: string;
}

export interface DocAttachmentList {
  items: DocAttachment[];
}

export interface ReharvestResult {
  ok: boolean;
  action: string;
  doc: DocRow | null;
}

// ─── Hooks ──────────────────────────────────────────────────────────────

export function useDocuments(params: {
  source?: string | null;
  search?: string | null;
  page?: number;
  limit?: number;
}) {
  const { source = null, search = null, page = 0, limit = 50 } = params;
  return useQuery({
    queryKey: qk.documents({ source, search, page }),
    queryFn: () => {
      const qs = new URLSearchParams();
      if (source) qs.set("source", source);
      if (search) qs.set("search", search);
      qs.set("page", String(page));
      qs.set("limit", String(limit));
      return apiFetch<DocListResponse>(`/api/documents?${qs.toString()}`);
    },
    staleTime: 10_000,
    placeholderData: (prev) => prev,
  });
}

export function useDocumentStats() {
  return useQuery({
    queryKey: qk.documentStats(),
    queryFn: () => apiFetch<DocStats>("/api/documents/stats"),
    staleTime: 30_000,
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ["documents", "detail", id],
    queryFn: () => apiFetch<DocRow>(`/api/documents/${encodeURIComponent(id!)}`),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useDocumentContent(id: string | null) {
  return useQuery({
    queryKey: qk.documentContent(id ?? ""),
    queryFn: () =>
      apiFetch<DocContent>(`/api/documents/${encodeURIComponent(id!)}/content`),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useDocumentAttachments(id: string | null) {
  return useQuery({
    queryKey: ["documents", "attachments", id],
    queryFn: () =>
      apiFetch<DocAttachmentList>(
        `/api/documents/${encodeURIComponent(id!)}/attachments`,
      ),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useReharvestDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<ReharvestResult>(`/api/documents/${encodeURIComponent(id)}/reharvest`, {
        method: "POST",
      }),
    onSuccess: (_res, id) => {
      qc.invalidateQueries({ queryKey: ["documents", "detail", id] });
      qc.invalidateQueries({ queryKey: qk.documentContent(id) });
      qc.invalidateQueries({ queryKey: qk.documents() });
      qc.invalidateQueries({ queryKey: qk.documentStats() });
    },
  });
}
