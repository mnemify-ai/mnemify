// The committed sample workspace (public/demo, built by scripts/sample-data)
// must satisfy what the app looks up at runtime. scripts/sample-data/
// validate.py checks the export more exhaustively; this guards the app-side
// contract so a hand-edit or partial re-export can't break the sample.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildIndexes } from "../data/indexes";
import { scheduleReplay } from "./replay";
import type { SampleChatRecord, SampleManifest } from "./sampleStore";
import type { NotesFile, RenderData } from "../../knowledgeMap/types";

const DEMO = join(__dirname, "../../../public/demo");
const read = <T,>(rel: string): T => JSON.parse(readFileSync(join(DEMO, rel), "utf-8")) as T;

describe("public/demo sample workspace", () => {
  const manifest = read<SampleManifest>("manifest.json");
  const render = read<RenderData>("render-data.json");
  const notes = read<NotesFile>("notes.json");
  const chat = read<SampleChatRecord[]>("chat.json");
  const noteIds = new Set(notes.notes.map((n) => n.id));
  const regionIds = new Set(render.regions.map((r) => r.id));

  it("is a v3 bake whose notes index cleanly", () => {
    expect(render.version).toBe(3);
    const idx = buildIndexes(render, notes);
    expect(idx.regionsById.size).toBe(render.regions.length);
    for (const n of notes.notes) expect(regionIds.has(n.regionId)).toBe(true);
  });

  it("spans every source the sample claims", () => {
    const sources = new Set(notes.notes.map((n) => n.source));
    for (const s of ["notion", "confluence", "obsidian", "localfiles"]) expect(sources.has(s)).toBe(true);
    expect(notes.notes.every((n) => n.author && n.author !== "Unknown")).toBe(true);
  });

  it("maps documents to notes", () => {
    for (const noteId of Object.values(manifest.docIdToNoteId)) expect(noteIds.has(noteId)).toBe(true);
  });

  it("stays light: a curated todo list and bodies only where something points", () => {
    const todos = read<{ items: unknown[] }>("action-items.json").items;
    expect(todos.length).toBeGreaterThanOrEqual(8);
    expect(todos.length).toBeLessThanOrEqual(30);
    expect(manifest.counts.documentBodies).toBeLessThan(manifest.counts.documents);
  });

  it("has a recorded, replayable answer for every suggested question", () => {
    expect(chat.length).toBeGreaterThanOrEqual(6);
    expect(chat.map((c) => c.id)).toEqual(manifest.questions.map((q) => q.id));
    for (const record of chat) {
      const plan = scheduleReplay(record.events);
      const text = plan.map((p) => (p.ev.kind === "delta" ? p.ev.text : "")).join("");
      expect(text.trim().length).toBeGreaterThan(80);
      const citations = plan.flatMap((p) => (p.ev.kind === "citations" ? p.ev.citations : []));
      expect(citations.length).toBeGreaterThan(0);
      for (const c of citations) {
        for (const nid of c.source_note_ids ?? []) expect(noteIds.has(nid)).toBe(true);
        for (const ref of c.source_refs ?? []) if (ref.doc_id) expect(existsSync(join(DEMO, "docs", `${ref.doc_id}.json`))).toBe(true);
      }
    }
  });
});
