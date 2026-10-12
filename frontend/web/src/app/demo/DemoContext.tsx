import { createContext, useContext } from "react";

/**
 * Present only inside the sample workspace (/sample). Real components check
 * `useDemo()` where they'd otherwise do something with a lasting effect the
 * sample can't honour: record a visit, refresh a brief with an LLM, open the
 * real Ask dock, write localStorage.
 */
export type DemoApi = {
  /** Treated as the user's previous visit to every workspace, so "since
   *  your last visit" shows what was harvested after the sample's compile. */
  previousVisit: string | null;
  /** The sample's map files, for map views that would otherwise fetch the
   *  user's compiled map (KnowledgeMap's defaults). */
  mapUrls: { dataUrl: string; notesUrl: string };
  /** Open the sample chat on the map, optionally on a recorded thread. */
  openChat: (opts?: { threadId?: string; regionId?: string }) => void;
};

export const DemoContext = createContext<DemoApi | null>(null);

export function useDemo(): DemoApi | null {
  return useContext(DemoContext);
}
