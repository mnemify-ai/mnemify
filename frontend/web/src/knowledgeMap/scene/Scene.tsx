// 3D scene root: <Canvas> + cinematic camera + lighting (key/fill/rim) +
// soft directional shadows + N8AO post-processing for valley occlusion.
//
// Phase 3 — Steps 8 (PBR shading), 9 (shadows + SSAO), 10 (camera polish).

import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { Bloom, EffectComposer, N8AO } from '@react-three/postprocessing';
import { useMemo } from 'react';
import { MOUSE, TOUCH } from 'three';
import type { RenderData } from '../types';
import { CameraAnimator } from './CameraAnimator';
import { CartographerPaper } from './CartographerPaper';
import { HexField } from './HexField';
import { HighlightBeacons } from './HighlightBeacons';
import { RegionLabels } from './RegionLabels';
import { useTheme } from '../util/useTheme';

// Bake heights are stored at 1:1 with world x/z, but god-tag peaks reach
// ~50 world units on apothem-0.5 hexes (≈ 1 world unit wide). Without a
// y-scale they render as 50:1 toothpicks. Compress vertically for a
// proportional, mountain-like look.
const Y_SCALE = 0.8;

// The y-scale the CAMERA FRAMING pretends the terrain has. It is deliberately
// the OLD Y_SCALE: the two used to be the same number, which made Y_SCALE
// self-cancelling — taller peaks grew `vertExtent`, which grew `lookDist`, so
// the camera retreated by almost exactly as much as the mountains gained
// (a 3× Y_SCALE bought ~1.29× apparent prominence). Framing on the old scale
// pins `lookDist` where it is today, so doubling Y_SCALE genuinely doubles
// apparent prominence instead of just rescaling the whole shot.
const FRAME_Y_SCALE = 0.4;

export function Scene({ data }: { data: RenderData }) {
  const theme = useTheme();
  const isDark = theme === 'dark';

  const layout = useMemo(() => {
    const { minX, maxX, minZ, maxZ, maxY } = data.bounds;
    // Earlier this took the worst-case half-extent assuming the map was
    // centred on origin. The bake doesn't centre — bounds can sit at
    // e.g. x ∈ [-20, +42], so the camera was looking 14 units off-centre
    // and the islands felt "pushed to one side." Centre on the actual
    // bbox and size by its span.
    const cx = (minX + maxX) / 2;
    const cz = (minZ + maxZ) / 2;
    const spanX = maxX - minX;
    const spanZ = maxZ - minZ;
    const horizExtent = Math.max(spanX, spanZ) / 2;
    const scaledHeight = maxY * Y_SCALE;   // apparent terrain-peak height

    // Frame on the LARGER of footprint-vs-height. Sizing on horizontal extent
    // alone (the old `extent * 2.6`) clipped the spires + floating labels once
    // the semantic-layout change made maps that are nearly as tall as they are
    // wide (or, for tight maps, taller than wide). LABEL_HEADROOM leaves room
    // for the medallions / god-tag labels hovering above the summits.
    // FRAME_MULT is the default-zoom dial (smaller = closer).
    // LABEL_HEADROOM is NOT damped by FRAME_Y_SCALE — it is an absolute
    // world-space allowance for the medallions hovering over the summits.
    const LABEL_HEADROOM = 8;
    const FRAME_MULT = 2.4;
    const vertExtent = maxY * FRAME_Y_SCALE + LABEL_HEADROOM;
    const frameExtent = Math.max(horizExtent, vertExtent);

    // Cinematic iso angle: ~30° elevation, looking from upper-front-right.
    const lookDist = frameExtent * FRAME_MULT;
    // 0.38 → 0.45: framing polish, NOT a clipping fix. Measured on the real
    // bake at Y_SCALE 0.8, the topmost thing on screen sits 9.29° above the
    // view axis at 0.38 and 8.64° at 0.45 — both comfortably inside the 19°
    // half of the 38° fov, so nothing was being cut off either way. Lifting
    // the orbit target 45% up the peak height just re-centres the taller
    // terrain, buying ~0.65° of extra top margin at the cost of a little more
    // near-foreground running off the bottom edge — which is where the paper
    // is, not where the peaks are. Treat this as a taste dial with headroom on
    // both sides, not a constraint.
    const targetY = scaledHeight * 0.45;
    const camPos: [number, number, number] = [
      cx + lookDist * 0.62,
      targetY + lookDist * 0.55,  // elevation kept relative to the look target
      cz + lookDist * 0.62,
    ];
    return {
      camPos,
      target: [cx, targetY, cz] as [number, number, number],
      lookDist,
      extent: horizExtent,   // horizontal only — drives ground-shadow framing
    };
  }, [data.bounds]);

  // Light position: high-front-right, just past the camera, so faces
  // toward the camera get the warm key light.
  const keyLightPos: [number, number, number] = [
    layout.lookDist * 0.9,
    layout.lookDist * 0.95,
    layout.lookDist * 0.5,
  ];
  const fillLightPos: [number, number, number] = [
    -layout.lookDist * 0.6,
    layout.lookDist * 0.4,
    -layout.lookDist * 0.4,
  ];

  return (
    <Canvas
      shadows
      // Render on demand, not 60fps-forever: the scene is static except during
      // camera moves / focus animation / hover repaints, and each frame runs
      // the full N8AO + Bloom + shadow pipeline. OrbitControls invalidates on
      // its change events; imperative mutators (CameraAnimator, HexField)
      // call invalidate() themselves.
      frameloop="demand"
      // Keep the canvas sized DURING a panel drag rather than a beat after it.
      //
      // r3f measures its container with react-use-measure, defaulting to
      // `{ scroll: true, debounce: { scroll: 50, resize: 0 } }` — which reads
      // as "resize is undebounced". It isn't: react-use-measure 2.1.7 wires
      // the two callbacks the wrong way round. It builds one callback debounced
      // by `resize` and one debounced by `scroll`, then hands the SCROLL-
      // debounced one to `new ResizeObserver(...)` and the resize-debounced one
      // to the `window.resize` listener. Dragging a panel only ever fires the
      // ResizeObserver, so the effective debounce is the *scroll* number: 50 ms,
      // trailing, with a `clearTimeout` on every call. A drag ticks roughly
      // every 16 ms, so that timer never lands and `getBoundingClientRect()` is
      // never re-read for the whole gesture. The <canvas> keeps its stale
      // explicit pixel size (three's setSize writes style.width/height), so
      // growing the panel clips it and shrinking the panel exposes a bare strip
      // of page background — the "canvas goes black while dragging" bug.
      //
      // `scroll: 0` is therefore the load-bearing number. Do NOT "tidy" it to a
      // small non-zero value: react-use-measure special-cases falsy to *no
      // debounce wrapper at all* (`d ? debounce(fn, d) : fn`), so 0 is exactly
      // synchronous, while any positive value re-arms the same never-landing
      // trailing timer and brings the black canvas straight back.
      //
      // `scroll: false` because scroll tracking exists only to refresh
      // size.top/left, and nothing reads those: r3f's default `compute` picks
      // with offsetX/offsetY, and top/left are otherwise inert in the store.
      // Leaving it on would install a window-level capture scroll listener
      // that — now undebounced — forces a layout read on every scroll frame of
      // the right panel's lists. Width/height still come from the
      // ResizeObserver, which is the part that actually matters.
      resize={{ scroll: false, debounce: { scroll: 0, resize: 0 } }}
      camera={{
        position: layout.camPos,
        fov: 38,
        near: 0.1,
        far: layout.lookDist * 5,
      }}
      style={{ background: 'transparent' }}
      dpr={[1, 2]}
      gl={{ antialias: true }}
    >
      {/* Ambient: low so SSAO + directional shading carry the contrast.
          Dimmer in dark mode so the leather desk reads as a dim surface.
          Light mode is lifted so shadowed hex faces and the paper under a
          spire's shadow stay cream rather than going brown. */}
      <ambientLight intensity={isDark ? 0.22 : 0.46} />

      {/* Key light: warm, casts soft shadows. Shadow camera explicitly
          framed to cover the whole world so nothing falls outside.
          The 1.3 multiplier survives the Y_SCALE bump: the key light sits at
          ~42.7° elevation, so a peak's ground shadow now reaches ~34.7 world
          units instead of ~17.3 — but the paper plane shrank at the same time,
          and shadow that misses the paper is invisible. Measured worst-case
          light-space half-extent needed is 1.25 × extent (demo bake) and
          0.96 × (real bake), both inside 1.3. Widening further would only
          spread the 2048² shadow map thinner. */}
      <directionalLight
        position={keyLightPos}
        intensity={1.15}
        color={'#FFF6E5'}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-layout.extent * 1.3}
        shadow-camera-right={layout.extent * 1.3}
        shadow-camera-top={layout.extent * 1.3}
        shadow-camera-bottom={-layout.extent * 1.3}
        shadow-camera-near={0.1}
        shadow-camera-far={layout.lookDist * 4}
        shadow-bias={-0.0008}
        shadow-radius={3}
      />

      {/* Fill light: cool, opposite side, no shadow — softens valleys.
          Dimmer in dark mode for the same reason ambient is. */}
      <directionalLight
        position={fillLightPos}
        intensity={isDark ? 0.30 : 0.58}
        color={'#D8E2F0'}
      />

      {/* Cartographer's paper / dark desk plane underneath everything.
          Drawn first so hexes and contour rings can shadow onto it. */}
      <CartographerPaper data={data} theme={theme} />

      <group scale={[1, Y_SCALE, 1]}>
        <HexField data={data} theme={theme} />
      </group>

      {/* Region cartouches (numeral + name) sit on the tallest peak of each
          top-level region. Mounted OUTSIDE the y-scale group so positions work
          in apparent (post-scale) world space directly. Always rendered for
          relevant regions (focused / hovered / highlighted) plus a zoom-scaled
          budget of the most prominent ones that fit without overlapping — the
          home look distance is the zoom=1 reference for that budget. */}
      <RegionLabels data={data} yScale={Y_SCALE} homeLookDist={layout.lookDist} />

      {/* Orbs + light columns over the spires the last Ask answer cited.
          Outside the y-scale group like the labels — see the component. */}
      <HighlightBeacons yScale={Y_SCALE} />

      {/* "Also resembles" now lives in the right panel's Tag → Related tab, so
          no floating card obstructs the map (was <TagRelationPopover />). */}

      {/* Post-processing chain. N8AO for valley ambient occlusion;
          Bloom catches the brighter god-tag summits as glowing peaks
          (Step 19 — luminanceThreshold tuned to ~god-tag colour brightness). */}
      <EffectComposer multisampling={4}>
        <N8AO
          // World units. Valleys are twice as DEEP after the Y_SCALE bump but
          // exactly as wide (hex footprints are untouched), so this is a
          // partial, not a 2×, correction — and a bigger radius spreads the
          // fixed aoSamples={20} thinner, which gets noisy.
          aoRadius={5}
          // Light mode: gentler, warmer occlusion. The old 2.4 / cool
          // aubergine tint pooled dark brown in every valley and along
          // every hex base, which is where the "muddy edges" came from.
          // Dark mode keeps the stronger AO — it carries the depth there.
          intensity={isDark ? 2.4 : 1.3}
          aoSamples={20}
          denoiseSamples={6}
          color={isDark ? '#3A3140' : '#7A6653'}
        />
        <Bloom
          intensity={0.55}
          // Sepia paper highlights peak around 0.91 luminance, well above
          // the 0.62 threshold tuned for the old flat-cream fill. Bump in
          // light mode so the paper itself doesn't bloom; the dark desk
          // peaks far below 0.62 so the original threshold still fits.
          luminanceThreshold={isDark ? 0.62 : 0.78}
          luminanceSmoothing={0.18}
          mipmapBlur
        />
      </EffectComposer>

      <OrbitControls
        target={layout.target}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        // Zoom limits track the fitted (height-aware) look distance so users
        // can get close to small/tight maps and still pull back from big ones.
        minDistance={layout.lookDist * 0.25}
        maxDistance={layout.lookDist * 2.5}
        minPolarAngle={0.15}
        maxPolarAngle={Math.PI / 2 - 0.05}
        // Left-drag orbits, right-drag MOVES across the map (ctrl/shift +
        // left-drag also pans, which OrbitControls honours by default),
        // dolly on middle. Touch: one finger orbits, two fingers pinch-zoom
        // + pan.
        mouseButtons={{ LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN }}
        touches={{ ONE: TOUCH.ROTATE, TWO: TOUCH.DOLLY_PAN }}
        // Pan parallel to the ground plane, not the screen — dragging "up"
        // slides the map away from you instead of lifting the camera off it.
        screenSpacePanning={false}
        // Pan speed scaled with the map: OrbitControls pans by world units
        // per pixel relative to the camera distance, so this is a taste dial.
        panSpeed={0.9}
      />

      {/* Animates camera + target whenever focusRegionIdx changes. */}
      <CameraAnimator
        data={data}
        yScale={Y_SCALE}
        homeCamPos={layout.camPos}
        homeTarget={layout.target}
        homeLookDist={layout.lookDist}
      />
    </Canvas>
  );
}
