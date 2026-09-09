// Cartographer's paper / desk plane that lives under the hex field.
//
// Light mode: aged sepia parchment with paper-fiber noise, stains, edge
// vignette and hand-drawn contour rings around each top-level region.
// (The compass rose and the "Map of Your Knowledge" title are DOM
// overlays now — see chrome/CartographerDecorations.tsx.)
//
// Dark mode: leather-desk variant of the same. Deep brown base, bone-
// coloured ink so the cartographer language carries through.
//
// Texture is baked synchronously inside a useMemo so the material has it
// on first render — the previous rAF deferral relied on an async setState
// commit that could leave the plane stuck on its fallback fill.
//
// The plane is sized PER AXIS from the real hex extent (see
// util/paperGeometry.ts) and the texture's pixel dimensions follow the
// plane's aspect, so texels stay square and the contour rings stay circular.

import { useEffect, useMemo } from 'react';
import {
  CanvasTexture,
  ClampToEdgeWrapping,
  LinearFilter,
  SRGBColorSpace,
} from 'three';
import type { RenderData } from '../types';
import { buildPaperGeometry, type Island } from '../util/paperGeometry';
import type { Theme } from '../util/useTheme';

type PaperPalette = {
  baseGradient: [string, string, string];
  noiseRGB: [number, number, number];
  noiseAlpha: number;
  stainColor: string;       // rgba(.., a) — alpha gets randomised per stain
  stainAlphaMin: number;
  stainAlphaMax: number;
  edgeColor: string;        // rgba string used at the burnt borders
  edgeAlpha: number;        // peak opacity of the burnt-border vignette
  contourColor: string;     // rgb tuple as rgba() string — alpha varies per ring
  contourAlphaMax: number;
  inkColor: string;         // rgb tuple as rgba() string — compass/title body
  inkAlphaStrong: number;
  inkAlphaSoft: number;
  fallbackFill: string;     // solid colour shown while the texture bakes
};

// Light parchment is deliberately PALE: the outer gradient stop used to fall
// to a burnt '#C9AC78' and the vignette peaked at 0.35, which framed the map
// in dark brown and competed with the coloured regions. Now the sheet stays a
// soft cream all the way out, with only a faint warm edge for the aged look.
const LIGHT: PaperPalette = {
  baseGradient: ['#F5EAD2', '#EEDFBC', '#E2CFA3'],
  noiseRGB: [210, 192, 155],
  noiseAlpha: 22,
  stainColor: '120, 80, 30',
  stainAlphaMin: 0.04,
  stainAlphaMax: 0.10,
  edgeColor: '110, 75, 35',
  edgeAlpha: 0.14,
  contourColor: '115, 78, 32',
  contourAlphaMax: 0.30,
  inkColor: '80, 50, 20',
  inkAlphaStrong: 0.88,
  inkAlphaSoft: 0.55,
  fallbackFill: '#EEDFBC',
};

const DARK: PaperPalette = {
  baseGradient: ['#2C211A', '#1F1813', '#14100C'],
  noiseRGB: [80, 64, 48],
  noiseAlpha: 46,
  stainColor: '40, 24, 10',
  stainAlphaMin: 0.20,
  stainAlphaMax: 0.32,
  edgeColor: '0, 0, 0',
  edgeAlpha: 0.35,
  contourColor: '220, 195, 150',
  contourAlphaMax: 0.22,
  inkColor: '230, 200, 150',
  inkAlphaStrong: 0.85,
  inkAlphaSoft: 0.55,
  fallbackFill: '#1F1813',
};

/** Resolution of the texture's LONG edge. The short edge is derived from the
 *  plane's aspect so texels are square — the ring maths below assumes it. */
const TEX_LONG_EDGE = 2048;

/** Per-axis margin around the hex extent. Symmetric, so the plane keeps the
 *  terrain's own aspect instead of inheriting the texture's. */
const PLANE_MARGIN = 1.3;
/** Floor for tiny maps, so a two-island bake still gets a sheet of paper. */
const PLANE_MIN = 40;

// Contour-ring geometry. Shared by the bake and by the plane sizing, so the
// outermost ring of an edge island can never fall off the sheet.
const RING_COUNT = 6;
const RING_GAP = 0.85;        // world units between successive rings
const RING_INSET = 0.8;       // first ring sits this far outside island.r
/** How far past `island.r` the outermost ring reaches, in world units. */
const RING_REACH = RING_INSET + (RING_COUNT - 1) * RING_GAP;
/** Breathing room between that ring and the edge of the paper. */
const RING_PAD = 1;

/** Everything the bake and the mesh need to agree on. */
type PlaneSpec = {
  w: number;
  h: number;
  texW: number;
  texH: number;
  centerX: number;
  centerZ: number;
};

function bakePaperTexture(
  islands: Island[],
  plane: PlaneSpec,
  palette: PaperPalette,
): HTMLCanvasElement {
  const { w: planeW, h: planeH, texW, texH, centerX, centerZ } = plane;
  const canvas = document.createElement('canvas');
  canvas.width = texW;
  canvas.height = texH;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;

  // World → texel maps. Plane is centred at (centerX, centerZ), so a world
  // point (w, _, w') sits at texel
  // ((w - cx + planeW/2) * texW/planeW, (w' - cz + planeH/2) * texH/planeH).
  // Without the (cx, cz) offset, contour rings would draw at the wrong
  // place once the plane is no longer origin-centred.
  const wxToPx = (w: number) => (w - centerX + planeW / 2) * (texW / planeW);
  const wzToPx = (w: number) => (w - centerZ + planeH / 2) * (texH / planeH);

  // Radii for the paper's own decoration are relative to the long edge, so
  // the look doesn't change with the texture's aspect.
  const texLong = Math.max(texW, texH);

  // Base radial gradient (paper highlight → mid → burnt).
  const [c0, c1, c2] = palette.baseGradient;
  const base = ctx.createRadialGradient(
    texW / 2, texH / 2, texLong * 0.1,
    texW / 2, texH / 2, texLong * 0.7,
  );
  base.addColorStop(0.0, c0);
  base.addColorStop(0.55, c1);
  base.addColorStop(1.0, c2);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, texW, texH);

  // Paper-fiber noise.
  const [nr, ng, nb] = palette.noiseRGB;
  const noise = ctx.createImageData(texW, texH);
  for (let i = 0; i < noise.data.length; i += 4) {
    const n = (Math.random() - 0.5) * 30;
    noise.data[i + 0] = nr + n;
    noise.data[i + 1] = ng + n;
    noise.data[i + 2] = nb + n;
    noise.data[i + 3] = palette.noiseAlpha;
  }
  ctx.putImageData(noise, 0, 0);

  // Stains & wear marks.
  for (let i = 0; i < 14; i++) {
    const x = Math.random() * texW;
    const y = Math.random() * texH;
    const r = (60 + Math.random() * 240) * (texLong / 2048);
    const alpha =
      palette.stainAlphaMin + Math.random() * (palette.stainAlphaMax - palette.stainAlphaMin);
    const stain = ctx.createRadialGradient(x, y, 0, x, y, r);
    stain.addColorStop(0.0, `rgba(${palette.stainColor}, ${alpha.toFixed(3)})`);
    stain.addColorStop(1.0, `rgba(${palette.stainColor}, 0)`);
    ctx.fillStyle = stain;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
  }

  // Burnt vignette — vertical + horizontal. Peak opacity is per theme.
  const ea = palette.edgeAlpha.toFixed(3);
  const v = ctx.createLinearGradient(0, 0, 0, texH);
  v.addColorStop(0.0, `rgba(${palette.edgeColor}, ${ea})`);
  v.addColorStop(0.08, `rgba(${palette.edgeColor}, 0.0)`);
  v.addColorStop(0.92, `rgba(${palette.edgeColor}, 0.0)`);
  v.addColorStop(1.0, `rgba(${palette.edgeColor}, ${ea})`);
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, texW, texH);
  const h = ctx.createLinearGradient(0, 0, texW, 0);
  h.addColorStop(0.0, `rgba(${palette.edgeColor}, ${ea})`);
  h.addColorStop(0.06, `rgba(${palette.edgeColor}, 0.0)`);
  h.addColorStop(0.94, `rgba(${palette.edgeColor}, 0.0)`);
  h.addColorStop(1.0, `rgba(${palette.edgeColor}, ${ea})`);
  ctx.fillStyle = h;
  ctx.fillRect(0, 0, texW, texH);

  // Hand-drawn contour rings around each island.
  ctx.lineCap = 'round';
  for (const island of islands) {
    const cx = wxToPx(island.cx);
    const cz = wzToPx(island.cz);
    const baseRWorld = island.r + RING_INSET;
    for (let i = 0; i < RING_COUNT; i++) {
      const rWorld = baseRWorld + i * RING_GAP;
      // texW/planeW and texH/planeH are the same texels-per-world-unit to
      // within integer rounding of the short edge (< 0.05%), so these rings
      // are circles, not ellipses. The only intentional deformation is `wob`.
      const rPxX = rWorld * (texW / planeW);
      const rPxZ = rWorld * (texH / planeH);
      ctx.beginPath();
      const steps = 96;
      for (let s = 0; s <= steps; s++) {
        const a = (s / steps) * Math.PI * 2;
        const wob = 1 + Math.sin(a * 5 + i * 1.2) * 0.04;
        const x = cx + Math.cos(a) * rPxX * wob;
        const y = cz + Math.sin(a) * rPxZ * wob;
        if (s === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      const alpha = Math.max(0.05, palette.contourAlphaMax - i * 0.05);
      ctx.strokeStyle = `rgba(${palette.contourColor}, ${alpha.toFixed(3)})`;
      ctx.lineWidth = i === 0 ? 2.2 : 1.4;
      ctx.setLineDash(i % 2 === 0 ? [] : [8, 6]);
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);

  // Title and compass are NOT baked into the texture any more — they
  // live as DOM overlays in CartographerDecorations.tsx so they always
  // sit at consistent screen positions regardless of camera angle.
  // The texture now carries only paper + noise + stains + vignette +
  // contour rings.

  return canvas;
}

export function CartographerPaper({
  data,
  theme,
}: {
  data: RenderData;
  theme: Theme;
}) {
  const palette = theme === 'dark' ? DARK : LIGHT;
  const geom = useMemo(() => buildPaperGeometry(data), [data]);

  // Plane sized PER AXIS from the hexes that actually exist: a symmetric 30%
  // margin on each axis to start with. The old rule sized BOTH axes off
  // `max(spanX, spanZ) * 1.8` and then derived the height from the TEXTURE's
  // aspect ratio — which made the sheet 2.2× the terrain on one axis and 1.3×
  // on the other (2.9× the footprint), i.e. the vast empty parchment expanse
  // around the map.
  const spanX = geom.maxX - geom.minX;
  const spanZ = geom.maxZ - geom.minZ;
  const centerX = (geom.minX + geom.maxX) / 2;
  const centerZ = (geom.minZ + geom.maxZ) / 2;
  // …then grown, if needed, so the outermost contour ring of an edge island
  // still lands on paper. The plane stays centred on the terrain, so an
  // island that overhangs one side grows both.
  let halfW = Math.max(spanX * PLANE_MARGIN, PLANE_MIN) / 2;
  let halfH = Math.max(spanZ * PLANE_MARGIN, PLANE_MIN) / 2;
  for (const island of geom.islands) {
    const reach = island.r + RING_REACH + RING_PAD;
    halfW = Math.max(halfW, Math.abs(island.cx - centerX) + reach);
    halfH = Math.max(halfH, Math.abs(island.cz - centerZ) + reach);
  }
  const planeW = halfW * 2;
  const planeH = halfH * 2;
  // Texture pixels follow the PLANE's aspect (long edge fixed at
  // TEX_LONG_EDGE) so texels stay square: a ring of radius r world units is
  // the same number of texels on both axes, so it draws as a circle.
  //
  // Cost, measured against the old fixed 2048×1500 (3.07 MP): the real bake
  // bakes 1712×2048 = 3.51 MP (+14%) and the demo 1774×2048 = 3.63 MP (+18%).
  // Worst case is a SQUARE plane — an empty or tiny bake falling back to the
  // PLANE_MIN floor — where both axes take TEX_LONG_EDGE: 2048² = 4.19 MP
  // (+37%). That is deliberately not capped. A total-texel cap would have to
  // shrink both axes by the same factor to keep texels square (the ring maths
  // below and the stain radii both assume it), and the case it would fire on
  // is the one with almost nothing on it — paying ~1 MP once, on first paint,
  // to keep small maps crisp is the better trade.
  const texW = planeW >= planeH
    ? TEX_LONG_EDGE
    : Math.max(1, Math.round(TEX_LONG_EDGE * (planeW / planeH)));
  const texH = planeH >= planeW
    ? TEX_LONG_EDGE
    : Math.max(1, Math.round(TEX_LONG_EDGE * (planeH / planeW)));

  // Keep the deps NUMERIC: the bake below is a ~3 MP per-pixel loop, and a
  // fresh object identity here would re-run it on every render.
  const plane = useMemo<PlaneSpec>(
    () => ({ w: planeW, h: planeH, texW, texH, centerX, centerZ }),
    [planeW, planeH, texW, texH, centerX, centerZ],
  );

  // Synchronous bake. ~150 ms one-time on first paint, then memo-stable
  // until theme or layout changes. Doing it here (rather than in an
  // effect + setState) means the texture is present on first render, so
  // the plane never flashes a blank fill.
  const texture = useMemo(() => {
    const canvas = bakePaperTexture(geom.islands, plane, palette);
    const tex = new CanvasTexture(canvas);
    tex.colorSpace = SRGBColorSpace;
    tex.anisotropy = 8;
    tex.minFilter = LinearFilter;
    tex.magFilter = LinearFilter;
    tex.wrapS = ClampToEdgeWrapping;
    tex.wrapT = ClampToEdgeWrapping;
    tex.needsUpdate = true;
    return tex;
  }, [geom, plane, palette]);

  // Dispose the previous texture once React commits the new one (and on
  // unmount). Tying disposal to `[texture]` cleanup means the previous
  // tex is only freed AFTER `material.map` has swapped to the new one.
  useEffect(() => {
    return () => {
      texture.dispose();
    };
  }, [texture]);

  return (
    <mesh
      position={[centerX, -0.01, centerZ]}
      rotation={[-Math.PI / 2, 0, 0]}
      receiveShadow
    >
      <planeGeometry args={[planeW, planeH]} />
      <meshStandardMaterial
        map={texture}
        roughness={0.95}
        metalness={0.0}
      />
    </mesh>
  );
}
