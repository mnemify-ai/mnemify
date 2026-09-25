// Renders all owned hexes as a single InstancedMesh of hex prisms.
// Per-instance: position (x, y/2, z), scale (height on y-axis), colour.
// One draw call for ~20k hexes — trivial for instanced WebGL.
//
// Also handles raycasting (pointer over/move/out, click). Three.js gives
// us `instanceId` on InstancedMesh hits; we map that to the raw hex
// 5-tuple via `instanceLookup`.

import { useMemo, useRef, useEffect } from 'react';
import {
  Color, InstancedMesh, Object3D, CylinderGeometry, MeshStandardMaterial,
} from 'three';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import type { RenderData } from '../types';
import { hexToWorld } from '../util/hexGeometry';
import { useKnowledgeMapStore } from '../store';
import type { Theme } from '../util/useTheme';
import { computeSiblingInfo, shadeColor } from '../util/regionShade';
import { regionTerrainFor } from '../util/regionTerrain';
import { resolveHoverChild } from '../util/hoverRegion';
import { isClickNotDrag } from '../util/pointerGesture';
import { HIGHLIGHT_ACCENT } from './HighlightBeacons';

const HEX_FIELDS_PER_HEX = 5;

export function HexField({ data, theme = 'light' }: { data: RenderData; theme?: Theme }) {
  const ref = useRef<InstancedMesh>(null);
  // Demand frameloop: imperative instance-buffer writes below bypass React,
  // so each effect must request a frame after mutating.
  const invalidate = useThree((s) => s.invalidate);
  const setHoveredInstance = useKnowledgeMapStore((s) => s.setHoveredInstance);
  const setHoveredHexMeta = useKnowledgeMapStore((s) => s.setHoveredHexMeta);
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const setTagSummitPos = useKnowledgeMapStore((s) => s.setTagSummitPos);
  const hoveredInstanceId = useKnowledgeMapStore((s) => s.hoveredInstanceId);
  const legendHoverIdx = useKnowledgeMapStore((s) => s.legendHoverIdx);
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const askHighlight = useKnowledgeMapStore((s) => s.askHighlight);

  // Decode hexes once per data load. Returns per-instance buffers + a
  // lookup so picker handlers can map instanceId → raw hex offset. Theme
  // is a memo dep so hex pigments re-bake when the user toggles dark mode.
  const decoded = useMemo(() => decodeHexes(data, theme), [data, theme]);
  const baseColors = decoded.colors;       // immutable per-instance base colour

  // Region → the terrain it actually occupies. Focus can land on a region whose
  // whole subtree owns no hexes (47 of 106 in the current bake), and testing
  // subtree membership against such an index matches nothing — which used to
  // grey EVERY hex. See util/regionTerrain.ts.
  const terrain = useMemo(() => regionTerrainFor(data), [data]);

  // Publish tag → summit-position so overlays (TagRelationPopover) can anchor
  // to a tag without reaching into this component's decode internals.
  useEffect(() => {
    setTagSummitPos(decoded.tagSummitPos);
  }, [decoded, setTagSummitPos]);

  // displayColors = baseColors modulated by the current focus selection (glow
  // on the focused subtree, dim on the rest). The hover highlight then
  // brightens/restores RELATIVE to displayColors, so focus-dim and hover never
  // fight. Rebuilt whenever decode changes; repainted on focus change.
  const displayColors = useRef<Float32Array>(new Float32Array(0));

  // Set per-instance transforms once per decode. Colour is owned by the focus
  // effect below (which also runs on mount, focus = null → base colours).
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const { positions, heights } = decoded;
    const count = positions.length / 2;
    for (let i = 0; i < count; i++) {
      const x = positions[i * 2];
      const z = positions[i * 2 + 1];
      const h = Math.max(0.1, heights[i]);
      dummy.position.set(x, h / 2, z);
      dummy.scale.set(1, h, 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [decoded, invalidate]);

  // Focus selection: when a region (top-level OR sub-region) is focused, glow
  // its subtree and dim everything else so the selection reads clearly on the
  // map; when focus clears, every hex returns to its base colour. Writes the
  // shared displayColors buffer, then paints all instances in one pass (focus
  // changes are rare and click-driven).
  const FOCUS_GLOW = 1.14;
  // Out-of-focus regions are pulled toward their own grey (luminance) and dimmed,
  // so the focused region reads in full colour while everything else recedes.
  const GREY_MIX = 0.88;   // 0 = keep colour, 1 = full greyscale
  const GREY_DIM = 0.5;    // overall darkening of the greyed regions
  // Ask-answer highlight. Cited spires are pulled most of the way to the hot
  // accent (HIGHLIGHT_ACCENT — a hue no region uses) and pushed past bloom
  // threshold; the regions they sit in keep their colour at full strength;
  // everything else goes near-monochrome and dark. The contrast is
  // deliberately harder than the focus grey: at the home framing a subtle
  // brighten of the region tint was invisible, and the whole point is to read
  // the answer's footprint at a glance. HighlightBeacons adds orbs on top.
  const HL_ACCENT = new Color(HIGHLIGHT_ACCENT);
  const HL_ACCENT_MIX = 0.7;
  const HL_GLOW = 1.35;
  const HL_LIFT = 0.12;
  const HL_REGION_GLOW = 1.08;
  const HL_GREY_MIX = 0.92;
  const HL_GREY_DIM = 0.36;
  const prevHoverTopRef = useRef<number | null>(null);
  useEffect(() => {
    const mesh = ref.current;
    // NOTE: don't guard on mesh.instanceColor here — it's null until the first
    // setColorAt() call, which three.js allocates lazily inside the loop below.
    // This effect is the sole owner of instance colours, so it must run on
    // first mount to bootstrap that buffer.
    if (!mesh) return;
    const { instanceLookup } = decoded;
    const { ancestorsOf } = terrain;
    const count = instanceLookup.length;
    let buf = displayColors.current;
    if (buf.length !== count * 3) buf = displayColors.current = new Float32Array(count * 3);

    // Dim against the terrain the focused region actually occupies: its own
    // hexes when it has them, otherwise its nearest ancestor's. `null` means
    // nothing in this bake's hex field contains it — leave the map alone rather
    // than greying the whole world for a selection nothing can highlight.
    const dimAgainst = terrain.resolveTerrainRegionIdx(focusRegionIdx);

    // Region indices (any level) the highlight keeps in colour: the cited
    // regions themselves plus every region a cited spire stands in.
    const hlTags = askHighlight?.tagIds ?? null;
    const hlRegions = new Set<number>(askHighlight?.regionIdxs ?? []);
    if (hlTags) {
      for (let i = 0; i < count; i++) {
        const t = instanceLookup[i].tagId;
        if (t !== null && hlTags.has(t)) hlRegions.add(instanceLookup[i].regionIdx);
      }
    }
    const hlActive = hlTags !== null && (hlTags.size > 0 || hlRegions.size > 0);

    const c = new Color();
    for (let i = 0; i < count; i++) {
      const r = baseColors[i * 3], g = baseColors[i * 3 + 1], b = baseColors[i * 3 + 2];
      let cr: number, cg: number, cb: number;
      const meta = instanceLookup[i];
      const inFocus =
        dimAgainst === null || (ancestorsOf[meta.regionIdx]?.includes(dimAgainst) ?? false);
      if (hlActive) {
        const litTag = meta.tagId !== null && hlTags!.has(meta.tagId);
        let litRegion = false;
        if (!litTag) {
          for (const a of ancestorsOf[meta.regionIdx] ?? []) {
            if (hlRegions.has(a)) { litRegion = true; break; }
          }
        }
        if (litTag) {
          const mr = r + (HL_ACCENT.r - r) * HL_ACCENT_MIX;
          const mg = g + (HL_ACCENT.g - g) * HL_ACCENT_MIX;
          const mb = b + (HL_ACCENT.b - b) * HL_ACCENT_MIX;
          cr = Math.min(1, mr * HL_GLOW + HL_LIFT);
          cg = Math.min(1, mg * HL_GLOW + HL_LIFT);
          cb = Math.min(1, mb * HL_GLOW + HL_LIFT);
        } else if (litRegion && inFocus) {
          cr = Math.min(1, r * HL_REGION_GLOW);
          cg = Math.min(1, g * HL_REGION_GLOW);
          cb = Math.min(1, b * HL_REGION_GLOW);
        } else {
          const lum = 0.299 * r + 0.587 * g + 0.114 * b;
          cr = (r + (lum - r) * HL_GREY_MIX) * HL_GREY_DIM;
          cg = (g + (lum - g) * HL_GREY_MIX) * HL_GREY_DIM;
          cb = (b + (lum - b) * HL_GREY_MIX) * HL_GREY_DIM;
        }
      } else if (dimAgainst === null) {
        cr = r; cg = g; cb = b;
      } else if (inFocus) {
        // Focused subtree: keep full colour with a slight glow.
        cr = Math.min(1, r * FOCUS_GLOW + 0.02);
        cg = Math.min(1, g * FOCUS_GLOW + 0.02);
        cb = Math.min(1, b * FOCUS_GLOW + 0.02);
      } else {
        // Everything else: desaturate toward its grey and dim.
        const lum = 0.299 * r + 0.587 * g + 0.114 * b;
        cr = (r + (lum - r) * GREY_MIX) * GREY_DIM;
        cg = (g + (lum - g) * GREY_MIX) * GREY_DIM;
        cb = (b + (lum - b) * GREY_MIX) * GREY_DIM;
      }
      buf[i * 3] = cr; buf[i * 3 + 1] = cg; buf[i * 3 + 2] = cb;
      mesh.setColorAt(i, c.setRGB(cr, cg, cb));   // allocates instanceColor on i=0
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    // The repaint blew away any hover brighten; let the hover effect re-apply
    // cleanly on the next pointer move.
    prevHoverTopRef.current = null;
    invalidate();
  }, [decoded, terrain, baseColors, focusRegionIdx, askHighlight, invalidate]);

  // Hover highlight: brighten the whole footprint of the region under the
  // cursor AT THE CURRENT LEVEL — the top-level region at the map root, the
  // immediate child of the focused region once inside one — so moving the
  // mouse "lights up" exactly the units the user can drill into next. The
  // sidebar feeds the same effect: hovering a row (legendHoverIdx) lights that
  // region's terrain too. Only repaints when the resolved region changes
  // (moving within a region is a no-op), and restores the previous region to
  // its DISPLAY colour (which already reflects focus). Hover never touches
  // focus or the camera — see util/hoverRegion.ts.
  const HOVER_BRIGHTEN = 1.5;
  const hoveredLeaf = (hoveredInstanceId !== null && hoveredInstanceId >= 0)
    ? decoded.instanceLookup[hoveredInstanceId]?.regionIdx ?? null
    : null;
  const hoverTarget =
    resolveHoverChild(terrain.ancestorsOf, hoveredLeaf, focusRegionIdx) ?? legendHoverIdx;
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh || !mesh.instanceColor) return;
    const lookup = decoded.instanceLookup;
    const buf = displayColors.current;
    if (buf.length !== lookup.length * 3) return;   // focus effect not yet run
    const newTop = hoverTarget;
    const prevTop = prevHoverTopRef.current;
    if (newTop === prevTop) return;

    const c = new Color();
    const restore = (i: number) => mesh.setColorAt(i, c.setRGB(
      buf[i * 3], buf[i * 3 + 1], buf[i * 3 + 2],
    ));
    const brighten = (i: number) => mesh.setColorAt(i, c.setRGB(
      Math.min(1, buf[i * 3] * HOVER_BRIGHTEN + 0.04),
      Math.min(1, buf[i * 3 + 1] * HOVER_BRIGHTEN + 0.04),
      Math.min(1, buf[i * 3 + 2] * HOVER_BRIGHTEN + 0.04),
    ));

    if (prevTop !== null) (decoded.instancesByRegion.get(prevTop) ?? []).forEach(restore);
    if (newTop !== null) (decoded.instancesByRegion.get(newTop) ?? []).forEach(brighten);
    mesh.instanceColor.needsUpdate = true;
    prevHoverTopRef.current = newTop;
    invalidate();
    // focusRegionIdx: the focus repaint above resets prevHoverTopRef, so a hover
    // that survives a focus change (sidebar row still under the pointer) must
    // re-apply on top of the fresh display colours.
  }, [hoverTarget, decoded, baseColors, focusRegionIdx, askHighlight, invalidate]);

  const geometry = useMemo(() => {
    const radius = (2 * data.hexSize) / Math.sqrt(3);
    return new CylinderGeometry(radius, radius, 1, 6, 1);
  }, [data.hexSize]);

  const material = useMemo(
    () => new MeshStandardMaterial({ roughness: 0.85, metalness: 0.0, flatShading: true }),
    [],
  );

  // ---- Raycast handlers ----
  // Hover surfaces two things to the store:
  //   • hoveredInstanceId   — drives the brightness highlight (this file)
  //   • hoveredHexMeta      — drives the screen-space tooltip (HexTooltip.tsx)
  // The tooltip uses cursor-anchored DOM positioning rather than a drei
  // <Html follow>; that keeps the tooltip outside the R3F render loop and
  // means no per-frame projection cost. Meta only changes when the cursor
  // crosses a hex boundary, so updates here are rare.
  const onMove = (e: ThreeEvent<PointerEvent>) => {
    const id = e.instanceId;
    if (id === undefined || id === null) return;
    e.stopPropagation();
    if (id !== hoveredInstanceId) {
      setHoveredInstance(id);
      const meta = decoded.instanceLookup[id];
      if (meta) {
        setHoveredHexMeta({ regionIdx: meta.regionIdx, tagId: meta.tagId });
      } else {
        setHoveredHexMeta(null);
      }
    }
    document.body.style.cursor = 'pointer';
  };
  const onOut = () => {
    setHoveredInstance(null);
    setHoveredHexMeta(null);
    document.body.style.cursor = 'default';
  };
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    const id = e.instanceId;
    if (id === undefined || id === null) return;
    // Swallow the click either way — a drag-release must not fall through to
    // whatever else the ray pierced under the terrain — but only ACT on it if
    // the pointer barely moved since pointerdown. The browser fires `click` at
    // the end of every orbit gesture too, and r3f re-raycasts at the RELEASE
    // position, so without this guard rotating the camera drills into
    // whichever hex you happened to let go over. See util/pointerGesture.ts.
    // Guarding here rather than per-branch covers BOTH navigate() calls below.
    e.stopPropagation();
    if (!isClickNotDrag(e.delta)) return;
    const meta = decoded.instanceLookup[id];
    if (!meta) return;
    setHoveredHexMeta(null);   // don't let the hover tooltip linger

    // DRILL ORDER: a click always advances ONE step down the hierarchy, and a
    // tag only opens once you're already focused on that hex's own region:
    //   Map root → clicked hex's TOP-LEVEL region
    //   focused on an ancestor → one level deeper toward the hex
    //   focused on a different branch → that hex's top-level (reset)
    //   focused on the hex's leaf region + hex has a tag → select the tag
    // This keeps the first click on the map from jumping straight to a tag.
    const chain: number[] = [];          // leaf → … → top-level
    let cur: number = meta.regionIdx;
    while (cur >= 0) {
      chain.push(cur);
      cur = data.regions[cur].parentIdx;
    }
    const top = chain[chain.length - 1];

    if (focusRegionIdx === meta.regionIdx && meta.tagId !== null) {
      // Already at the hex's own region → the tag is the next step. Focus stays,
      // so the map stays scoped; navigate() records history for Back.
      navigate({ selectedTagId: meta.tagId });
      return;
    }

    let nextFocus: number;
    if (focusRegionIdx === null) {
      nextFocus = top;
    } else {
      const focusInChain = chain.indexOf(focusRegionIdx);
      if (focusInChain === -1) nextFocus = top;                        // reset to top
      else if (focusInChain > 0) nextFocus = chain[focusInChain - 1];  // drill one
      else nextFocus = focusRegionIdx;                                 // at leaf, no tag
    }
    // navigate zooms the camera when focus changes (one-shot, see CameraAnimator).
    navigate({ focusRegionIdx: nextFocus, selectedTagId: null, docNoteId: null });
  };

  return (
    <instancedMesh
      ref={ref}
      args={[geometry, material, decoded.heights.length]}
      castShadow
      receiveShadow
      onPointerMove={onMove}
      onPointerOut={onOut}
      onClick={onClick}
    />
  );
}

type InstanceMeta = {
  rawHexOffset: number;       // index into data.hexes (multiple of 5)
  regionIdx: number;          // leaf region
  topLevelIdx: number;        // walked up to the root node
  tagId: string | null;
};

// Paper / desk anchors for the "dusty" hex tint. Region colours get pulled
// 22% toward whichever anchor matches the current theme — this both
// desaturates the palette and ensures pigments sit darker than the sepia
// paper (light) or brighter than the leather desk (dark).
const PAPER_LIGHT = new Color('#E6D3AC');
const DESK_DARK = new Color('#3D3340');

/** Convert the flat hexes array into per-instance buffers + lookup. */
function decodeHexes(data: RenderData, theme: Theme = 'light') {
  const { hexes, hexSize, regions, bounds } = data;
  const count = hexes.length / HEX_FIELDS_PER_HEX;
  const positions = new Float32Array(count * 2);
  const heights = new Float32Array(count);
  const colors = new Float32Array(count * 3);
  const instanceLookup: InstanceMeta[] = [];
  // region idx (ANY level) → the instance indices in its subtree, for the
  // hover highlight. A hex is filed under every region on its ancestor chain,
  // so brightening a parent lights all of its descendants' terrain.
  const instancesByRegion = new Map<number, number[]>();
  // tag.id → summit-hex world position (tallest hex carrying that tag), in
  // RAW world coords — y is left UN-SCALED, so consumers mounted outside
  // Scene's y-scale group must multiply by yScale themselves.
  const tagSummitPos = new Map<string, { x: number; y: number; z: number }>();

  // Pre-compute top-level region for every region so we don't walk the
  // chain on every click.
  const topOfRegion = new Int32Array(regions.length);
  const chainOf: number[][] = [];
  for (let i = 0; i < regions.length; i++) {
    const chain: number[] = [];
    let cur = i;
    while (cur >= 0 && chain.length <= regions.length) {
      chain.push(cur);
      cur = regions[cur].parentIdx;
    }
    chainOf.push(chain);
    topOfRegion[i] = chain[chain.length - 1];
  }

  // Depth + sibling position drive per-sub-region shading (see regionShade.ts).
  const sib = computeSiblingInfo(regions);

  // Region tints — two-stage "dusty" pipeline:
  //   1. Desaturate ~30% in HSL so the palette feels weathered/pigmented
  //      rather than plastic-saturated.
  //   2. Pull 22% toward a theme-matched anchor so islands sit darker than
  //      the sepia paper (light) or brighter than the leather desk (dark),
  //      giving a consistent paper↔hex contrast either way.
  const anchor = theme === 'dark' ? DESK_DARK : PAPER_LIGHT;
  const regionTints = regions.map((r, i) => {
    // 1. Shade the inherited colour by depth/sibling so sub-regions read as
    //    distinct-but-related variants within the parent's hue family.
    const c = shadeColor(new Color(r.color), sib.depth[i], sib.siblingIdx[i], sib.siblingCount[i]);
    // 2. Keep most of the saturation so colours stay vibrant, with only a light
    //    pull toward the theme anchor for paper/desk cohesion (was a heavy
    //    0.70× desaturation + 0.22 anchor lerp, which washed everything out).
    const hsl = { h: 0, s: 0, l: 0 };
    c.getHSL(hsl);
    c.setHSL(hsl.h, Math.min(1, hsl.s * 0.95), hsl.l);
    return c.lerp(anchor, 0.10);
  });

  // Muted, dimmed region tint used as the high-elevation target for NO-TAG
  // filler terrain. Lower saturation + lightness so plain terrain reads as
  // quiet background territory, well below the vivid tag spires — "colour means
  // a topic lives here" at a glance.
  const fillerHi = regionTints.map((t) => {
    const c = t.clone();
    const hsl = { h: 0, s: 0, l: 0 };
    c.getHSL(hsl);
    // Lightness 0.55× → 0.72×: dark filler plateaus read as brown crust
    // around every island. Still clearly muted next to the tag spires.
    c.setHSL(hsl.h, hsl.s * 0.45, hsl.l * 0.72);
    return c;
  });

  // God-tag set — these CENTER hexes get a brighter, vivid colour so the
  // Bloom post-process catches them as glowing peaks (Step 19).
  const godSet = new Set(data.highlights.godTagIds);

  // Per-tag we track the centre = the hex with that tagIdx and max height.
  // Without scanning twice, we approximate: centre = first encountered hex
  // with that tagIdx whose height equals the maximum we've seen for it.
  // Easier to just find the maxima in a first pass then mark in second pass.
  const tagMaxHeight = new Map<number, number>();
  // Per TOP-LEVEL region, the min/max height across its TAG hexes — used to
  // normalize tag darkness within a region (taller tag spire = darker).
  const regTagMin = new Map<number, number>();
  const regTagMax = new Map<number, number>();
  for (let i = 0; i < count; i++) {
    const base = i * HEX_FIELDS_PER_HEX;
    const tagIdx = hexes[base + 4];
    const regionIdx = hexes[base + 2];
    const h = hexes[base + 3];
    if (tagIdx < 0 || regionIdx < 0) continue;
    const prev = tagMaxHeight.get(tagIdx);
    if (prev === undefined || h > prev) tagMaxHeight.set(tagIdx, h);
    const top = topOfRegion[regionIdx];
    const mn = regTagMin.get(top);
    if (mn === undefined || h < mn) regTagMin.set(top, h);
    const mx = regTagMax.get(top);
    if (mx === undefined || h > mx) regTagMax.set(top, h);
  }

  const maxY = Math.max(bounds.maxY, 1);
  // Tag darkness ramp: shortest tag in a region ≈ BASE_DARK, tallest ≈
  // BASE_DARK+HEIGHT_DARK darker. Per-region so each region self-normalizes.
  // Kept gentle (high floor) so tag spires stay vivid — they're the signal that
  // a hex carries a topic; only relative height still reads via mild shading.
  const BASE_DARK = 0.04;
  const HEIGHT_DARK = 0.24;   // was 0.34 — tallest spires kept going dusky
  const TAG_FLOOR = 0.62;

  let writeI = 0;
  for (let i = 0; i < count; i++) {
    const base = i * HEX_FIELDS_PER_HEX;
    const q = hexes[base];
    const r = hexes[base + 1];
    const regionIdx = hexes[base + 2];
    const h = hexes[base + 3];
    const tagIdx = hexes[base + 4];

    if (regionIdx < 0) continue;
    const [x, z] = hexToWorld(q, r, hexSize);
    positions[writeI * 2] = x;
    positions[writeI * 2 + 1] = z;
    heights[writeI] = h;

    const t = Math.max(0, Math.min(1, h / maxY));
    const isTag = tagIdx >= 0;
    const tagId = isTag ? data.tagIndex[tagIdx] : null;
    const isGod = isTag && tagId !== null && godSet.has(tagId);
    const isSummit = isTag && h === tagMaxHeight.get(tagIdx);
    const isGodCentre = isGod && isSummit;
    if (isTag && tagId !== null && isSummit && !tagSummitPos.has(tagId)) {
      tagSummitPos.set(tagId, { x, y: h, z });
    }

    const tint = regionTints[regionIdx];
    let cr: number, cg: number, cb: number;
    if (isGodCentre) {
      // Vivid, near-saturated region colour — pushes pixel luminance over
      // bloom threshold so god-tag summits glow.
      cr = Math.min(1, tint.r * 1.45 + 0.10);
      cg = Math.min(1, tint.g * 1.45 + 0.10);
      cb = Math.min(1, tint.b * 1.45 + 0.10);
    } else if (isTag) {
      // Tag hex: darken by its height normalized within the region — taller
      // spires read darker, self-scaled to each region's own min/max.
      const top = topOfRegion[regionIdx];
      const mn = regTagMin.get(top) ?? 0;
      const mx = regTagMax.get(top) ?? maxY;
      const norm = mx > mn ? (h - mn) / (mx - mn) : 0;
      const brightness = Math.max(TAG_FLOOR, 1.0 - (BASE_DARK + HEIGHT_DARK * norm));
      cr = tint.r * brightness;
      cg = tint.g * brightness;
      cb = tint.b * brightness;
    } else {
      // Elevation ramp: warm sandy floor at t=0 blends toward a MUTED region
      // tint at t=1. Low terrain reads as parchment; elevation hints at the
      // region's colour but stays quiet so it never competes with tag spires.
      // Lifted from #C4A96B (a fairly dark sand) to #DCC79A so the floor of
      // each island sits close to the paper instead of ringing it in brown.
      const GROUND_R = 0.863, GROUND_G = 0.780, GROUND_B = 0.604;
      const hi = fillerHi[regionIdx];
      const mix = Math.min(1, t * 2.0);
      cr = GROUND_R + (hi.r - GROUND_R) * mix;
      cg = GROUND_G + (hi.g - GROUND_G) * mix;
      cb = GROUND_B + (hi.b - GROUND_B) * mix;
    }
    colors[writeI * 3]     = cr;
    colors[writeI * 3 + 1] = cg;
    colors[writeI * 3 + 2] = cb;

    const topIdx = topOfRegion[regionIdx];
    instanceLookup.push({
      rawHexOffset: base,
      regionIdx,
      topLevelIdx: topIdx,
      tagId,
    });
    for (const a of chainOf[regionIdx]) {
      const bucket = instancesByRegion.get(a);
      if (bucket) bucket.push(writeI);
      else instancesByRegion.set(a, [writeI]);
    }
    writeI++;
  }

  return {
    positions: positions.subarray(0, writeI * 2),
    heights: heights.subarray(0, writeI),
    colors: colors.subarray(0, writeI * 3),
    instanceLookup,
    instancesByRegion,
    tagSummitPos,
  };
}
