// V3 render-data schema (matches §9 of Frontend technical plan).
// This is what the bake script emits and the frontend consumes.

export type RegionEntry = {
  id: string;
  name: string;
  level: number;
  parentIdx: number;             // -1 for top-level
  isLeaf: boolean;
  color: string;
  accent: string | null;
  centroid: { x: number; z: number };
  radius: number;
  basePlateauHeight: number;
  tagCount: number;
  /** Note/source counts for the region panel. Optional: older bakes omit them. */
  notes?: number;
  sources?: number;
  avgElevation: number;
};

export type AttentionLevel = 'none' | 'low' | 'medium' | 'high' | 'critical';

export type AttentionSignalKind =
  | 'todo'
  | 'risk'
  | 'decision'
  | 'open_question'
  | 'owner'
  | 'recent_change';

export type AttentionSignal = {
  id: string;
  kind: AttentionSignalKind;
  title: string;
  summary: string;
  severity: number;
  status: string;
  owner?: string | null;
  /** Verbatim deadline phrase from the source ("by end of April"), if any. */
  due_text?: string | null;
  /** Resolved ISO deadline (YYYY-MM-DD), if the source stated one. */
  due_date?: string | null;
  source_note_ids: string[];
  source_chunk_ids: string[];
  created_or_updated_at?: string | null;
};

export type AttentionItem = {
  id: string;
  type: 'region' | 'tag';
  label: string;
  summary: string;
  attentionScore: number;
  attentionLevel: AttentionLevel;
  signals: AttentionSignal[];
};

export type AttentionFile = {
  generated_at: string | null;
  regions: Record<string, AttentionItem>;
  tags: Record<string, AttentionItem>;
  burning: Array<{
    id: string;
    type: 'region' | 'tag';
    label: string;
    attentionScore: number;
    attentionLevel: AttentionLevel;
    signalCount: number;
  }>;
};

/** Cross-region tag co-occurrence edge with tip-to-tip world coords. The 3D
 *  arc rendering is gone, but this still backs the app/data layer's
 *  related-tags / crosses-into selectors (indexes.ts → TagProvenanceDrawer). */
export type Arc = {
  from: [number, number, number];   // [x, z, y]
  to: [number, number, number];
  weight: number;
  fromTagId: string;
  toTagId: string;
};

/** One weighted membership of a tag in a top-level region. */
export type TagRegionWeight = {
  regionIdx: number;
  weight: number;       // 0..1, semantic-cosine strength
  isHome: boolean;      // the single region used for hex placement
};

export type Highlights = {
  godTagIds: string[];
  bridgeTagIds: string[];
  trendingTagIds: string[];
};

export type ShaderParams = {
  warpAmp: number;
  reachCapMultiplier: number;
};

export type Bounds = {
  minX: number; maxX: number;
  minZ: number; maxZ: number;
  maxY: number;
};

export type Palette = {
  bg: string;
  ramp: string[];
};

export type RenderData = {
  version: 3;
  schemaName: 'cortex.brain-map.hex';
  generatedAt: string;
  bounds: Bounds;
  palette: Palette;
  hexSize: number;
  regions: RegionEntry[];
  /** Flat array. 5 numbers per hex: [q, r, regionIdx, height, tagIdx]. */
  hexes: number[];
  /** tagIdx → tag.id string. */
  tagIndex: string[];
  /** tagIdx → human-readable tag label (the LLM-generated name). Parallel to
   *  `tagIndex`. Optional: render-data baked before this field existed won't
   *  have it, so consumers fall back to prettifying the id. */
  tagLabels?: string[];
  /** tagIdx → recencyScore (0..1, exp decay over days-since-update,
   *  90-day half-life). Parallel to `tagIndex`. */
  tagRecency: number[];
  /** tagIdx → weighted top-level region memberships, sorted strongest-first.
   *  Parallel to `tagIndex`. Optional: render-data baked before this field
   *  existed won't have it, so consumers must guard for undefined/empty. */
  tagRegionWeights?: TagRegionWeight[][];
  arcs: Arc[];
  highlights: Highlights;
  shaderParams: ShaderParams;
};

/** A single note loaded lazily from mocknotes.json on tag click. */
export type Note = {
  id: string;
  title: string;
  source: string;
  sourceUrl: string;
  author: string;
  /** Last editor's display name when it differs from the creator. */
  lastModifiedBy?: string | null;
  /** Container inside the source — Confluence space key, Jira project key. */
  sourceDetail?: string;
  createdAt: string;
  updatedAt: string;
  regionId: string;
  primaryTagId: string;
  tagIds: string[];
  excerpt: string;
  wordCount: number;
};

export type NotesFile = {
  version: number;
  generatedAt: string;
  notes: Note[];
};
