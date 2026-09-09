// Pure display helpers shared by CitationChip, the inline citation groups in
// AssistantMarkdown, and StepTimeline's collapsed summary. No JSX here.

import { format, formatDistanceToNowStrict } from "date-fns";
import type { AgentStep, Citation } from "./types";

export function provenanceClass(p: Citation["edge_provenance"]): string {
  // Border *style* carries provenance now that border *color* carries node
  // type (see NODE_TYPE_META): solid = extracted/inferred, dashed =
  // ambiguous, muted text = no provenance (seed item).
  if (p === "ambiguous") return "border-dashed";
  if (p === null) return "text-muted";
  return "";
}

/** Per-node-type chip tint + glyph color, all token-based so light/dark both
 *  resolve through the theme (never raw hex). Chip text stays `text-ink` for
 *  AA contrast in both themes — the tint lives in border/background only, and
 *  the glyph shape (see NodeTypeGlyph) keeps type legible without color. */
export type NodeTypeMeta = {
  /** Border + background tint classes for the chip surface. */
  chip: string;
  /** Color class for the tiny node-type glyph. */
  glyph: string;
  /** Human-readable type name for eyebrows and aria labels. */
  display: string;
};

export const NODE_TYPE_META: Record<Citation["node_type"], NodeTypeMeta> = {
  region: { chip: "border-sage/40 bg-sage/10", glyph: "text-sage", display: "Region" },
  tag: { chip: "border-magenta/35 bg-magenta/[0.07]", glyph: "text-magenta", display: "Tag" },
  note: { chip: "border-hair bg-bone/60", glyph: "text-muted", display: "Note" },
  entity: { chip: "border-info/60 bg-info/30", glyph: "text-muted", display: "Entity" },
  signal: { chip: "border-warning/40 bg-warning/10", glyph: "text-warning", display: "Signal" },
};

export function layerName(layer: number): string {
  return layer === 0 ? "note" : layer === 1 ? "entity" : layer === 2 ? "tag" : "region";
}

export function citationTitle(c: Citation): string {
  const provLabel = c.edge_provenance ? ` (${c.edge_provenance})` : "";
  return `${layerName(c.layer)}: ${c.label}${provLabel}`;
}

/** Parses the agentic path's `terrain_overview` step detail string
 *  ("1269 nodes, 6117 edges") into counts for StepTimeline's collapsed
 *  summary. Returns null if that step never ran or the format changes. */
export function parseTerrainOverview(
  steps: AgentStep[],
): { nodes: number; edges: number } | null {
  const step = steps.find((s) => s.tool === "terrain_overview" && s.detail);
  if (!step?.detail) return null;
  const m = /^([\d,]+)\s+nodes,\s*([\d,]+)\s+edges$/i.exec(step.detail.trim());
  if (!m) return null;
  return { nodes: Number(m[1].replace(/,/g, "")), edges: Number(m[2].replace(/,/g, "")) };
}

/** "Jul 28" style — used by CitationPopoverContent's per-passage date row.
 *  Empty string if unparseable. */
export function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return format(d, "MMM d");
}

/** "3 days ago" style relative time for the hover preview card. Empty string
 *  if missing/unparseable so callers can render nothing. */
export function formatRelativeDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return formatDistanceToNowStrict(d, { addSuffix: true });
}

/** Most recent `source_refs[].updated_at` across a set of citations, if any. */
export function mostRecentDate(citations: Citation[]): string | null {
  let best: Date | null = null;
  let bestIso: string | null = null;
  for (const c of citations) {
    for (const r of c.source_refs || []) {
      if (!r.updated_at) continue;
      const d = new Date(r.updated_at);
      if (Number.isNaN(d.getTime())) continue;
      if (!best || d > best) {
        best = d;
        bestIso = r.updated_at;
      }
    }
  }
  return bestIso;
}

/** Where "Show on terrain" should focus for a given citation — a tag selects
 *  directly, a region node focuses itself, and anything else (note/entity/
 *  signal) falls back to its home region when the graph stamped one. Null
 *  means this citation has no terrain representation to show. */
export type TerrainFocusTarget =
  | { kind: "tag"; id: string }
  | { kind: "region"; id: string };

export function terrainFocusTarget(c: Citation): TerrainFocusTarget | null {
  if (c.node_type === "tag") return { kind: "tag", id: c.node_id };
  if (c.node_type === "region") return { kind: "region", id: c.node_id };
  if (c.home_region_id) return { kind: "region", id: c.home_region_id };
  return null;
}
