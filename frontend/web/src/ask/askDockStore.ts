import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The Ask dock's shell state — open/closed, maximized or not, and the docked
 * width — persisted so the dock comes back the way you left it.
 */

export const DOCK_MIN_WIDTH = 380;
/** Store-level ceiling only. Deliberately generous: a width dragged on a wide
 *  monitor must survive a session on a laptop unmangled, so the *viewport*
 *  clamp lives at the drag/render edge (`dockDragMaxWidth`), not here. */
export const DOCK_MAX_WIDTH = 2400;
export const DOCK_DEFAULT_WIDTH = 460;

/** How far left the dock may be dragged on a given viewport: almost the whole
 *  window, but always leaving the app usable behind it. The reserve is 420px,
 *  not a token sliver: on Home the map column carries a `flexShrink: 0` detail
 *  panel of 300px, so anything less clips that panel and starves the canvas to
 *  zero width. Mirrored in CSS as `min(92vw, calc(100vw - 420px))` so the
 *  applied width re-clamps on window resize without a listener. */
export const dockDragMaxWidth = (viewportWidth: number) =>
  Math.min(viewportWidth * 0.92, viewportWidth - 420);

type AskDockState = {
  open: boolean;
  /** Maximized — the dock fills the shell row instead of its docked width. */
  wide: boolean;
  /** Docked-mode width in px (restored when un-maximizing). */
  width: number;
  /** How many right-anchored overlays are currently holding a slot beside the
   *  dock (see `openOverlay`). Never persisted — a reload starts at 0. */
  overlays: number;
  openDock: () => void;
  closeDock: () => void;
  toggleDock: () => void;
  toggleWide: () => void;
  unmaximizeDock: () => void;
  openOverlay: () => void;
  closeOverlay: () => void;
  setWidth: (width: number) => void;
};

/** The state a right-anchored overlay needs to know where the dock starts. */
export type DockInsetSource = Pick<AskDockState, "open" | "wide" | "width">;

/**
 * How much of the viewport's right edge the Ask dock is eating — i.e. the
 * `right` offset a viewport-anchored overlay must take to land *beside* the
 * conversation instead of on top of it.
 *
 * Zero when the dock is closed (nothing to clear) and zero when it's
 * maximized: a full-row dock leaves no "beside", so surfaces that must not
 * cover it un-maximize instead (`openOverlay`), and by the time they paint
 * the dock is back to `width`.
 *
 * Answers *which* width, not *how much of it fits*: `width` carries only the
 * static ceiling, and the viewport clamp lives at the render edge. Feed the
 * result through `dockInsetCss` before handing it to CSS.
 *
 * The dock mutates `aside.style.width` directly during a resize drag and only
 * commits to the store on pointer-up, so subscribers trail a live drag by one
 * release. That's the same deal the map's panel-width store strikes and
 * it is deliberate — the alternative is a store write per pointermove.
 */
export function dockOverlayInset(dock: DockInsetSource): number {
  return dock.open && !dock.wide ? dock.width : 0;
}

/**
 * `dockOverlayInset` as a CSS length, re-clamped to *this* viewport.
 *
 * The dock's aside caps itself in CSS with `min(92vw, calc(100vw - 420px))`
 * — the `dockDragMaxWidth` formula, left to the browser so it follows window
 * resizes without a listener. A raw store width would therefore overshoot
 * what the dock actually renders: a 1800px width dragged on a 27" monitor is
 * kept verbatim (that's the point of `DOCK_MAX_WIDTH`), but on a 1440px
 * laptop the dock draws 1020px. An inset of 1800px there leaves a 780px cream
 * gap and drives `calc(100vw - inset)` negative, which collapses the inset
 * surface to zero width — a "View source" click that opens nothing.
 *
 * Mirroring the same `min()` keeps inset and rendered dock in lockstep. Every
 * consumer applies it behind `md:`, where `100vw - 420px` is at least 348px,
 * so the result can't go negative.
 */
export function dockInsetCss(inset: number): string {
  return `min(${inset}px, 92vw, calc(100vw - 420px))`;
}

/** `dockOverlayInset` as a subscription. Pass `enabled: false` and the
 *  selector returns a constant 0, so callers that don't care never re-render
 *  when the dock opens, closes, or is resized. */
export function useDockOverlayInset(enabled = true): number {
  return useAskDockStore((s) => (enabled ? dockOverlayInset(s) : 0));
}

export const useAskDockStore = create<AskDockState>()(
  persist(
    (set, get) => ({
      open: false,
      wide: false,
      width: DOCK_DEFAULT_WIDTH,
      overlays: 0,
      openDock: () => set({ open: true }),
      closeDock: () => set({ open: false }),
      toggleDock: () => set({ open: !get().open }),
      toggleWide: () => set({ wide: !get().wide }),
      unmaximizeDock: () => set({ wide: false }),
      // A document surface that must sit *left* of the conversation has
      // opened. A maximized dock owns the whole row, so there is no left of
      // it — restore the docked width and hold maximize disabled until every
      // such surface has closed again, or one click on Maximize would put the
      // document back on top of the chat.
      openOverlay: () => set({ overlays: get().overlays + 1, wide: false }),
      closeOverlay: () => set({ overlays: Math.max(0, get().overlays - 1) }),
      setWidth: (width) =>
        set({ width: Math.min(DOCK_MAX_WIDTH, Math.max(DOCK_MIN_WIDTH, width)) }),
    }),
    {
      name: "mnemify.ask.dock.v1",
      // `overlays` counts live UI, not preference: a reload (or a crash with
      // a drawer open) must never restore a non-zero count, which would leave
      // Maximize permanently disabled. Functions were already dropped by
      // JSON.stringify, so the persisted payload is unchanged by this.
      partialize: (s) => ({ open: s.open, wide: s.wide, width: s.width }) as AskDockState,
      // v2: `wide` used to mean "a 720px panel"; it now means "fill the whole
      // shell row", which drops the route column out of layout. A stale
      // `wide: true` from the old build would restore into a full-window chat
      // with no map or nav — indistinguishable from a broken app — so drop it
      // on the way in and keep the rest (open, width).
      version: 2,
      migrate: (persisted) => ({ ...(persisted as AskDockState), wide: false }),
    },
  ),
);
