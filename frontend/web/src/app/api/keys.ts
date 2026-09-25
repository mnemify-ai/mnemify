export const qk = {
  connections: () => ["connections"] as const,
  notionDiscover: (token: string | null) => ["connections", "notion", "discover", token] as const,
  confluenceDiscover: (creds: { baseUrl: string; email: string; token: string } | null) =>
    ["connections", "confluence", "discover", creds] as const,
  obsidianDiscover: (vaultPath: string | null) =>
    ["connections", "obsidian", "discover", vaultPath] as const,
  localFilesDiscover: (rootPath: string | null) =>
    ["connections", "localfiles", "discover", rootPath] as const,
  harvestCurrent: () => ["harvest", "current"] as const,
  harvestHistory: () => ["harvest", "history"] as const,
  documents: (params?: { source?: string | null; search?: string | null; page?: number }) =>
    params ? (["documents", "list", params] as const) : (["documents"] as const),
  documentStats: () => ["documents", "stats"] as const,
  documentContent: (id: string) => ["documents", "content", id] as const,
  terrainCurrent: () => ["terrain", "current"] as const,
  terrainReport: () => ["terrain", "report"] as const,
  terrainRuns: () => ["terrain", "runs"] as const,
  // The 3D map's render-data + the MapDataProvider both key off this.
  mapData: () => ["map-data"] as const,
  // Documents changed since the last compile (the pending-changes nudge/feed).
  changes: (since = "last_compile") => ["changes", since] as const,
  // Open todos with deadlines, bucketed by urgency at read time.
  actionItems: () => ["action-items"] as const,
};
