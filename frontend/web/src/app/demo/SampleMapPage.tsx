import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { KnowledgeMap } from "../../knowledgeMap";
import type { TerrainFocusTarget } from "../../ask/citationDisplay";
import type { SourceInspectorTarget } from "../../ask/SourceInspector";
import { MapInteractionHint } from "../components/MapInteractionHint";
import { useTagParam } from "../lib/useTagParam";
import { useSampleShell } from "./SampleLayout";
import { SAMPLE_DATA_BASE, type SampleChatRecord } from "./sampleStore";
import { SampleChatPanel } from "./SampleChatPanel";
import { useMapFocusStore } from "../lib/mapFocusStore";
import { MAP_PANEL_GUTTER } from "../lib/mapPanelStore";

/** /sample — the sample workspace's map, with its chat on the left. */
export function SampleMapPage() {
  const { manifest, chatRequest, consumeChatRequest, bottomBarSlot, chat, chatOpen, setChatOpen } = useSampleShell();
  const [selectedTagId, setSelectedTagId] = useTagParam();
  // Region focus goes through the app's focus store, like Home, so the
  // workspace's "Open full map" and an evidence drawer's "Show on terrain"
  // land here focused. SampleLayout clears it on the way in and out.
  const focusRegionId = useMapFocusStore((s) => s.focusRegionId);
  const setFocusRegionId = useMapFocusStore((s) => s.setFocusRegion);
  const focusTick = useMapFocusStore((s) => s.focusTick);
  const requestFocus = useMapFocusStore((s) => s.requestFocus);
  const [openDocRequest, setOpenDocRequest] = useState<{ noteId: string; tick: number } | null>(null);
  // The chat docks beside the map's detail panel, tracking its real width
  // (it's resizable, collapsible and narrows while the chat is open).
  const [panelWidth, setPanelWidth] = useState(0);

  // Recorded answers are only needed once someone looks at the chat.
  const records = useQuery({
    queryKey: ["sample", "chat"],
    queryFn: async (): Promise<SampleChatRecord[]> => {
      const res = await fetch(`${SAMPLE_DATA_BASE}/chat.json`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    staleTime: Infinity,
    enabled: chatOpen,
  });

  // "Ask region" / an Activity thread elsewhere in the sample → open the
  // chat here, replaying that thread's answer when there is one.
  const { ask, askedIds } = chat;
  useEffect(() => {
    if (!chatRequest) return;
    setChatOpen(true);
    if (!records.data) return;
    consumeChatRequest();
    const record =
      records.data.find((r) => r.threadId === chatRequest.threadId) ??
      (chatRequest.regionId ? records.data.find((r) => r.regionId === chatRequest.regionId) : undefined);
    if (record && !askedIds.has(record.id)) ask(record);
  }, [chatRequest, records.data, ask, askedIds, consumeChatRequest, setChatOpen]);

  const onFocusTerrain = useCallback(
    (target: TerrainFocusTarget) => {
      if (target.kind === "tag") setSelectedTagId(target.id);
      else requestFocus(target.id);
    },
    [setSelectedTagId, requestFocus],
  );
  const onViewSource = useCallback(
    (target: SourceInspectorTarget) => {
      const noteId = manifest.docIdToNoteId[target.docId];
      if (noteId) setOpenDocRequest((prev) => ({ noteId, tick: (prev?.tick ?? 0) + 1 }));
      else if (target.terrainFocus) onFocusTerrain(target.terrainFocus);
    },
    [manifest.docIdToNoteId, onFocusTerrain],
  );

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div className="absolute inset-0 z-0">
        <KnowledgeMap
          dataUrl={`${SAMPLE_DATA_BASE}/render-data.json`}
          notesUrl={`${SAMPLE_DATA_BASE}/notes.json`}
          hideHeader
          hideBreadcrumb
          selectedTagId={selectedTagId}
          onTagSelect={setSelectedTagId}
          focusRegionId={focusRegionId}
          focusRequestTick={focusTick}
          onFocusChange={setFocusRegionId}
          openDocRequest={openDocRequest}
          panelAlwaysOpenAtStart
          compactRightPanel={chatOpen}
          onPanelWidthChange={setPanelWidth}
          bottomBarSlot={bottomBarSlot}
        />
      </div>
      <div className="pointer-events-none absolute inset-0 z-20">
        <div className="pointer-events-auto absolute top-20 left-1/2 -translate-x-1/2 max-w-[calc(100vw-2rem)] hidden lg:block">
          <MapInteractionHint selectedTagId={selectedTagId} />
        </div>
        <div
          className={
            chatOpen
              // Docked against the detail panel, below the map's Home /
              // Timeline buttons, ending above the "Lit for …" answer pill.
              ? "pointer-events-auto absolute top-[132px] bottom-16 hidden md:flex w-[min(400px,calc(100vw-2rem))]"
              // Collapsed: the launcher sits bottom-right, where the real
              // map's "Ask your map" bubble does.
              : "pointer-events-auto absolute bottom-6 hidden md:block"
          }
          style={{ right: panelWidth + MAP_PANEL_GUTTER }}
        >
          <SampleChatPanel
            records={records.data ?? []}
            manifest={manifest}
            chat={chat}
            open={chatOpen}
            onOpenChange={setChatOpen}
            onFocusTerrain={onFocusTerrain}
            onViewSource={onViewSource}
          />
        </div>
      </div>
    </div>
  );
}
