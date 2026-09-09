// Wire values for /api/ask. The UI only offers two engines — "claude" and
// "openai". "anthropic" is the same agentic path as "claude" with a BYOK key
// injected; the frontend picks it automatically when a key is set (see
// `wireProvider`), it is never a user-facing choice.
export type AskProvider = "anthropic" | "openai" | "claude";

export type AskEngine = "claude" | "openai";

/** One tool call in the agent's exploration, streamed as `agent_step` SSE
 *  events (status flips running → done/error with the same id). */
export type AgentStep = {
  id: string;
  tool: string;
  label: string;
  status: "running" | "done" | "error";
  detail?: string | null;
  /** Terrain region ids this step touched, for the map pulse. Absent on
   *  pre-V0.9 streams; snake_case because the SSE payload is used as-is. */
  node_ids?: string[];
};

/** Doc name/excerpt/date for one expanded source chunk backing a citation —
 *  the citation popover's "why does Mnemify believe this?" payload. Only
 *  populated for note/signal citations (the ones chunk-expansion touches);
 *  tag/entity/region citations carry an empty array. */
export type CitationSourceRef = {
  doc_title: string;
  /** Harvest-manifest document id — resolves via `/api/documents/{id}` for
   *  the "View source" inspector. Null on old terrain.db rows compiled
   *  before this field was stamped. */
  doc_id: string | null;
  heading: string | null;
  excerpt: string;
  source_url: string | null;
  updated_at: string | null;
};

export type Citation = {
  citation_id: string;
  node_id: string;
  node_type: "region" | "tag" | "note" | "entity" | "signal";
  layer: number;
  label: string;
  edge_provenance: "extracted" | "inferred" | "ambiguous" | null;
  score?: number;
  source_note_ids?: string[];
  source_chunk_ids?: string[];
  source_refs?: CitationSourceRef[];
  /** The node's home region, when it has one — lets "Show on terrain" focus
   *  a region for citations that aren't themselves a region or tag. */
  home_region_id?: string | null;
};

export type AskMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  /** Citation ids the answer actually referenced ([cN] markers). Chips are
   *  filtered to this set; grows live while the answer streams, reconciled
   *  by the server's `citations_used` event at the end. */
  usedCitationIds?: string[];
  /** True when the model cited nothing and the server fell back to the
   *  top-scored retrieval items. */
  citationsFallback?: boolean;
  /** Agent exploration timeline (agentic providers only). */
  steps?: AgentStep[];
  pending?: boolean;
  error?: string;
};

export type AskSettings = {
  provider: AskEngine;
  model: string;
  anthropicKey: string;
  openaiKey: string;
};

export const DEFAULT_SETTINGS: AskSettings = {
  provider: "claude",
  model: "claude-sonnet-5",
  anthropicKey: "",
  openaiKey: "",
};

/** Provider value sent to /api/ask: the Claude engine switches to the BYOK
 *  "anthropic" wire provider when a key is set, otherwise it rides the local
 *  Claude Code login. Both run the same agentic path server-side. */
export function wireProvider(s: AskSettings): AskProvider {
  if (s.provider === "claude") {
    return s.anthropicKey.trim() ? "anthropic" : "claude";
  }
  return s.provider;
}

export function activeKey(s: AskSettings): string {
  if (s.provider === "openai") return s.openaiKey.trim();
  return s.anthropicKey.trim(); // "claude" — optional, empty means local login
}
