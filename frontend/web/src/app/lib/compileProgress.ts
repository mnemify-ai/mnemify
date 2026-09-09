// Compile-progress model for the Compiling page. Stages have very unequal
// durations (enrich + derive dominate), so an equal-weight bar jumps around.
// We weight each stage by its rough share of wall-clock and compute one smooth
// overall percentage. Copy is product-language — never "chunks".

import type { CompileCountsState } from "../sse/useCompileStream";
// Type-only — keeps this module free of react-query / fetch imports so it
// stays a pure lib (and runs under the node-environment vitest).
import type { CompileCounts } from "../api/terrain";

export const STAGE_ORDER = [
  "load", "chunk", "enrich", "cluster", "derive", "compile_notes", "validate", "emit", "render",
] as const;

export type Stage = (typeof STAGE_ORDER)[number];

/** Rough share of total wall-clock per stage (sums to 1.0). Enrich is the long
 *  pole; derive second. The rest are near-instant. */
const STAGE_WEIGHT: Record<string, number> = {
  load: 0.03, chunk: 0.02, enrich: 0.55, cluster: 0.05,
  derive: 0.18, compile_notes: 0.12, validate: 0.02, emit: 0.01, render: 0.02,
};

/** Warm, plain phase names — what the user understands is happening. */
export const PHASE_LABEL: Record<string, string> = {
  load: "Reading your documents",
  chunk: "Breaking things down",
  enrich: "Understanding each piece",
  cluster: "Finding patterns",
  derive: "Naming regions & tags",
  compile_notes: "Writing the notes",
  validate: "Checking connections",
  emit: "Saving your map",
  render: "Drawing your map",
};

/** One-line description shown under the phase title in the morphing card. */
export const PHASE_DESC: Record<string, string> = {
  load: "Gathering everything you've harvested into one place.",
  chunk: "Splitting each document into readable passages.",
  enrich: "Reading the meaning of every passage of your documents.",
  cluster: "Grouping related ideas into regions on your map.",
  derive: "Giving each region and tag a clear, human name.",
  compile_notes: "Summarizing each region and topic for search and the map panel.",
  validate: "Making sure every note and connection lines up.",
  emit: "Writing your Knowledge Map to disk.",
  render: "Laying out the map you'll explore.",
};

/** 1-based phase number for the "PHASE n OF 8" eyebrow. 0 when unknown. */
export function phaseNumber(stage: string | null): number {
  const i = stage ? STAGE_ORDER.indexOf(stage as Stage) : -1;
  return i < 0 ? 0 : i + 1;
}

export const PHASE_COUNT = STAGE_ORDER.length;

/** Overall completion 0..100, weighted by stage. Completed stages contribute
 *  their full weight; the current stage contributes its weight × its own
 *  fraction (enrich/derive expose done/total; others are treated as mid-stage). */
export function weightedPercent(
  stage: string | null,
  counts: CompileCountsState,
): number {
  const i = stage ? STAGE_ORDER.indexOf(stage as Stage) : -1;
  if (i < 0) return 0;
  let base = 0;
  for (let s = 0; s < i; s++) base += STAGE_WEIGHT[STAGE_ORDER[s]] ?? 0;

  let frac = 0.5; // stages without a counter sit mid-way while active
  if (stage === "enrich") {
    frac = enrichFraction(counts);
  } else if (stage === "derive") {
    frac = counts.deriveTotal > 0 ? counts.deriveDone / counts.deriveTotal : 0;
  }
  const pct = (base + (STAGE_WEIGHT[STAGE_ORDER[i]] ?? 0) * Math.min(1, Math.max(0, frac))) * 100;
  return Math.min(100, Math.max(0, pct));
}

/** Share of the enrich weight given to the "extract" (chunk analysis) phase;
 *  the remainder goes to "embed". */
const ENRICH_EXTRACT_SHARE = 0.75;

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

/** Enrich completion as a 0..1 fraction, split so extraction fills the first
 *  ~75% and embedding the last ~25% — keeping the bar moving through both
 *  phases instead of freezing. Prefers the per-phase counters; falls back to
 *  the single done/total + the current phase label when they're absent. */
function enrichFraction(counts: CompileCountsState): number {
  const hasPerPhase = counts.enrichExtractTotal > 0 || counts.enrichEmbedTotal > 0;
  if (hasPerPhase) {
    const ex = counts.enrichExtractTotal > 0 ? counts.enrichExtractDone / counts.enrichExtractTotal : 0;
    const em = counts.enrichEmbedTotal > 0 ? counts.enrichEmbedDone / counts.enrichEmbedTotal : 0;
    return ENRICH_EXTRACT_SHARE * clamp01(ex) + (1 - ENRICH_EXTRACT_SHARE) * clamp01(em);
  }
  // Fallback: one done/total counter, placed within its phase's sub-segment.
  const f = counts.enrichTotal > 0 ? clamp01(counts.enrichDone / counts.enrichTotal) : 0;
  if (counts.enrichPhase === "embed") {
    return ENRICH_EXTRACT_SHARE + (1 - ENRICH_EXTRACT_SHARE) * f;
  }
  return ENRICH_EXTRACT_SHARE * f;
}

/** Widen a poll snapshot's snake_case `counts` into the camelCase state the
 *  progress helpers speak. The SSE stream builds `CompileCountsState` directly;
 *  pollers (`/api/terrain/current`) come through here so both paths feed the
 *  same `weightedPercent` / `stageLabel`. */
export function countsFromSnapshot(c: CompileCounts | undefined): CompileCountsState {
  return {
    docs: c?.docs ?? 0,
    chunks: c?.chunks ?? 0,
    enrichPhase: c?.enrich_phase ?? null,
    enrichDone: c?.enrich_done ?? 0,
    enrichTotal: c?.enrich_total ?? 0,
    enrichExtractDone: c?.enrich_extract_done ?? 0,
    enrichExtractTotal: c?.enrich_extract_total ?? 0,
    enrichEmbedDone: c?.enrich_embed_done ?? 0,
    enrichEmbedTotal: c?.enrich_embed_total ?? 0,
    deriveDone: c?.derive_done ?? 0,
    deriveTotal: c?.derive_total ?? 0,
  };
}

/** Phase-aware count line for the enrich stage — extraction vs embedding.
 *  Returns null outside enrich or before a total is known. */
export function enrichCountLine(counts: CompileCountsState): string | null {
  if (counts.enrichTotal <= 0) return null;
  const verb = counts.enrichPhase === "embed" ? "Embedding" : "Analyzing chunks";
  return `${verb} ${counts.enrichDone.toLocaleString()} / ${counts.enrichTotal.toLocaleString()}`;
}

/** One-line "what is happening right now", for compact surfaces (the TopBar
 *  ops pill). During enrich it's the live count line; elsewhere it's the plain
 *  phase name. Unknown stages fall back to the raw stage string. */
export function stageLabel(
  stage: string | null | undefined,
  counts: CompileCountsState,
): string {
  if (stage === "enrich") {
    const line = enrichCountLine(counts);
    if (line) return line;
  }
  return `Compiling · ${stage ? PHASE_LABEL[stage] ?? stage : "…"}`;
}
