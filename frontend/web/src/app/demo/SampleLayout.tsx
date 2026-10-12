import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type MouseEvent } from "react";
import { Outlet, useNavigate, useOutletContext } from "react-router-dom";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import type { AttentionFile, NotesFile, RenderData } from "../../knowledgeMap/types";
import { StaticMapDataProvider, toMapData } from "../data/MapDataProvider";
import type { ShellOutletContext } from "../layouts/DashboardLayout";
import { freezeClock } from "../lib/clock";
import { useMapFocusStore } from "../lib/mapFocusStore";
import { useMapHighlightStore } from "../lib/mapHighlightStore";
import { useMapPulseStore } from "../lib/mapPulseStore";
import { useMapTimelineStore } from "../lib/mapTimelineStore";
import { DemoContext, type DemoApi } from "./DemoContext";
import { sampleApi } from "./resolveSampleRequest";
import { createSampleQueryClient } from "./sampleQueryClient";
import { SAMPLE_BASE, toSamplePath } from "./samplePaths";
import { SAMPLE_DATA_BASE, SampleStore, type SampleManifest } from "./sampleStore";
import { useSampleChat } from "./useSampleChat";

type SampleBase = {
  manifest: SampleManifest;
  renderData: RenderData;
  notes: NotesFile;
  attention: AttentionFile | null;
};

async function loadBase(): Promise<SampleBase> {
  const get = async <T,>(name: string): Promise<T> => {
    const res = await fetch(`${SAMPLE_DATA_BASE}/${name}`);
    if (!res.ok) throw new Error(`Couldn't load the sample (${name}: HTTP ${res.status})`);
    return (await res.json()) as T;
  };
  const [manifest, renderData, notes, attention] = await Promise.all([
    get<SampleManifest>("manifest.json"),
    get<RenderData>("render-data.json"),
    get<NotesFile>("notes.json"),
    get<AttentionFile>("attention.json").catch(() => null),
  ]);
  return { manifest, renderData, notes, attention };
}

/** A request from elsewhere in the sample (a workspace's "Ask region", a
 *  thread in Activity) for the map page to open its chat. */
export type SampleChatRequest = { tick: number; threadId?: string; regionId?: string };

type SampleShell = {
  manifest: SampleManifest;
  bottomBarSlot: HTMLElement | null;
  /** The chat lives here, not on the map page, so the conversation survives
   *  a trip to Workspaces and back. */
  chat: ReturnType<typeof useSampleChat>;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  /** Pending request from elsewhere in the sample; the map page handles it
   *  once, then calls `consumeChatRequest`. */
  chatRequest: SampleChatRequest | null;
  consumeChatRequest: () => void;
};

const SampleShellContext = createContext<SampleShell | null>(null);

export function useSampleShell(): SampleShell {
  const ctx = useContext(SampleShellContext);
  if (!ctx) throw new Error("useSampleShell must be used inside <SampleLayout>");
  return ctx;
}

/**
 * /sample — the sample workspace. Reuses the real Map, Workspaces, TODOs and
 * Documents pages over a fictional company's compiled knowledge (exported to
 * public/demo by scripts/sample-data). Everything below this layout reads
 * fixtures: the map data via StaticMapDataProvider, every API hook via a
 * sample QueryClient. Nothing the visitor does here reaches the backend.
 */
export function SampleLayout() {
  const base = useQuery({ queryKey: ["sample", "base"], queryFn: loadBase, staleTime: Infinity, retry: false });
  const shell = useOutletContext<ShellOutletContext | undefined>();

  if (base.error) {
    return (
      <div className="min-h-dvh flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <p className="eyebrow text-rose mb-3">Sample workspace unavailable</p>
          <p className="font-serif text-xl text-ink">{(base.error as Error).message}</p>
        </div>
      </div>
    );
  }
  if (!base.data) {
    return (
      <div className="relative min-h-dvh w-full bg-cream flex items-center justify-center">
        <span className="font-serif text-muted animate-pulse motion-reduce:animate-none">Loading the sample workspace…</span>
      </div>
    );
  }
  return <SampleWorkspace base={base.data} bottomBarSlot={shell?.bottomBarSlot ?? null} />;
}

function SampleWorkspace({ base, bottomBarSlot }: { base: SampleBase; bottomBarSlot: HTMLElement | null }) {
  const navigate = useNavigate();
  const [client] = useState(() => createSampleQueryClient(sampleApi(new SampleStore())));
  const mapData = useMemo(() => toMapData(base.renderData, base.notes, base.attention), [base]);
  const [chatRequest, setChatRequest] = useState<SampleChatRequest | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const chat = useSampleChat();

  // The sample is a moment in time: relative labels count from its export.
  // Set during the first render so the very first paint already uses it. No
  // unfreeze on unmount: the clock only honours it while the URL is inside
  // /sample (lib/clock.ts), and an unmount cleanup would also fire on
  // StrictMode's simulated remount in dev, unfreezing the sample itself.
  useState(() => {
    const at = Date.parse(base.manifest.exportedAt);
    freezeClock(Number.isNaN(at) ? null : at);
  });

  // The map's highlight/pulse/focus/timeline stores are app-wide. Start the
  // sample clean of the user's own map state, and leave none of the sample's
  // behind. Layout effect: runs before the sample map's own effects read them.
  useLayoutEffect(() => {
    resetSharedMapState();
    return resetSharedMapState;
  }, []);

  const openChat = useCallback<DemoApi["openChat"]>(
    (opts) => {
      setChatRequest((prev) => ({ tick: (prev?.tick ?? 0) + 1, ...opts }));
      navigate(SAMPLE_BASE);
    },
    [navigate],
  );
  const consumeChatRequest = useCallback(() => setChatRequest(null), []);
  const demo = useMemo<DemoApi>(
    () => ({
      previousVisit: base.manifest.generatedAt,
      mapUrls: { dataUrl: `${SAMPLE_DATA_BASE}/render-data.json`, notesUrl: `${SAMPLE_DATA_BASE}/notes.json` },
      openChat,
    }),
    [base.manifest.generatedAt, openChat],
  );
  const shell = useMemo<SampleShell>(
    () => ({ manifest: base.manifest, bottomBarSlot, chat, chatOpen, setChatOpen, chatRequest, consumeChatRequest }),
    [base.manifest, bottomBarSlot, chat, chatOpen, chatRequest, consumeChatRequest],
  );

  // The reused pages link with absolute app paths; keep the ones the sample
  // can show inside it. Runs in the capture phase, ahead of <Link>'s own
  // handler, which then sees `defaultPrevented` and stands down.
  // Modified and middle clicks open the sample page in a new tab rather
  // than the real one.
  const keepLinksInSample = (e: MouseEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || (e.button !== 0 && e.button !== 1)) return;
    const a = (e.target as Element | null)?.closest?.("a[href]");
    if (!(a instanceof HTMLAnchorElement)) return;
    const url = new URL(a.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const href = `${url.pathname}${url.search}${url.hash}`;
    const mapped = toSamplePath(href);
    if (!mapped || mapped === href) return;
    e.preventDefault();
    const newTab = e.button === 1 || e.metaKey || e.ctrlKey || e.shiftKey || (a.target && a.target !== "_self");
    if (newTab) window.open(mapped, "_blank", "noopener");
    else navigate(mapped);
  };

  return (
    <QueryClientProvider client={client}>
      <StaticMapDataProvider data={mapData}>
        <DemoContext.Provider value={demo}>
          <SampleShellContext.Provider value={shell}>
            <div className="contents" onClickCapture={keepLinksInSample} onAuxClickCapture={keepLinksInSample}>
              <Outlet context={{ bottomBarSlot } satisfies ShellOutletContext} />
            </div>
          </SampleShellContext.Provider>
        </DemoContext.Provider>
      </StaticMapDataProvider>
    </QueryClientProvider>
  );
}

function resetSharedMapState(): void {
  useMapHighlightStore.getState().clear();
  useMapPulseStore.getState().clear();
  useMapFocusStore.getState().setFocusRegion(null);
  useMapTimelineStore.getState().setAsOf(null);
}
