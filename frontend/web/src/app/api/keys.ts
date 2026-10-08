export const qk = {
  connections: () => ["connections"] as const,
  notionDiscover: (token: string | null) => ["connections", "notion", "discover", token] as const,
  notionOAuthStatus: (flow: string | null) => ["connections", "notion", "oauth", flow] as const,
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
  // Region workspaces (/api/regions/*). Everything under "regions" is
  // invalidated together after a compile, since region ids may have moved.
  regions: () => ["regions"] as const,
  region: (id: string) => ["regions", "detail", id] as const,
  regionChanges: (id: string, since: string) => ["regions", "changes", id, since] as const,
  regionMemory: (id: string) => ["regions", "memory", id] as const,
  regionThreads: (id: string) => ["regions", "threads", id] as const,
  unassignedRegion: (key: string) => ["regions", "unassigned", key] as const,
  // Server-side conversation list (all regions + unscoped).
  threads: () => ["threads"] as const,
  thread: (id: string) => ["threads", "detail", id] as const,
};
