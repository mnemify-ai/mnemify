// How one `/api/ask` server-sent event changes the answer being streamed and
// the map behind it. Shared by the live stream (useAskStream) and the sample
// workspace's replay of recorded answers (app/demo), so the two can't drift.

import { useMapHighlightStore } from "../app/lib/mapHighlightStore";
import { useMapPulseStore } from "../app/lib/mapPulseStore";
import { highlightFromCitations, usedCitations } from "./askHighlight";
import type { AgentStep, AskMessage, AskStatus, Citation } from "./types";

export type AskEvent =
  | { kind: "citations"; citations: Citation[] }
  | { kind: "delta"; text: string }
  | { kind: "status"; status: AskStatus }
  | { kind: "agent_step"; step: AgentStep }
  | { kind: "citations_used"; used: string[]; fallback: boolean }
  | { kind: "error"; message: string }
  | { kind: "done" };

const CITATION_MARKER = /\[(c\d+)\]/g;

/** Citation ids referenced in the text, deduped in first-appearance order. */
export function extractCitationIds(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(CITATION_MARKER)) {
    if (!seen.has(match[1])) {
      seen.add(match[1]);
      out.push(match[1]);
    }
  }
  return out;
}

/** The assistant message after `ev`. Pure. */
export function applyAskEvent(m: AskMessage, ev: AskEvent): AskMessage {
  switch (ev.kind) {
    case "citations":
      return { ...m, citations: ev.citations };
    case "delta": {
      const text = m.text + ev.text;
      // Surface chips live as [cN] markers stream in; citations_used
      // reconciles at the end.
      return { ...m, text, pending: true, usedCitationIds: extractCitationIds(text) };
    }
    case "status":
      return { ...m, status: ev.status };
    case "agent_step": {
      const steps = m.steps ? [...m.steps] : [];
      const idx = steps.findIndex((s) => s.id === ev.step.id);
      if (idx === -1) steps.push(ev.step);
      else steps[idx] = ev.step;
      return { ...m, steps };
    }
    case "citations_used":
      return { ...m, usedCitationIds: ev.used, citationsFallback: ev.fallback };
    case "error":
      return { ...m, error: ev.message, pending: false };
    case "done":
      return { ...m, pending: false };
  }
}

/**
 * What `ev` does to the map: light everything retrieval touched (first
 * citations frame the camera; later ones only widen the set), pulse the
 * regions the agent walks, then narrow to what the answer leaned on.
 * `allCitations` is the latest citations list seen for this answer.
 */
export function applyAskEventToMap(ev: AskEvent, query: string, allCitations: Citation[]): void {
  if (ev.kind === "citations") {
    const ids = highlightFromCitations(ev.citations);
    const hl = useMapHighlightStore.getState();
    if (hl.highlight === null) hl.setHighlight({ ...ids, label: query.trim() });
    else hl.narrow(ids);
    useMapPulseStore.getState().pulseRegions(ids.regionIds);
  } else if (ev.kind === "agent_step") {
    useMapPulseStore.getState().pulseRegions(ev.step.node_ids);
  } else if (ev.kind === "citations_used") {
    // Same token, so the camera stays where the first framing put it.
    useMapHighlightStore.getState().narrow(highlightFromCitations(usedCitations(allCitations, ev.used)));
  }
}

/** A raw `{event, data}` pair (as the SSE stream or a recording carries it)
 *  → an AskEvent, or null for events the answer doesn't use. */
export function toAskEvent(event: string, data: unknown): AskEvent | null {
  const d = (data ?? {}) as Record<string, unknown>;
  switch (event) {
    case "citations":
      return { kind: "citations", citations: (d.citations as Citation[]) ?? [] };
    case "delta":
      return typeof d.text === "string" ? { kind: "delta", text: d.text } : null;
    case "status":
      return typeof d.stage === "string" ? { kind: "status", status: d as AskStatus } : null;
    case "agent_step":
      return d.id && d.label ? { kind: "agent_step", step: d as unknown as AgentStep } : null;
    case "citations_used":
      return {
        kind: "citations_used",
        used: Array.isArray(d.used) ? (d.used as string[]) : [],
        fallback: Boolean(d.fallback),
      };
    case "error":
      return { kind: "error", message: String(d.message ?? "error") };
    case "done":
      return { kind: "done" };
    default:
      return null;
  }
}
