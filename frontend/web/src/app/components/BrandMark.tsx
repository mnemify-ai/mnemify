import { Link } from "react-router-dom";
import { useMapFocusStore } from "../lib/mapFocusStore";
import { useMapHighlightStore } from "../lib/mapHighlightStore";
import { useMapPulseStore } from "../lib/mapPulseStore";

/** The brand mark is the "start over" button for the map: home route with no
 *  query (drops `?tag=`), no region focus, no answer highlight, no agent
 *  pulses, and a camera re-frame. Safe to call from any route — the stores
 *  outlive route mounts and HomePage / KnowledgeMap consume them on mount. */
export function resetMapView() {
  useMapHighlightStore.getState().clear();
  useMapPulseStore.getState().clear();
  useMapFocusStore.getState().requestReset();
}

/**
 * Mnemify wordmark + logo.
 *
 * The logo is the isometric "M" from `assets/icons/mnemify-mark-1024.png`
 * (a trimmed 128px copy lives in `public/mnemify-mark.png` — the 1024px
 * original is far too heavy for a 28px slot). It sits baseline-aligned with
 * the serif italic wordmark so the two read as one unit at any text size.
 * Hover nudges the logo up a touch, like the old hex "firing".
 */
export function BrandMark() {
  return (
    <Link
      to="/"
      onClick={resetMapView}
      className="flex items-center gap-2.5 group"
      aria-label="Mnemify home"
      title="Home: reset the map"
    >
      <img
        src="/mnemify-mark.png"
        alt=""
        width={28}
        height={28}
        draggable={false}
        className="h-7 w-7 shrink-0 select-none transition-transform duration-base ease-out group-hover:-translate-y-px"
      />
      <span className="font-serif italic text-[2.25rem] tracking-tight text-ink leading-none translate-y-[2px]">
        Mnemify
      </span>
    </Link>
  );
}

/**
 * The original hex mark, kept for places that want a vector glyph (empty
 * states, preview cards) — the TopBar now shows the PNG logo instead.
 *
 * Drawn as a pointy-top regular hexagon in a 32×32 viewbox. The outer hex
 * is an outline; the inner hex is filled magenta at 40% scale.
 */
export function MnemifyMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      aria-hidden="true"
      role="img"
    >
      {/*
        All three hexes are pointy-top, concentric on (16, 16). For a regular
        pointy-top hex of circumradius R at (cx, cy), the six vertices are:
          (cx, cy ± R)              top + bottom
          (cx ± R·√3/2, cy ± R/2)   four sides
        We use √3/2 ≈ 0.866. Paths walk clockwise from the top vertex.
      */}

      {/* Outer hex — circumradius 14. Outline, magenta with low alpha so it
         sits gently against cream / dark backgrounds. */}
      <path
        d="M16 2 L28.12 9 L28.12 23 L16 30 L3.88 23 L3.88 9 Z"
        fill="none"
        stroke="rgb(var(--c-magenta))"
        strokeWidth="1.5"
        strokeLinejoin="round"
        opacity="0.75"
        className="transition-opacity duration-base ease-out group-hover:opacity-100"
      />
      {/* Hover halo — concentric hex at circumradius 10, fades in on hover. */}
      <path
        d="M16 6 L24.66 11 L24.66 21 L16 26 L7.34 21 L7.34 11 Z"
        fill="none"
        stroke="rgb(var(--c-magenta))"
        strokeWidth="1"
        strokeLinejoin="round"
        opacity="0"
        className="transition-opacity duration-base ease-out group-hover:opacity-40"
      />
      {/* Synapse core — filled hex at circumradius 5.2 (matches the previous
         visual weight). Scales up on hover for the "firing" feel. */}
      <path
        d="M16 10.8 L20.5 13.4 L20.5 18.6 L16 21.2 L11.5 18.6 L11.5 13.4 Z"
        fill="rgb(var(--c-magenta))"
        className="transition-transform duration-base ease-out group-hover:scale-110 origin-center"
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
      />
    </svg>
  );
}
