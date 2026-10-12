import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { sampleApi } from "./resolveSampleRequest";
import { SampleStore } from "./sampleStore";

const item = (id: string) => ({ id, title: id, user_status: "unverified", bucket: "due_soon" });

const FILES: Record<string, unknown> = {
  "documents.json": [
    { id: "d1", source: "notion", title: "Board Update" },
    { id: "d2", source: "confluence", title: "ACH Cut-over Plan" },
    { id: "d3", source: "confluence", title: "SOC 2 Program Overview" },
  ],
  "docs/d2.json": { row: { id: "d2", title: "ACH Cut-over Plan" }, content: { id: "d2", content: "# ACH", format: "md" } },
  "stats.json": { total_documents: 3 },
  "manifest.json": { docIdToNoteId: { d1: "n-1" } },
  "notes.json": { notes: [{ id: "n-1", excerpt: "May board update: MAU up 22%." }] },
  "action-items.json": {
    today: "2026-10-11",
    counts_by_status: { unverified: 2, confirmed: 0, dismissed: 0 },
    items: [item("t1"), item("t2")],
  },
  "regions.json": { regions: [{ id: "r1" }] },
  "regions/r1.json": {
    detail: {
      region: { id: "r1", name: "Payments" },
      memory_preview: [],
      memory_count: 0,
      action_items: { counts_by_status: {}, items: [item("t1")] },
    },
    changes: { changes: [] },
    memory: { groups: [{ region_id: "r1", is_self: true, items: [{ id: "m1", title: "Saved", body: "b" }] }] },
    threads: { threads: [{ id: "demo-q01" }] },
    action_items: { counts_by_status: {}, items: [item("t1")] },
  },
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const rel = String(url).replace(/^\/demo\//, "");
      return rel in FILES
        ? new Response(JSON.stringify(FILES[rel]), { status: 200 })
        : new Response("", { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("sampleApi", () => {
  it("lists, filters and pages documents like the backend", async () => {
    const api = sampleApi(new SampleStore());
    const all = (await api("/api/documents?page=0&limit=50")) as { total: number; rows: unknown[] };
    expect(all.total).toBe(3);
    const conf = (await api("/api/documents?source=confluence&search=soc&page=0&limit=50")) as { rows: { id: string }[] };
    expect(conf.rows.map((r) => r.id)).toEqual(["d3"]);
    const paged = (await api("/api/documents?page=1&limit=2")) as { rows: unknown[]; total: number };
    expect(paged.rows).toHaveLength(1);
    expect(paged.total).toBe(3);
  });

  it("serves a document's row and content", async () => {
    const api = sampleApi(new SampleStore());
    expect(await api("/api/documents/d2")).toMatchObject({ title: "ACH Cut-over Plan" });
    expect(await api("/api/documents/d2/content")).toMatchObject({ format: "md" });
    expect(await api("/api/documents/d2/attachments")).toEqual({ items: [] });
  });

  it("opens a document without shipped text as a summary preview", async () => {
    const api = sampleApi(new SampleStore());
    expect(await api("/api/documents/d1")).toMatchObject({ title: "Board Update" });
    const content = (await api("/api/documents/d1/content")) as { content: string; format: string };
    expect(content.format).toBe("markdown");
    expect(content.content).toContain("May board update: MAU up 22%.");
    await expect(api("/api/documents/nope/content")).rejects.toMatchObject({ status: 404 });
  });

  it("keeps todo verdicts in memory, globally and per region", async () => {
    const api = sampleApi(new SampleStore());
    await api("/api/action-items/t1/status", { method: "PATCH", body: JSON.stringify({ status: "dismissed" }) });
    const all = (await api("/api/action-items")) as { items: { id: string; user_status: string }[]; counts_by_status: Record<string, number> };
    expect(all.items.find((i) => i.id === "t1")?.user_status).toBe("dismissed");
    expect(all.counts_by_status).toEqual({ unverified: 1, confirmed: 0, dismissed: 1 });
    const scoped = (await api("/api/action-items?region_id=r1")) as { items: { user_status: string }[] };
    expect(scoped.items[0].user_status).toBe("dismissed");
    const detail = (await api("/api/regions/r1")) as { action_items: { items: { user_status: string }[] } };
    expect(detail.action_items.items[0].user_status).toBe("dismissed");
  });

  it("applies memory edits and deletions", async () => {
    const api = sampleApi(new SampleStore());
    await api("/api/regions/memory/m1", { method: "PATCH", body: JSON.stringify({ title: "Renamed" }) });
    type Mem = { groups: { items: { title: string }[] }[] };
    const edited = (await api("/api/regions/r1/memory")) as Mem;
    expect(edited.groups[0].items[0].title).toBe("Renamed");
    await api("/api/regions/memory/m1", { method: "DELETE" });
    const deleted = (await api("/api/regions/r1/memory")) as Mem;
    expect(deleted.groups[0].items).toHaveLength(0);
  });

  it("answers 404 for what the sample doesn't have, and 403 for writes it can't honour", async () => {
    const api = sampleApi(new SampleStore());
    await expect(api("/api/regions/nope")).rejects.toMatchObject({ status: 404 });
    await expect(api("/api/connections")).rejects.toBeInstanceOf(ApiError);
    await expect(api("/api/documents/d2/reharvest", { method: "POST" })).rejects.toMatchObject({ status: 403 });
  });
});
