// Answers the real app's API calls from the sample workspace's fixtures, so
// the pages it reuses (workspaces, TODOs, documents, the map's panels) run
// unchanged. Shapes are exactly the backend's: export.py saves the responses
// verbatim. Anything the sample doesn't have answers 404 (and says so in dev)
// rather than reaching the network.

import { ApiError } from "../api/client";
import type { ActionItemsResponse, ActionItemUserStatus } from "../api/actionItems";
import type { DocContent, DocRow, DocStats } from "../api/documents";
import type { NotesFile } from "../../knowledgeMap/types";
import type { MemoryCreate, MemoryItem, RegionsIndexResponse, ThreadDetail } from "../api/regions";
import { nowMs } from "../lib/clock";
import { SampleMissError, type SampleManifest, type SampleRegionFile, type SampleStore } from "./sampleStore";

const NOT_IN_SAMPLE = "Not available in the sample workspace — connect a source to use this.";

type Route = { method: string; segments: string[]; query: URLSearchParams; body: unknown };

function parse(path: string, init?: RequestInit): Route {
  const url = new URL(path, "http://sample.local");
  const segments = url.pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  let body: unknown = null;
  if (typeof init?.body === "string") {
    try {
      body = JSON.parse(init.body);
    } catch {
      body = null;
    }
  }
  return { method: (init?.method ?? "GET").toUpperCase(), segments, query: url.searchParams, body };
}

function notFound(what: string): never {
  throw new ApiError(404, `${what} isn't in the sample workspace`);
}

async function regionFile(store: SampleStore, id: string): Promise<SampleRegionFile> {
  try {
    return await store.file<SampleRegionFile>(`regions/${encodeURIComponent(id)}.json`);
  } catch (e) {
    if (e instanceof SampleMissError) notFound(`Region ${id}`);
    throw e;
  }
}

async function documents(store: SampleStore, q: URLSearchParams) {
  const all = await store.file<DocRow[]>("documents.json");
  const source = q.get("source");
  const search = (q.get("search") ?? "").toLowerCase();
  const page = Number(q.get("page") ?? 0);
  const limit = Number(q.get("limit") ?? 50);
  let rows = source ? all.filter((r) => r.source === source) : all;
  if (search) rows = rows.filter((r) => (r.title ?? "").toLowerCase().includes(search));
  return {
    total: rows.length,
    page,
    limit,
    rows: rows.slice(page * limit, page * limit + limit),
    out_of_scope_count: 0,
  };
}

/** The sample ships full text only for documents its answers, todos and
 *  saved memory point at. Every other listed document opens as this: its
 *  details plus the summary the compile wrote for it. */
async function previewDoc(store: SampleStore, docId: string): Promise<{ row: DocRow; content: DocContent }> {
  const [rows, manifest, notes] = await Promise.all([
    store.file<DocRow[]>("documents.json"),
    store.file<SampleManifest>("manifest.json"),
    store.file<NotesFile>("notes.json"),
  ]);
  const row = rows.find((r) => r.id === docId);
  if (!row) notFound(`Document ${docId}`);
  const noteId = manifest.docIdToNoteId[docId];
  const summary = notes.notes.find((n) => n.id === noteId)?.excerpt || row.excerpt;
  const content = [
    `# ${row.title}`,
    summary ? `> ${summary}` : "",
    "*The sample workspace includes the full text of the documents its answers and todos cite. This one is summarized; connect your own sources to read everything.*",
  ]
    .filter(Boolean)
    .join("\n\n");
  return { row, content: { id: docId, content, format: "markdown" } };
}

async function get(store: SampleStore, r: Route): Promise<unknown> {
  const [a, b, c, d] = r.segments;
  switch (a) {
    case "documents": {
      if (!b) return documents(store, r.query);
      if (b === "stats") return store.file<DocStats>("stats.json");
      const doc = await store
        .file<{ row: DocRow; content: unknown }>(`docs/${encodeURIComponent(b)}.json`)
        .catch(() => previewDoc(store, b));
      if (!c) return doc.row;
      if (c === "content") return doc.content;
      if (c === "attachments") return { items: [] };
      return notFound(r.segments.join("/"));
    }
    case "action-items": {
      const regionId = r.query.get("region_id");
      if (regionId) return store.withStatuses((await regionFile(store, regionId)).action_items);
      return store.withStatuses(await store.file<ActionItemsResponse>("action-items.json"));
    }
    case "regions": {
      if (!b) return store.file<RegionsIndexResponse>("regions.json");
      if (b === "threads") {
        if (!c) return { threads: [] };
        return store.file<ThreadDetail>(`threads/${encodeURIComponent(c)}.json`).catch(() => notFound(`Thread ${c}`));
      }
      if (b === "unassigned") return notFound("Unassigned region");
      const region = await regionFile(store, b);
      if (!c) {
        const detail = region.detail;
        const preview = store.memoryPreview(detail.memory_preview, b);
        return {
          ...detail,
          action_items: store.withStatuses(detail.action_items),
          memory_preview: preview,
          memory_count: Math.max(0, detail.memory_count + preview.length - detail.memory_preview.length),
        };
      }
      if (c === "changes") return region.changes;
      if (c === "memory") return store.withMemoryEdits(region.memory, b);
      if (c === "threads") return region.threads;
      return notFound(r.segments.join("/"));
    }
    case "terrain":
      if (b === "report") return store.file("report.json");
      return notFound(r.segments.join("/"));
    case "changes":
      return store.file("changes.json");
    default:
      return notFound(r.segments.join("/") || "/");
  }
  void d;
}

async function write(store: SampleStore, r: Route): Promise<unknown> {
  const [a, b, c, d] = r.segments;
  const now = new Date(nowMs()).toISOString();
  if (a === "action-items" && c === "status" && r.method === "PATCH") {
    const status = (r.body as { status?: ActionItemUserStatus } | null)?.status ?? "unverified";
    store.setStatus(b, status);
    return { signal_id: b, status, updated_at: now };
  }
  if (a === "regions") {
    if (b === "memory" && c) {
      if (r.method === "DELETE") {
        store.deleteMemory(c);
        return undefined;
      }
      if (r.method === "PATCH") {
        store.editMemory(c, { ...(r.body as Partial<MemoryItem>), updated_at: now });
        return { id: c, ...(r.body as object), updated_at: now };
      }
    }
    if (c === "memory" && r.method === "POST") {
      const region = await regionFile(store, b);
      return store.addMemory(b, region.detail.region.name, r.body as MemoryCreate, now);
    }
    if (c === "visit" && r.method === "POST") {
      return { previous_visited_at: null, visited_at: now, region_key: `sample:${b}` };
    }
  }
  void d;
  throw new ApiError(403, NOT_IN_SAMPLE);
}

/** An `ApiOverride` (api/client.ts) backed by `store`. */
export function sampleApi(store: SampleStore) {
  return async (path: string, init?: RequestInit): Promise<unknown> => {
    const route = parse(path, init);
    try {
      return route.method === "GET" ? await get(store, route) : await write(store, route);
    } catch (e) {
      if (import.meta.env.DEV && e instanceof ApiError && e.status === 404) {
        console.info(`[sample] ${route.method} ${path} → 404 (${e.message})`);
      }
      throw e;
    }
  };
}
