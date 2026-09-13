// Self-contained KnowledgeMap component. Per Frontend technical plan §17:
// - Owns its own zustand store (no module-level singleton)
// - Owns its own data fetch (no host preload required)
// - Self-sized; fills its parent
// - Scoped input (Esc/keys only when focused — added later)
//
// V2 layout (this file): the chrome no longer floats over the 3D canvas
// as absolute-positioned panels. The shell is a flex column:
//
//   ┌─────────────────────────────────────────────────────────────┐
//   │  [canvas + breadcrumb + minimap]   │   right sidebar (slot) │
//   ├─────────────────────────────────────────────────────────────┤
//   │        bottom bar (corpus · map stats · sources)            │
//   └─────────────────────────────────────────────────────────────┘
//
// …unless the host hands us a `bottomBarSlot`, in which case the bar is
// portalled out to a shell-owned row that spans the whole window — on Home
// it must run *under* the app-level Ask dock too, which is a flex sibling of
// this component, not a child:
//
//   ┌──────────────────────────────────────────┬──────────────────┐
//   │  [canvas]              │ right sidebar   │    Ask dock      │
//   ├──────────────────────────────────────────┴──────────────────┤
//   │            bottom bar (full window width)                   │
//   └─────────────────────────────────────────────────────────────┘
//
// drei's <Html> projections (the region medallions) are anchored to the
// Canvas DOM box — now physically smaller — so they can never overlap the
// right sidebar or the bottom bar. That's the structural fix for the
// "map labels block the chrome" pain point.
//
// Public props are intentionally optional so the map works fullscreen or
// embedded in a dashboard panel with no refactor.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { PanelRightClose, PanelRightOpen } from 'lucide-react';
import { CartographerDecorations } from './chrome/CartographerDecorations';
import { Header } from './chrome/Header';
import { HexTooltip } from './chrome/HexTooltip';
import { RegionHoverPreview } from './chrome/RegionHoverPreview';
import { RightPanel } from './chrome/RightPanel';
import { BottomBar } from './chrome/BottomBar';
import { ResetViewButton } from './chrome/ResetViewButton';
import { useRenderData } from './data/useRenderData';
import { recolorRegions } from './util/regionColors';
import { Scene } from './scene/Scene';
import {
  KnowledgeMapStoreProvider,
  useKnowledgeMapStore,
  useLocalKnowledgeMapStore,
} from './store';
import { useEscapeHandler } from './input/useEscapeHandler';
import type { RenderData } from './types';

export type KnowledgeMapProps = {
  /** Where to fetch the v3 render-data. Defaults to the backend's
   *  `/api/terrain/render-data` (same-origin in prod; Vite-proxied in dev). */
  dataUrl?: string;
  /** Where to fetch the notes file used by the hover tooltip. Defaults to
   *  `/api/terrain/notes`. */
  notesUrl?: string;
  /** className for sizing. Defaults to filling parent. */
  className?: string;

  /** Controlled focus region (or null = top-level). When provided, the map
   *  is in controlled mode; the host owns scope and must update this prop
   *  in response to `onFocusChange`. */
  focusRegionId?: string | null;
  onFocusChange?: (regionId: string | null) => void;

  /** Controlled tag selection. Same controlled/uncontrolled rules as focus. */
  selectedTagId?: string | null;
  onTagSelect?: (tagId: string | null) => void;

  /** Suppress individual chrome pieces. Used when the host renders its own. */
  hideHeader?: boolean;
  hideBreadcrumb?: boolean;
  hideBottomBar?: boolean;
  /** Suppress the right drill-down panel. The panel reads app-level map data
   *  (useMapDataReady), which is absent in standalone contexts like the
   *  sample-terrain demo — hide it there to keep the map self-contained. */
  hideRightPanel?: boolean;
  /** Narrow the right panel to its compact width. Set while the app-level Ask
   *  dock is open, so the canvas keeps a usable share of the viewport with
   *  two right-hand columns on screen. Manual resizing still wins. */
  compactRightPanel?: boolean;

  /** Effective width, in px, of the right detail panel: its resizable full
   *  width, the narrow rail when collapsed, or 0 when suppressed. Hosts that
   *  float chrome over the canvas (Home's briefing card, the shell's Ask
   *  bubble) use it to stay clear of the panel however the user sized it.
   *  Fires on mount and on every commit — during a drag only on release, so
   *  the 3D canvas isn't re-rendered on every pointer move. */
  onPanelWidthChange?: (width: number) => void;

  /** Where to render the bottom bar. Three-way on purpose:
   *  - `undefined` → inline, as the map's own bottom row (standalone / demo).
   *  - an element  → portal into it, so the host can span the bar across
   *    surfaces that live outside this component (the Ask dock). The bar stays
   *    in this React tree either way — it needs the KnowledgeMap store and the
   *    recoloured data.
   *  - `null`      → render nothing. The host's callback ref hasn't attached
   *    yet; rendering inline for that one frame would flash the bar in the map
   *    column and resize the r3f canvas twice. */
  bottomBarSlot?: HTMLElement | null;
};

const DEFAULT_DATA_URL = '/api/terrain/render-data';
const DEFAULT_NOTES_URL = '/api/terrain/notes';
const SIDEBAR_WIDTH = 400;
const SIDEBAR_COMPACT_WIDTH = 300;
/** Collapsed: just wide enough for the expand button. Deliberately below the
 *  resize floor — the rail is never a `panelWidth` value, so collapsing can't
 *  clobber the width the user (or the Ask-dock snap) settled on. */
const SIDEBAR_RAIL_WIDTH = 44;
const PANEL_COLLAPSED_KEY = 'mnemify.map.panelCollapsed';

export function KnowledgeMap(props: KnowledgeMapProps) {
  const { dataUrl = DEFAULT_DATA_URL, className } = props;
  const store = useLocalKnowledgeMapStore();
  const dataState = useRenderData(dataUrl);

  return (
    <KnowledgeMapStoreProvider store={store}>
      <div
        className={className}
        style={{
          width: '100%',
          height: '100%',
          background: 'rgb(var(--c-bg))',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {dataState.status === 'loading' && <LoadingState />}
        {dataState.status === 'error' && <ErrorState message={dataState.error} />}
        {dataState.status === 'ready' && (
          <ReadyChrome data={dataState.data} props={props} />
        )}
      </div>
    </KnowledgeMapStoreProvider>
  );
}

function ReadyChrome({ data: rawData, props }: { data: RenderData; props: KnowledgeMapProps }) {
  // Override the backend's repeating 8-colour palette with a vibrant, varied
  // one (assigned per top-level region) before anything renders. Every consumer
  // reads from this recoloured copy, so map + medallions + panel stay in sync.
  const data = useMemo(() => recolorRegions(rawData), [rawData]);
  useEscapeHandler();
  useControlledFocusBridge(data, props.focusRegionId, props.onFocusChange);
  useControlledTagBridge(data, props.selectedTagId, props.onTagSelect);

  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const compact = Boolean(props.compactRightPanel);
  const [panelWidth, setPanelWidth] = useState(
    compact ? SIDEBAR_COMPACT_WIDTH : SIDEBAR_WIDTH,
  );

  // Collapsed → the panel shrinks to a rail so the map (and, on Home, the
  // chat beside it) get the width back. `panelWidth` is deliberately left
  // alone while collapsed: expanding restores exactly what was there, and the
  // Ask-dock snap below keeps running underneath, unaware of the collapse.
  // Persisted the same way the Documents filter rail is (see DocumentsPage).
  const [panelCollapsed, setPanelCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(PANEL_COLLAPSED_KEY) === '1';
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(PANEL_COLLAPSED_KEY, panelCollapsed ? '1' : '0');
    } catch {
      /* ignore — private mode etc. */
    }
  }, [panelCollapsed]);

  // Snap to the matching default when the Ask dock opens/closes. A width the
  // user dragged themselves is left alone — only untouched defaults move.
  const userResizedRef = useRef(false);
  useEffect(() => {
    if (userResizedRef.current) return;
    setPanelWidth(compact ? SIDEBAR_COMPACT_WIDTH : SIDEBAR_WIDTH);
  }, [compact]);

  // How much of the host's right edge the panel is actually eating. Reported
  // out so overlays the host floats over the canvas can track it.
  const hideRightPanel = Boolean(props.hideRightPanel);
  const effectivePanelWidth = hideRightPanel
    ? 0
    : panelCollapsed
      ? SIDEBAR_RAIL_WIDTH
      : panelWidth;
  const { onPanelWidthChange } = props;
  useEffect(() => {
    onPanelWidthChange?.(effectivePanelWidth);
  }, [effectivePanelWidth, onPanelWidthChange]);

  // Drag the panel's left edge to resize, clamped to [default, half the map
  // column]. Measured against the panel's own right edge and its column, NOT
  // the viewport: the app-level Ask dock is a flex sibling of the whole page
  // column, so `window.innerWidth - clientX` overshoots by the dock's width
  // and pins the panel at its max the moment chat is open.
  // We mutate the width directly during the drag and only commit to state on
  // release, so the 3D canvas doesn't re-render every pointer move.
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const minWidth = compact ? SIDEBAR_COMPACT_WIDTH : SIDEBAR_WIDTH;
    const asideRight = asideRef.current?.getBoundingClientRect().right ?? 0;
    const colWidth =
      asideRef.current?.parentElement?.getBoundingClientRect().width ?? 0;
    const onMove = (ev: PointerEvent) => {
      const w = Math.max(minWidth, Math.min(colWidth * 0.5, asideRight - ev.clientX));
      if (asideRef.current) asideRef.current.style.width = `${w}px`;
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      if (asideRef.current) {
        userResizedRef.current = true;
        setPanelWidth(asideRef.current.getBoundingClientRect().width);
      }
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  return (
    <>
      {/* Top row: canvas + unified right panel */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <div
          ref={canvasContainerRef}
          style={{
            flex: 1,
            position: 'relative',
            minWidth: 0,
            overflow: 'hidden',
          }}
        >
          <Scene data={data} />
          <CartographerDecorations />
          {!props.hideHeader && <Header data={data} />}
          <ResetViewButton />
          {/* On-map breadcrumb removed — navigation now lives in the right
              panel's nav header (Back + breadcrumb). */}
          <HexTooltip
            data={data}
            notesUrl={props.notesUrl ?? DEFAULT_NOTES_URL}
            containerRef={canvasContainerRef}
          />
          {/* Delayed card for the region under the cursor at the current
              level (name · notes · sub-regions · summary). Yields to the tag
              tooltip above while a spire is hovered. */}
          <RegionHoverPreview data={data} containerRef={canvasContainerRef} />
        </div>
        {/* Single unified panel: regions list → region detail → tag detail.
            Always present (hidden < md). Drag the left edge to resize up to
            half the screen, or collapse it to a rail to watch just the map.
            Either way the borderLeft seam stays, so the canvas reads as a
            column that ends rather than one cut off at the window edge. */}
        {!hideRightPanel &&
          (panelCollapsed ? (
            <aside
              className="hidden md:flex"
              style={railStyle}
              aria-label="Map detail, collapsed"
            >
              <button
                type="button"
                onClick={() => setPanelCollapsed(false)}
                aria-label="Expand detail panel"
                aria-expanded={false}
                title="Expand detail panel"
                className="grid h-8 w-8 place-items-center rounded-lg border border-hair bg-bone/40 text-muted transition-colors hover:bg-bone/70 hover:text-ink"
              >
                <PanelRightOpen size={16} strokeWidth={1.5} aria-hidden />
              </button>
            </aside>
          ) : (
            <aside
              ref={asideRef}
              className="hidden md:flex"
              style={{ ...panelStyle, width: panelWidth }}
              aria-label="Map detail"
            >
              <div
                onPointerDown={startResize}
                title="Drag to resize"
                style={resizeHandleStyle}
              />
              {/* Its own row rather than a badge on the drag handle — the
                  handle owns pointerdown across the whole left edge, so a
                  click target sitting on it would be swallowed by the drag. */}
              <div style={panelToolbarStyle}>
                <button
                  type="button"
                  onClick={() => setPanelCollapsed(true)}
                  aria-label="Collapse detail panel"
                  aria-expanded
                  title="Collapse detail panel"
                  className="grid h-7 w-7 place-items-center rounded-lg text-muted transition-colors hover:bg-bone/60 hover:text-ink"
                >
                  <PanelRightClose size={16} strokeWidth={1.5} aria-hidden />
                </button>
              </div>
              {/* RightPanel's roots are all `h-full`; this gives them a
                  definite box to fill now that the toolbar shares the column. */}
              <div style={panelBodyStyle}>
                <RightPanel data={data} />
              </div>
            </aside>
          ))}
      </div>

      {/* Bottom row: stats · sources — inline here, or portalled into the
          host's own full-width row. See `bottomBarSlot` for the third case. */}
      {!props.hideBottomBar &&
        (props.bottomBarSlot === undefined ? (
          <BottomBar data={data} />
        ) : props.bottomBarSlot !== null ? (
          createPortal(<BottomBar data={data} />, props.bottomBarSlot)
        ) : null)}
    </>
  );
}

/**
 * Controlled/uncontrolled bridge for `focusRegionId`.
 *
 * When `focusRegionId` is undefined → uncontrolled; store owns the state.
 * When provided → controlled; we sync prop → store on prop change, and
 * fire `onFocusChange` on store change. A ref tracks the last value we
 * synced in each direction so we never bounce updates back where they
 * came from.
 */
function useControlledFocusBridge(
  data: RenderData,
  focusRegionId: string | null | undefined,
  onFocusChange: ((id: string | null) => void) | undefined,
) {
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const setFocusRegion = useKnowledgeMapStore((s) => s.setFocusRegion);
  const requestZoomToRegion = useKnowledgeMapStore((s) => s.requestZoomToRegion);
  // Starts undefined (not the initial prop) so the mount value is synced too —
  // the map can mount with a selection already in the URL (command-palette
  // navigation, deep link, reload).
  const lastSyncedPropRef = useRef<string | null | undefined>(undefined);
  // Set while a prop → store push is in flight. The store hook value lags the
  // write by one render; without this the store → prop effect would echo the
  // stale value back and wipe the URL param.
  const pendingStoreEchoRef = useRef<{ value: string | null } | null>(null);
  const lastFiredCallbackValueRef = useRef<string | null | undefined>(undefined);

  // prop → store
  useEffect(() => {
    if (focusRegionId === undefined) return;
    if (focusRegionId === lastSyncedPropRef.current) return;
    const prevSyncedProp = lastSyncedPropRef.current;
    lastSyncedPropRef.current = focusRegionId;
    const idx = focusRegionId === null
      ? null
      : data.regions.findIndex((r) => r.id === focusRegionId);
    const resolvedIdx = idx !== null && idx >= 0 ? idx : null;
    pendingStoreEchoRef.current = { value: resolvedIdx === null ? null : focusRegionId };
    setFocusRegion(resolvedIdx);
    // Externally-driven focus (e.g. a chat citation's "Show on terrain")
    // should fly the camera in, same as the tag-select path already does via
    // `navigate()` — plain `setFocusRegion` only moves the hex glow/dim.
    // Clearing it flies back to the home framing; `undefined` means this is
    // the mount sync, where there's nothing to fly back from.
    if (resolvedIdx !== null) requestZoomToRegion(resolvedIdx);
    else if (prevSyncedProp !== undefined) requestZoomToRegion(null);
  }, [focusRegionId, data.regions, setFocusRegion, requestZoomToRegion]);

  // store → prop
  useEffect(() => {
    if (focusRegionId === undefined) return;
    const storeRegionId = focusRegionIdx === null ? null : data.regions[focusRegionIdx]?.id ?? null;
    const pending = pendingStoreEchoRef.current;
    if (pending) {
      if (storeRegionId === pending.value) pendingStoreEchoRef.current = null;
      return;
    }
    if (storeRegionId === focusRegionId) return;
    if (storeRegionId === lastFiredCallbackValueRef.current) return;
    lastFiredCallbackValueRef.current = storeRegionId;
    onFocusChange?.(storeRegionId);
  }, [focusRegionIdx, focusRegionId, data.regions, onFocusChange]);
}

/** Leaf regionIdx of the hex spire carrying `tagId`, or null if the tag isn't
 *  on the map (the bake can drop tags the compile report still references). */
function findTagSpireRegionIdx(data: RenderData, tagId: string): number | null {
  const tagIdx = data.tagIndex.indexOf(tagId);
  if (tagIdx < 0) return null;
  const HEX_STRIDE = 5; // [q, r, regionIdx, height, tagIdx]
  for (let i = 0; i < data.hexes.length; i += HEX_STRIDE) {
    if (data.hexes[i + 4] === tagIdx) return data.hexes[i + 2];
  }
  return null;
}

/** Same shape as useControlledFocusBridge, for `selectedTagId`. */
function useControlledTagBridge(
  data: RenderData,
  selectedTagId: string | null | undefined,
  onTagSelect: ((id: string | null) => void) | undefined,
) {
  const storeTagId = useKnowledgeMapStore((s) => s.selectedTagId);
  const setSelectedTag = useKnowledgeMapStore((s) => s.setSelectedTag);
  const navigateStore = useKnowledgeMapStore((s) => s.navigate);
  // See useControlledFocusBridge for why these start undefined / track a
  // pending echo: the mount value must sync too, and the store hook value
  // lags a prop → store push by one render.
  const lastSyncedPropRef = useRef<string | null | undefined>(undefined);
  const pendingStoreEchoRef = useRef<{ value: string | null } | null>(null);
  const lastFiredCallbackValueRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (selectedTagId === undefined) return;
    if (selectedTagId === lastSyncedPropRef.current) return;
    lastSyncedPropRef.current = selectedTagId;
    pendingStoreEchoRef.current = { value: selectedTagId };
    // `storeTagId !== selectedTagId` means the change originated OUTSIDE the
    // map (deep link, compile-report chip, command palette) rather than being
    // the URL echo of a store change — for those, also focus + zoom the tag's
    // home region so the map visibly responds to the selection.
    if (selectedTagId !== null && storeTagId !== selectedTagId) {
      const regionIdx = findTagSpireRegionIdx(data, selectedTagId);
      navigateStore(
        regionIdx !== null
          ? { selectedTagId, focusRegionIdx: regionIdx, docNoteId: null }
          : { selectedTagId, docNoteId: null },
      );
    } else {
      setSelectedTag(selectedTagId);
    }
  }, [selectedTagId, storeTagId, setSelectedTag, navigateStore, data]);

  useEffect(() => {
    if (selectedTagId === undefined) return;
    const pending = pendingStoreEchoRef.current;
    if (pending) {
      if (storeTagId === pending.value) pendingStoreEchoRef.current = null;
      return;
    }
    if (storeTagId === selectedTagId) return;
    if (storeTagId === lastFiredCallbackValueRef.current) return;
    lastFiredCallbackValueRef.current = storeTagId;
    onTagSelect?.(storeTagId);
  }, [storeTagId, selectedTagId, onTagSelect]);
}

function LoadingState() {
  return (
    <div style={centeredText}>
      <span style={{ color: 'rgb(var(--c-muted))' }}>Loading your map…</span>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div style={centeredText}>
      <strong style={{ color: 'rgb(var(--c-magenta))' }}>Failed to load your map</strong>
      <code style={{ marginTop: 8, color: 'rgb(var(--c-muted))' }}>{message}</code>
    </div>
  );
}

const centeredText: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  fontFamily: 'ui-serif, Georgia, "Times New Roman", serif',
};

const panelStyle: React.CSSProperties = {
  position: 'relative',
  flexShrink: 0,
  borderLeft: '1px solid rgb(var(--c-line) / 0.18)',
  background: 'rgb(var(--c-bg))',
  // Top padding clears the fixed h-16 (64px) TopBar that floats over; the
  // collapse toolbar sits in the strip just below it.
  padding: '68px 20px 20px',
  flexDirection: 'column',
  minHeight: 0,
};

const panelToolbarStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  flexShrink: 0,
  marginBottom: 8,
};

const panelBodyStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
};

/** Collapsed rail: the seam, the TopBar clearance, and the expand button. */
const railStyle: React.CSSProperties = {
  position: 'relative',
  width: SIDEBAR_RAIL_WIDTH,
  flexShrink: 0,
  borderLeft: '1px solid rgb(var(--c-line) / 0.18)',
  background: 'rgb(var(--c-bg))',
  padding: '68px 0 20px',
  flexDirection: 'column',
  alignItems: 'center',
  minHeight: 0,
};

// Invisible 8px grab strip on the panel's left edge (with a faint grip line),
// col-resize cursor signals it's draggable.
const resizeHandleStyle: React.CSSProperties = {
  position: 'absolute',
  left: -4,
  top: 0,
  bottom: 0,
  width: 8,
  cursor: 'col-resize',
  zIndex: 6,
  borderLeft: '2px solid rgb(var(--c-line) / 0.25)',
};
