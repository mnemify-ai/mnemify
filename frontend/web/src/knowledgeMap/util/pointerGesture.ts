// Click-vs-drag discrimination for react-three-fiber pointer events.
//
// r3f maps `onClick` straight onto the native DOM `click` event
// (DOM_EVENTS = { onClick: ['click', false], … }), and the browser fires
// `click` after ANY pointerdown→pointerup pair on the element, however far the
// pointer travelled in between. Neither three.js nor r3f applies a motion
// budget, and OrbitControls — which listens on the same <canvas> — never calls
// stopPropagation. So an orbit gesture ends in both a camera rotation AND a
// "click", which is how dragging the terrain used to drill into a region.
//
// It is worse than it first looks: r3f re-raycasts at the RELEASE position, so
// press-on-A → drag → release-over-B drilled into B, not A. r3f's own
// `initialHits` gate compares eventObjects, and the whole terrain is a single
// <instancedMesh>, so that gate always passes and carries no per-instance
// information — it cannot help here.
//
// The fix r3f hands us is `delta`, present on every click-family event: the
// rounded pixel distance from the pointerdown position, computed as
// `Math.round(Math.sqrt(dx * dx + dy * dy))` over offsetX/offsetY.

/**
 * Pointer travel, in CSS pixels, still treated as a click rather than a drag.
 *
 * r3f's own internal notion of a click is `delta <= 2` (used on its
 * pointer-missed path). That is a tight, mouse-shaped number; this is a 3D
 * orbit surface where the press lands on large hex targets and a trackpad or
 * touch adds a few pixels of tremor to even a deliberate tap, so we allow a
 * little more headroom than r3f does.
 *
 * The exact value barely matters: OrbitControls has no dead zone, so anyone
 * genuinely rotating the camera moves tens of pixels before releasing. The gap
 * between "tremor" and "gesture" is wide enough that anything in the 2–8 range
 * behaves identically in practice. 5 sits in the middle of it.
 */
export const CLICK_MAX_DRAG_PX = 5;

/**
 * True when a click-family r3f event was a tap, not the tail of a drag.
 *
 * Feed this `event.delta` from an `onClick` / `onDoubleClick` /
 * `onContextMenu` handler ONLY. r3f hardcodes `delta = 0` for pointer events
 * (`const delta = isClickEvent ? calculateDistance(event) : 0`), so calling
 * this from `onPointerMove` would report every single move as a click.
 */
export function isClickNotDrag(delta: number): boolean {
  return delta <= CLICK_MAX_DRAG_PX;
}
