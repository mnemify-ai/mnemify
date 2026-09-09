// Re-export render-data types from the KnowledgeMap module so the dashboard reads
// the same schema definitions the renderer does. Dashboard-only types follow.

export type {
  RenderData,
  RegionEntry,
  Arc,
  Highlights,
  Bounds,
  Palette,
  Note,
  NotesFile,
} from "../../knowledgeMap/types";

import type { RegionEntry, Arc, Note } from "../../knowledgeMap/types";

/** Indexes built once at data-load time. All Map/array reads are O(1). */
export interface MapIndexes {
  regionsByIdx: RegionEntry[];                   // identity — the renderData.regions array
  regionsById: Map<string, RegionEntry>;
  regionPathById: Map<string, RegionEntry[]>;    // top-level → … → self
  topLevelRegionByTagId: Map<string, RegionEntry>;
  topLevelRegionByRegionId: Map<string, RegionEntry>;

  tagIdToIdx: Map<string, number>;
  tagLabelById: Map<string, string>;             // tag.id → human label (from renderData.tagLabels)
  tagHeights: Map<string, number>;               // tag.id → spire height from hexes[]
  regionByTagId: Map<string, RegionEntry>;       // leaf region owning the tag spire
  arcsByTagId: Map<string, Arc[]>;

  notesByTagId: Map<string, Note[]>;
  notesByRegionId: Map<string, Note[]>;          // direct membership (note.regionId)
  notesByRegionSubtree: Map<string, Note[]>;     // includes descendants

  /** Tag IDs that aren't referenced as either endpoint in arcs[]. Derived. */
  isolatedTagIds: string[];
}

export interface TagInfo {
  id: string;
  label: string;
  recencyScore: number;
  height: number;
  /** Region path from top-level to leaf. `[]` if tag has no spire hex. */
  regionPath: RegionEntry[];
  /** Top-level region this tag belongs to. `null` if no spire hex. */
  topRegion: RegionEntry | null;
  /** Leaf region this tag belongs to. `null` if no spire hex. */
  leafRegion: RegionEntry | null;
  /** Number of notes referencing this tag. */
  frequency: number;
  relatedTagIds: string[];
  /** Arcs whose other endpoint lives in a different top-level region. */
  crossesInto: { tagId: string; regionName: string }[];
  isGod: boolean;
  isBridge: boolean;
  isTrending: boolean;
}
