// Top-level region palette. The backend assigns colours by cycling a small
// 8-colour list (`palette_index % 8`), so with 16+ top-level regions colours
// repeat — adjacent territories can share a hue and the map looks flat. We
// override that on load with a larger, vibrant, well-spaced categorical palette
// assigned by top-level ordinal. Every consumer reads `region.color`, so
// recolouring the loaded data once propagates everywhere (map, medallions,
// panel swatches, tooltip, breadcrumb) with zero downstream changes.

import type { RenderData } from '../types';

// Vibrant mid-tone hues, ORDERED so sequential top-level regions land in
// different hue families (maximal adjacent contrast). Saturation/lightness are
// tuned to read on both the cream (light) and leather (dark) themes.
export const REGION_PALETTE: string[] = [
  '#E6394B', // red
  '#19A88E', // teal
  '#F5811F', // orange
  '#3B5BDB', // blue
  '#C026A8', // magenta
  '#5FA800', // yellow-green
  '#8E3FD6', // violet
  '#009DC4', // cyan
  '#E0457E', // pink
  '#F0A300', // amber
  '#2E8B57', // sea green
  '#6645E0', // indigo
  '#D2691E', // dark orange
  '#1CA3EC', // sky
  '#B5179E', // fuchsia
  '#4C9A00', // olive green
  '#C2255C', // raspberry
  '#00897B', // dark teal
  '#7048E8', // purple
  '#E8590C', // burnt orange
  '#2F9E44', // forest
  '#1971C2', // steel blue
  '#9C36B5', // grape
  '#F59F00', // gold
];

/** Vibrant colour for the Nth top-level region (cycles only past 24 regions). */
export function topLevelPaletteColor(ordinal: number): string {
  return REGION_PALETTE[ordinal % REGION_PALETTE.length];
}

/**
 * Return a shallow-cloned RenderData whose every region carries a vibrant,
 * varied colour: each top-level region gets the next palette entry (by array
 * order, matching the medallion numbering); sub-regions inherit their top-level
 * ancestor's colour (per-sub-region variation is layered on later by
 * shadeColor, exactly as before). Pure + deterministic, so multiple callers
 * produce identical colours.
 */
export function recolorRegions(data: RenderData): RenderData {
  const colorByIdx: string[] = new Array(data.regions.length);
  let ordinal = 0;
  for (let i = 0; i < data.regions.length; i++) {
    if (data.regions[i].parentIdx < 0) colorByIdx[i] = topLevelPaletteColor(ordinal++);
  }
  const regions = data.regions.map((r) => {
    let cur = r;
    while (cur.parentIdx >= 0) cur = data.regions[cur.parentIdx];
    const topIdx = data.regions.indexOf(cur);
    return { ...r, color: colorByIdx[topIdx] };
  });
  return { ...data, regions };
}
