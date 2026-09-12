// One-shot camera move, fired by the store's `zoomToRegion` nonce — map clicks
// (hex / medallion) and any nav action that changes focus, Escape included.
// `idx: null` is the home framing (whole-map bbox), so drilling out actually
// brings the orbit target back to the centre instead of leaving it stranded on
// the region peak — and so is a region that owns no terrain anywhere up its
// ancestor chain, which has no honest destination to fly to.
// It is still NOT driven by `focusRegionIdx` directly: nav
// that only moves tag/doc emits no nonce and never touches the camera. The
// animation preserves the user's current view direction, is time-bounded, and
// cancels the instant the user grabs the controls, so it can never persist or
// fight rotation.

import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { Vector3 } from 'three';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { buildRegionTerrain } from '../util/regionTerrain';

/** Minimal subset of OrbitControls we actually touch. Avoids importing
 *  `three-stdlib`/etc. types that may not ship with our drei version. */
type ControlsLike = {
  target: Vector3;
  update: () => void;
  addEventListener?: (type: string, listener: () => void) => void;
  removeEventListener?: (type: string, listener: () => void) => void;
};

type Pose = { camPos: Vector3; target: Vector3 };

const ANIM_DURATION = 0.55;   // seconds; hard cap so the zoom NEVER persists

/** Largest per-frame step the flight will accept.
 *
 *  The frameloop is `demand`, and r3f 8 feeds useFrame `clock.getDelta()` —
 *  wall time since the LAST RENDERED frame. Nothing renders while the user is
 *  typing in the Ask dock, so the first frame of a "Show on map" flight arrived
 *  with dt = however long the map had sat idle (seconds, not ms). That single
 *  frame both covered the whole distance (k → 1) and blew past ANIM_DURATION,
 *  so the camera teleported instead of flying. Clamping the step makes the
 *  first frame worth at most one ordinary frame. */
const MAX_FRAME_STEP = 1 / 30;

/** Apparent-space (post-yScale) units the focus camera must stay above the
 *  focused region's own summit.
 *
 *  Two constants conspire against a focus flight: Y_SCALE is 0.8, so peaks are
 *  twice as tall as this framing was originally tuned for, and OrbitControls
 *  permits an orbit all the way down to `maxPolarAngle = π/2 − 0.05` — a 2.9°
 *  elevation, at which `dist` buys the camera almost no height at all. Swept
 *  over the real 106-region bake at that lowest orbit: 37 regions parked the
 *  camera below nearby terrain and 4 put it INSIDE a hex prism (up to 3.5
 *  units of penetration — and `near` is 0.1, so you look straight through the
 *  walls). Restoring FOCUS_MIN_FRAC to 0.5 takes that to 2; this floor takes
 *  it to 0 at every orbit heading.
 *
 *  It is a LOCAL guarantee — the focused region's own peak, not the global
 *  maximum — but the camera is aimed at that peak, so it is what sits under
 *  the camera. Inert above ~15° elevation, so ordinary framing is unchanged. */
const FOCUS_TERRAIN_CLEARANCE = 2;

export function CameraAnimator({
  data,
  yScale,
  homeCamPos,
  homeTarget,
  homeLookDist,
}: {
  data: RenderData;
  yScale: number;
  homeCamPos: [number, number, number];
  homeTarget: [number, number, number];
  homeLookDist: number;
}) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as ControlsLike | null;
  const invalidate = useThree((s) => s.invalidate);
  const zoomToRegion = useKnowledgeMapStore((s) => s.zoomToRegion);

  // Region summits at EVERY level, plus the resolve that maps a region onto the
  // terrain it actually occupies. A region's `centroid` is not a safe target:
  // most of this bake's regions own no hexes at all in their whole subtree, and
  // their centroids land on terrain belonging to someone else (or on the world
  // origin) — which is how a chat citation used to fly the camera to nowhere.
  const terrain = useMemo(() => buildRegionTerrain(data), [data]);

  // Live snapshots the trigger effect reads without re-subscribing (refetches
  // change `data`'s identity but not the value we need).
  const liveRef = useRef({ data, yScale, homeCamPos, homeTarget, homeLookDist, terrain });
  liveRef.current = { data, yScale, homeCamPos, homeTarget, homeLookDist, terrain };

  const desired = useRef<Pose>({
    camPos: new Vector3(...homeCamPos),
    target: new Vector3(...homeTarget),
  });
  // Pose at the moment the flight was requested. The flight is a time-
  // parameterised ease from `start` to `desired`, not a per-frame exponential
  // chase: the chase never actually arrived (it was force-released ~4% short
  // of the destination) and its step size depended on dt, which under the
  // demand frameloop is unbounded. See MAX_FRAME_STEP.
  const start = useRef<Pose>({
    camPos: new Vector3(...homeCamPos),
    target: new Vector3(...homeTarget),
  });
  // animating + an elapsed accumulator: the ease runs only while animating, and
  // is force-released at ANIM_DURATION regardless (OrbitControls damping can
  // otherwise keep it from ever "settling" → the stuck/snap bug).
  const animating = useRef(false);
  const elapsed = useRef(0);

  const tick = zoomToRegion?.tick ?? 0;
  useEffect(() => {
    if (!zoomToRegion) return;
    const { data: d, yScale: ys, homeCamPos: hp, homeTarget: ht, homeLookDist: hl, terrain: terr } =
      liveRef.current;
    // PAN to the destination (centre it) while PRESERVING the current view
    // direction — so the camera doesn't reset its angle or dive low onto the
    // point. Shared by both branches: drilling back out must not snap the
    // user's orbit angle to the default iso.
    const curTarget = controls?.target ?? new Vector3(...ht);
    let dir = camera.position.clone().sub(curTarget);
    if (dir.lengthSq() < 1e-6) dir = new Vector3(...hp).sub(new Vector3(...ht));
    dir.normalize();

    // Aim at the terrain that actually CONTAINS the requested region: itself
    // when its subtree owns hexes, otherwise its nearest ancestor that does.
    // `null` — a region with no hexes anywhere up its chain — has no honest
    // destination, so it frames home rather than diving at a phantom centroid.
    const terrainIdx = terr.resolveTerrainRegionIdx(zoomToRegion.idx);

    let newTarget: Vector3;
    let dist: number;
    // Lowest y the finished camera pose may take. Home frames the whole map
    // from well above it and needs no clearance guard, so it leaves this at
    // -Infinity — the clamp below is then a no-op for that branch.
    let camFloorY = -Infinity;
    if (terrainIdx === null) {
      // Home: the whole-map framing Scene computed (bbox centre + look dist).
      newTarget = new Vector3(...ht);
      dist = hl;
    } else {
      const r = d.regions[terrainIdx];
      if (!r) return;

      // Fit the region's footprint AND its peak height (+headroom) so the spire
      // stays in view; clamp so it never zooms OUT past the overview nor IN
      // past what OrbitControls would allow anyway.
      //
      // Aim at the centre of the hexes the region really owns, not at its
      // tallest spire: a peak on the region's rim put the rest of the region
      // off to one side (or off-screen), which read as "it jumped to a point
      // but didn't show me the region". Size the frame from that same hex
      // bbox — the bake's `radius` describes a footprint the layout may never
      // have materialised.
      const peak = terr.peakOf(terrainIdx);
      const foot = terr.footprintOf(terrainIdx);
      const tx = foot?.cx ?? peak?.x ?? r.centroid.x;
      const tz = foot?.cz ?? peak?.z ?? r.centroid.z;
      const footExtent = foot?.halfExtent ?? r.radius;
      const peakScaledY = (peak ? peak.y : r.basePlateauHeight || 0) * ys;
      const ty = peakScaledY * 0.38;
      const FOCUS_LABEL_HEADROOM = 8;
      const FOCUS_MULT = 2.2;        // zoom tightness (smaller = closer)
      // Deliberately STRICTER than OrbitControls' own
      // `minDistance = lookDist * 0.25` (Scene.tsx): that is a pure radius
      // limit and knows nothing about terrain. This was briefly lowered to
      // 0.25 on the theory that real peak targets had made the old floor
      // redundant — they hadn't. At a low orbit the camera lands beside
      // whatever terrain happens to be under it no matter how good the target
      // is, and with Y_SCALE doubled to 0.8 that dropped 37 of the bake's 106
      // regions below nearby hexes. 0.5 brings that back to 2; the clearance
      // floor below covers the rest.
      const FOCUS_MIN_FRAC = 0.5;
      const fitExtent = Math.max(footExtent, peakScaledY + FOCUS_LABEL_HEADROOM);
      dist = fitExtent * FOCUS_MULT;
      dist = Math.min(dist, hl);
      dist = Math.max(dist, hl * FOCUS_MIN_FRAC);
      newTarget = new Vector3(tx, ty, tz);
      camFloorY = peakScaledY + FOCUS_TERRAIN_CLEARANCE;
    }

    // Lift the pose clear of the summit if the preserved view direction would
    // otherwise bury it. Only y moves, so the azimuth the user is orbiting
    // from survives exactly and nothing swings horizontally — but the PITCH
    // change is not cosmetic: entering from the lowest orbit (2.9°) the floor
    // lifts the camera by up to 17.5 units, landing it at up to 14°. That is
    // the deliberate trade — you cannot look at a summit from underneath it.
    const camPos = newTarget.clone().add(dir.multiplyScalar(dist));
    camPos.y = Math.max(camPos.y, camFloorY);

    desired.current = { camPos, target: newTarget };
    start.current = { camPos: camera.position.clone(), target: curTarget.clone() };
    elapsed.current = 0;
    animating.current = true;
    invalidate();   // demand frameloop: kick the first frame of the animation
    // Depend ONLY on the nonce — a fresh request is the one and only trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  // Cancel the moment the user grabs the controls (rotate / zoom / pan), so the
  // zoom never fights the drag. (We do NOT listen to 'change' — the lerp itself
  // calls controls.update(), which fires 'change', and would self-cancel.)
  useEffect(() => {
    if (!controls?.addEventListener) return;
    const stop = () => { animating.current = false; };
    controls.addEventListener('start', stop);
    return () => controls.removeEventListener?.('start', stop);
  }, [controls]);

  useFrame((_, dt) => {
    if (!controls || !animating.current) return;
    elapsed.current += Math.min(dt, MAX_FRAME_STEP);
    const t = Math.min(elapsed.current / ANIM_DURATION, 1);
    const e = 1 - (1 - t) ** 3;   // ease-out cubic: fast departure, soft landing
    camera.position.lerpVectors(start.current.camPos, desired.current.camPos, e);
    controls.target.lerpVectors(start.current.target, desired.current.target, e);
    controls.update();
    if (t >= 1) {
      animating.current = false;   // hard release — never persists
    } else {
      invalidate();   // sustain the demand frameloop until the ease completes
    }
  });

  return null;
}
