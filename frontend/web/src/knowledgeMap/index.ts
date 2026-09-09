// Public surface of the KnowledgeMap module. Anything not re-exported here is
// considered internal.

export { KnowledgeMap, type KnowledgeMapProps } from './KnowledgeMap';
export { useKnowledgeMapStore, type KnowledgeMapState } from './store';
export type {
  RenderData, RegionEntry, Arc, Highlights, ShaderParams,
  Bounds, Palette, Note, NotesFile,
} from './types';
