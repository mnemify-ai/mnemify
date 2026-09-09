// On-map labels for the CURRENT hierarchy level.
//
// Each label is a cartouche: a wax-seal disc (the region's Roman numeral for
// top-level regions, a colour swatch for sub-regions) plus the region NAME
// beside it, anchored above the region's tallest peak. Top-level numerals
// match the right panel's regions list (chrome/RegionsList.tsx) so disc and
// row cross-reference — but the name is right there on the map, so users never
// have to match a colour against 27 sidebar entries.
//
// Which regions get a label depends on where the user is:
//   • Map root — the top-level regions.
//   • Inside a region — that region's IMMEDIATE children, plus the region
//     itself (lifted higher, styled as the "you are here" title) so the
//     current scope stays named. Nothing outside the open region is labelled;
//     the greyed-out terrain around it reads as background.
//
// Which of those labels render:
//   • FORCED — always: the current region; the region hovered on the terrain
//     or in the sidebar (util/hoverRegion.ts); the selected tag's home or a
//     region it also resembles; a region pulsing from the Ask agent; and,
//     when the open region has only one or two children, every child — two
//     names always fit, and making the user hover to find them is silly.
//   • PROMINENT — a small budget of the most prominent regions at this level
//     (tallest peak weighted by footprint) that fit on screen without
//     overlapping each other or a forced label. The budget grows as the camera
//     zooms in, so a map that shows ~6 names at rest reveals the rest
//     progressively.
// Everything else renders nothing, so the map stays legible and carries a
// handful of drei <Html> DOM roots instead of one per region.
//
// The prominent set is recomputed inside useFrame (the frameloop is on demand,
// so this only runs while the camera actually moves) and committed to React
// state ONLY when the set changes — no per-frame re-renders.
//
// Hovering a label lights the region's terrain + sidebar row exactly like
// hovering its terrain does; it never moves the camera. Clicking drills in.
//
// Mounted OUTSIDE the y-scale group in Scene.tsx, so peak.y is multiplied
// by the scene's Y_SCALE before being used as the label's apparent Y.

import { Html } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Vector3 } from 'three';
import type { RegionEntry, RenderData } from '../types';
import { useKnowledgeMapStore } from '../store';
import { buildTopLevelRegions } from '../util/topLevelRegions';
import { regionTerrainFor } from '../util/regionTerrain';
import { computeSiblingInfo, regionShadeHex } from '../util/regionShade';
import { useHoverRegion } from '../util/hoverRegion';
import { toRoman } from '../util/roman';
import { useTagRegionHighlight } from '../util/useTagRegionHighlight';
import { useAgentPulseRegions } from '../util/agentPulse';

/** World units the label floats above its summit. Fixed in world space,
 *  so it does NOT scale with the scene's Y_SCALE. */
const LABEL_LIFT = 2.5;
/** Extra lift for the current region's title. Its peak is (almost always) also
 *  the peak of its tallest child, so without this the two cartouches would sit
 *  on top of each other. */
const CURRENT_EXTRA_LIFT = 6;

/** Labels shown at the home framing (zoom 1) when nothing is forced. */
const BASE_LABELS = 6;
/** Budget growth per zoom: labels = BASE_LABELS * zoom^ZOOM_EXPONENT. At 2×
 *  zoom that is ~16 labels, at 3× every region on a 27-region map. */
const ZOOM_EXPONENT = 1.4;
/** With this many children or fewer, every child label is forced on. */
const FORCE_ALL_CHILDREN_AT_MOST = 2;

/** Approximate on-screen footprint of a cartouche, for overlap tests. The
 *  disc is 30px + gap; the name renders at 12px in a condensed serif, so
 *  ~6.2px per character is a safe upper estimate. */
const DISC_PX = 30;
const CHAR_PX = 6.2;
const LABEL_H_PX = 34;
const LABEL_PAD_PX = 10;
/** Names longer than this are ellipsised on the map (full name in `title`). */
const MAX_NAME_CHARS = 26;

type Rect = { x0: number; y0: number; x1: number; y1: number };

/** Width of the "REGION" kicker the current region's title carries. */
const KICKER_PX = 48;

function labelWidthPx(name: string, isCurrent: boolean): number {
  const chars = Math.min(name.length, MAX_NAME_CHARS + 1);
  return DISC_PX + 8 + chars * CHAR_PX + LABEL_PAD_PX * 2 + (isCurrent ? KICKER_PX : 0);
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
}

type ControlsLike = { target: Vector3 } | null;

/** One label candidate at the current level. */
export type LevelLabel = {
  idx: number;
  region: RegionEntry;
  /** 'top' at the map root, 'child' inside a region, 'current' for the open
   *  region's own title. */
  kind: 'top' | 'child' | 'current';
  /** 1-based slot for top-level regions (feeds toRoman); null for children. */
  numeral: number | null;
  /** Disc colour: the bake colour for top-level, sibling-shaded for children. */
  color: string;
  /** World anchor in RAW coords (y un-scaled) — the subtree's tallest hex. */
  peak: { x: number; y: number; z: number };
  /** Extra world-space lift on top of LABEL_LIFT. */
  extraLift: number;
  /** Tallest peak weighted by footprint; ranks the zoom-budgeted set. */
  prominence: number;
};

/** Pure: the label candidates for `focusRegionIdx` (null = map root). Only
 *  regions whose subtree owns terrain qualify — a phantom region has no peak
 *  to hang a label on. Exported for tests. */
export function buildLevelLabels(data: RenderData, focusRegionIdx: number | null): LevelLabel[] {
  const terrain = regionTerrainFor(data);
  if (focusRegionIdx === null) {
    return buildTopLevelRegions(data).map((top) => ({
      idx: top.idx,
      region: top.region,
      kind: 'top' as const,
      numeral: top.number,
      color: top.region.color,
      peak: top.peak,
      extraLift: 0,
      prominence: top.prominence,
    }));
  }
  const region = data.regions[focusRegionIdx];
  if (!region) return [];
  const out: LevelLabel[] = [];
  const sib = computeSiblingInfo(data.regions);

  // The open region's own title. A hexless focus (a citation into a phantom
  // region) borrows its nearest ancestor's terrain, exactly like the camera.
  const anchorIdx = terrain.resolveTerrainRegionIdx(focusRegionIdx);
  const ownPeak = anchorIdx === null ? null : terrain.peakOf(anchorIdx);
  if (ownPeak) {
    const tops = buildTopLevelRegions(data);
    const numeral = region.level === 0 ? tops.find((t) => t.idx === focusRegionIdx)?.number ?? null : null;
    out.push({
      idx: focusRegionIdx,
      region,
      kind: 'current',
      numeral,
      color: regionShadeHex(region.color, sib.depth[focusRegionIdx], sib.siblingIdx[focusRegionIdx], sib.siblingCount[focusRegionIdx]),
      peak: ownPeak,
      extraLift: CURRENT_EXTRA_LIFT,
      prominence: Number.POSITIVE_INFINITY,
    });
  }

  for (const childIdx of terrain.childrenOf(focusRegionIdx)) {
    const peak = terrain.peakOf(childIdx);
    if (!peak) continue;
    const hexCount = terrain.hexCountOf(childIdx);
    out.push({
      idx: childIdx,
      region: data.regions[childIdx],
      kind: 'child',
      numeral: null,
      color: regionShadeHex(data.regions[childIdx].color, sib.depth[childIdx], sib.siblingIdx[childIdx], sib.siblingCount[childIdx]),
      peak,
      extraLift: 0,
      prominence: peak.y * (1 + Math.log(Math.max(1, hexCount))),
    });
  }
  return out;
}

export function RegionLabels({
  data,
  yScale,
  homeLookDist,
}: {
  data: RenderData;
  /** Same Y_SCALE the HexField group uses — peak heights are raw world units. */
  yScale: number;
  /** Camera distance at the home framing (Scene's layout.lookDist). The
   *  ratio home/current is the zoom that grows the label budget. */
  homeLookDist: number;
}) {
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const setLegendHover = useKnowledgeMapStore((s) => s.setLegendHover);
  const hover = useHoverRegion(data);
  const highlight = useTagRegionHighlight(data);
  const agentPulsing = useAgentPulseRegions(data);

  const labels = useMemo(() => buildLevelLabels(data, focusRegionIdx), [data, focusRegionIdx]);
  const childCount = useMemo(
    () => labels.reduce((n, l) => n + (l.kind === 'child' ? 1 : 0), 0),
    [labels],
  );

  // Regions that must render regardless of zoom / overlap.
  const forced = useMemo(() => {
    const set = new Set<number>();
    const forceAllChildren = childCount > 0 && childCount <= FORCE_ALL_CHILDREN_AT_MOST;
    for (const l of labels) {
      if (
        l.kind === 'current' ||
        (l.kind === 'child' && forceAllChildren) ||
        hover.idx === l.idx ||
        highlight.homeIdx === l.idx ||
        highlight.related.has(l.idx) ||
        agentPulsing.has(l.idx)
      ) set.add(l.idx);
    }
    return set;
  }, [labels, childCount, hover.idx, highlight, agentPulsing]);

  // Prominence order, computed once per level.
  const byProminence = useMemo(
    () => [...labels].sort((a, b) => b.prominence - a.prominence),
    [labels],
  );

  // ── Zoom-aware prominent set ────────────────────────────────────────────────
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as ControlsLike;
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const [prominent, setProminent] = useState<Set<number>>(() => new Set());
  const prominentKey = useRef('');
  // Latest inputs for the frame callback without re-subscribing it.
  const frameInputs = useRef({ forced, byProminence, homeLookDist, yScale, size });
  frameInputs.current = { forced, byProminence, homeLookDist, yScale, size };
  const scratch = useRef(new Vector3());

  // A forced-set change (hover, focus, tag select) shifts what fits around the
  // forced labels, and a new bake / level needs a first pass — kick one frame
  // so the demand frameloop actually runs the placement below.
  useEffect(() => { invalidate(); }, [forced, byProminence, size, invalidate]);

  useFrame(() => {
    const { forced: f, byProminence: ranked, homeLookDist: home, yScale: ys, size: sz } =
      frameInputs.current;
    if (ranked.length === 0) return;

    const target = controls?.target;
    const dist = target ? camera.position.distanceTo(target) : home;
    const zoom = Math.max(1, home / Math.max(dist, 1e-3));
    const budget = Math.min(
      ranked.length,
      Math.max(BASE_LABELS, Math.round(BASE_LABELS * Math.pow(zoom, ZOOM_EXPONENT))),
    );

    const project = (l: LevelLabel): Rect | null => {
      const v = scratch.current.set(l.peak.x, l.peak.y * ys + LABEL_LIFT + l.extraLift, l.peak.z);
      v.project(camera);
      if (v.z > 1 || v.z < -1) return null;   // behind the camera / past far plane
      const px = ((v.x + 1) / 2) * sz.width;
      const py = ((1 - v.y) / 2) * sz.height;
      const w = labelWidthPx(l.region.name, l.kind === 'current');
      const h = LABEL_H_PX;
      // <Html center> centres the label on the anchor.
      const r: Rect = { x0: px - w / 2, y0: py - h / 2, x1: px + w / 2, y1: py + h / 2 };
      if (r.x1 < 0 || r.y1 < 0 || r.x0 > sz.width || r.y0 > sz.height) return null;
      return r;
    };

    // Forced labels claim their screen space first; they render no matter what.
    const taken: Rect[] = [];
    for (const l of ranked) {
      if (!f.has(l.idx)) continue;
      const r = project(l);
      if (r) taken.push(r);
    }

    // Then fill the budget by prominence, skipping anything that would collide.
    const next: number[] = [];
    for (const l of ranked) {
      if (next.length >= budget) break;
      if (f.has(l.idx)) continue;
      const r = project(l);
      if (!r) continue;
      if (taken.some((t) => overlaps(t, r))) continue;
      taken.push(r);
      next.push(l.idx);
    }

    const key = next.join(',');
    if (key !== prominentKey.current) {
      prominentKey.current = key;
      setProminent(new Set(next));
    }
  });

  return (
    <>
      {labels.map((l) => {
        const isForced = forced.has(l.idx);
        if (!isForced && !prominent.has(l.idx)) return null;
        const isCurrent = l.kind === 'current';
        const isHome = highlight.homeIdx === l.idx;
        const isRelated = highlight.related.has(l.idx);
        const isHovered = hover.idx === l.idx;
        // The Ask agent's live exploration wins the ring while it lasts — it's
        // transient (a few seconds) and the whole point is seeing where the
        // assistant is looking right now. Otherwise: related regions get a
        // pulsing magenta ring; the selected tag's home region gets a steady
        // ring so it reads as the anchor, not a sibling.
        const isAgentPulsing = agentPulsing.has(l.idx);
        // A label revealed purely by terrain hover is anchored above the
        // region's summit and can land under the cursor — swallowing the
        // pointer ends the hex hover, which unmounts the label and blinks the
        // tooltip with it. Clicking the hex itself already drills into the
        // region, so a hover-only label stays passive.
        const hoverOnly =
          isHovered &&
          hover.source === 'terrain' &&
          !prominent.has(l.idx) &&
          !(isCurrent || isHome || isRelated || isAgentPulsing) &&
          !(l.kind === 'child' && childCount <= FORCE_ALL_CHILDREN_AT_MOST);
        const ringStyle: React.CSSProperties = isAgentPulsing
          ? { outline: '2px solid', outlineOffset: 3, outlineColor: 'rgb(var(--c-sage) / 0.85)', animation: 'agent-pulse-ring 1.1s ease-in-out infinite' }
          : isRelated
            ? { outline: '2px solid', outlineOffset: 3, outlineColor: 'rgb(var(--c-magenta) / 0)', animation: 'region-pulse-ring 1.5s ease-in-out infinite' }
            : isHome
              ? { outline: '2px solid', outlineOffset: 3, outlineColor: 'rgb(var(--c-magenta) / 0.7)' }
              : {};
        const emphasised = isCurrent || isHovered || isHome || isRelated || isAgentPulsing;
        const name = l.region.name.length > MAX_NAME_CHARS
          ? l.region.name.slice(0, MAX_NAME_CHARS - 1).trimEnd() + '…'
          : l.region.name;
        return (
          <Html
            key={`${l.kind}:${l.region.id}`}
            position={[l.peak.x, l.peak.y * yScale + LABEL_LIFT + l.extraLift, l.peak.z]}
            center
            // Emphasised labels sit above resting ones so a hovered name is
            // never hidden under a neighbour's prominent label.
            zIndexRange={emphasised ? [20, 10] : [10, 0]}
            // Fade the label in on appear (the <Html> remounts each time it
            // becomes visible). Set here rather than on the button, whose
            // inline `animation` for the pulse rings would clobber it.
            className="animate-fade-in motion-reduce:animate-none"
            style={{
              pointerEvents: hoverOnly ? 'none' : 'auto',
              userSelect: 'none',
            }}
          >
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                // Route through the nav layer so label clicks record history
                // (Back works) and the camera zooms on focus change. The
                // current region's title steps back OUT one level; a child /
                // top-level label drills IN — same as clicking its terrain.
                if (isCurrent) {
                  const parent = l.region.parentIdx >= 0 ? l.region.parentIdx : null;
                  navigate({ focusRegionIdx: parent, selectedTagId: null, docNoteId: null });
                } else {
                  navigate({ focusRegionIdx: l.idx, selectedTagId: null, docNoteId: null });
                }
              }}
              // Hovering the label lights the matching sidebar row AND the
              // region's terrain, exactly like hovering the terrain does.
              onMouseEnter={() => setLegendHover(l.idx)}
              onMouseLeave={() => setLegendHover(null)}
              title={isCurrent ? `${l.region.name} — click to step out` : l.region.name}
              style={{
                ...cartoucheStyle,
                borderColor: isCurrent
                  ? 'rgb(var(--c-magenta) / 0.85)'
                  : isHovered
                    ? 'rgb(var(--c-ink) / 0.45)'
                    : 'rgb(var(--c-line) / 0.35)',
                transform: isCurrent ? 'scale(1.06)' : isHovered ? 'scale(1.04)' : 'scale(1)',
                opacity: emphasised || prominent.has(l.idx) ? 1 : 0.92,
                ...ringStyle,
              }}
            >
              <span
                style={{
                  ...discStyle,
                  // Region colour comes from the bake — stays inline. A child
                  // (no numeral) shows the swatch itself, filled.
                  background: l.numeral === null ? l.color : 'rgb(var(--c-bg) / 0.95)',
                  boxShadow: `inset 0 0 0 2px ${l.color}, 0 1px 3px rgb(0 0 0 / 0.25)`,
                }}
              >
                {l.numeral !== null ? toRoman(l.numeral) : ''}
              </span>
              <span style={nameStyle}>
                {isCurrent && <span style={kickerStyle}>Region</span>}
                {name}
              </span>
            </button>
          </Html>
        );
      })}
    </>
  );
}

const cartoucheStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 7,
  height: LABEL_H_PX,
  padding: `0 ${LABEL_PAD_PX + 2}px 0 3px`,
  borderRadius: LABEL_H_PX / 2,
  background: 'rgb(var(--c-bg) / 0.9)',
  border: '1px solid rgb(var(--c-line) / 0.35)',
  boxShadow:
    '0 2px 8px rgb(0 0 0 / 0.28), inset 0 1px 0 rgb(255 255 255 / 0.18)',
  color: 'rgb(var(--c-ink))',
  cursor: 'pointer',
  backdropFilter: 'blur(6px)',
  WebkitBackdropFilter: 'blur(6px)',
  whiteSpace: 'nowrap',
  transition: 'transform 140ms ease, border-color 140ms ease, opacity 140ms ease',
};

const discStyle: React.CSSProperties = {
  width: DISC_PX - 2,
  height: DISC_PX - 2,
  borderRadius: '50%',
  background: 'rgb(var(--c-bg) / 0.95)',
  display: 'grid',
  placeItems: 'center',
  fontFamily: 'ui-serif, "Newsreader", Georgia, serif',
  fontSize: 12,
  fontStyle: 'italic',
  fontWeight: 600,
  letterSpacing: '0.04em',
  flexShrink: 0,
};

const nameStyle: React.CSSProperties = {
  fontFamily: 'ui-serif, "Newsreader", Georgia, serif',
  fontSize: 12.5,
  fontWeight: 500,
  letterSpacing: '0.01em',
  lineHeight: 1,
  display: 'inline-flex',
  alignItems: 'baseline',
  gap: 6,
};

const kickerStyle: React.CSSProperties = {
  fontSize: 9,
  fontStyle: 'normal',
  fontWeight: 600,
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: 'rgb(var(--c-magenta) / 0.9)',
};
