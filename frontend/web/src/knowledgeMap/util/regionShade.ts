// Sub-region shading. The backend assigns a `color` only to top-level regions;
// every sub-region inherits its parent's colour, so siblings are visually
// identical on the map and in the panel. To make nesting legible we derive a
// distinct-but-related shade per region from its DEPTH + SIBLING INDEX (not the
// colour value, which is shared). Shades stay inside the parent's hue family —
// a bounded lightness step plus a small hue nudge — and are depth-capped so
// nested shifts don't compound into mud.
//
// Both the hex field (HexField.decodeHexes) and the right panel's sub-region
// list import from here so a sub-region's swatch matches its hexes on the map.

import { Color } from 'three';

/** Max lightness offset (HSL L) applied to the outermost sibling. */
export const SHADE_LIGHT_STEP = 0.07;
/** Max hue offset (fraction of the wheel) applied to the outermost sibling. */
export const SHADE_HUE_STEP = 0.018;
/** Levels deeper than this reuse the depth-2 magnitude (no further compounding). */
const DEPTH_CAP = 2;
/** Keep shaded lightness inside a readable band. */
const L_MIN = 0.2;
const L_MAX = 0.82;

export type SiblingInfo = {
  /** Tree depth: 0 = top-level region, 1+ = sub-region. */
  depth: Int32Array;
  /** Index of a region among siblings sharing the same parent (array order). */
  siblingIdx: Int32Array;
  /** Number of siblings in that group (the region itself included). */
  siblingCount: Int32Array;
};

/** Precompute depth + sibling position for every region. O(n). */
export function computeSiblingInfo(regions: { parentIdx: number }[]): SiblingInfo {
  const n = regions.length;
  const depth = new Int32Array(n);
  const siblingIdx = new Int32Array(n);
  const siblingCount = new Int32Array(n);

  for (let i = 0; i < n; i++) {
    let d = 0;
    let cur = regions[i].parentIdx;
    while (cur >= 0) { d++; cur = regions[cur].parentIdx; }
    depth[i] = d;
  }

  const byParent = new Map<number, number[]>();
  for (let i = 0; i < n; i++) {
    const p = regions[i].parentIdx;
    const bucket = byParent.get(p);
    if (bucket) bucket.push(i);
    else byParent.set(p, [i]);
  }
  for (const group of byParent.values()) {
    for (let k = 0; k < group.length; k++) {
      siblingIdx[group[k]] = k;
      siblingCount[group[k]] = group.length;
    }
  }
  return { depth, siblingIdx, siblingCount };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * Return a shaded clone of `base` for a region at the given depth / sibling
 * position. Top-level regions (depth 0) and only-children are returned
 * unchanged so the palette reads exactly as authored at the top level.
 */
export function shadeColor(
  base: Color,
  depth: number,
  siblingIdx: number,
  siblingCount: number,
): Color {
  if (depth <= 0) return base.clone();   // top-level reads as authored

  const dcap = Math.min(depth, DEPTH_CAP);
  // Per-LEVEL lightness step so a sub-region differs from its parent even when
  // it's an only child (off == 0) — the common case here. Direction alternates
  // by level so nested levels separate from each other instead of all drifting
  // one way into clipping.
  const dir = depth % 2 === 1 ? 1 : -1;
  const depthStep = SHADE_LIGHT_STEP * 0.7 * dcap * dir;
  // Symmetric offset in [-1, 1] fans siblings around that stepped lightness.
  const mid = (siblingCount - 1) / 2;
  const off = mid > 0 ? (siblingIdx - mid) / mid : 0;

  const hsl = { h: 0, s: 0, l: 0 };
  base.getHSL(hsl);
  const l = clamp(hsl.l + depthStep + SHADE_LIGHT_STEP * off, L_MIN, L_MAX);
  const h = (hsl.h + SHADE_HUE_STEP * off + 1) % 1;
  return new Color().setHSL(h, hsl.s, l);
}

/** Convenience for DOM swatches: shaded colour as a `#rrggbb` string. */
export function regionShadeHex(
  baseColor: string,
  depth: number,
  siblingIdx: number,
  siblingCount: number,
): string {
  return `#${shadeColor(new Color(baseColor), depth, siblingIdx, siblingCount).getHexString()}`;
}
