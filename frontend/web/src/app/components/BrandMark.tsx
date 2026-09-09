import { Link } from "react-router-dom";

/**
 * Mnemify wordmark + mark.
 *
 * The mark is a pointy-top hexagon outline with a smaller filled inner hex
 * — the "synapse core" idea. Pairs with the serif italic wordmark. The mark
 * sits on a baseline-aligned grid with the wordmark so the two read as one
 * unit at any text size.
 *
 * Hover: the inner hex scales up slightly, and a third concentric outline
 * fades in — like the synapse firing. Honors prefers-reduced-motion via the
 * global `*:transition-duration: 0.001ms` rule + `motion-reduce:animate-none`
 * on the animated ring.
 */
export function BrandMark() {
  return (
    <Link
      to="/"
      className="flex items-center gap-2.5 group"
      aria-label="Mnemify home"
    >
      <MnemifyMark className="h-7 w-7 shrink-0" />
      <span className="font-serif italic text-[2.25rem] tracking-tight text-ink leading-none translate-y-[2px]">
        Mnemify
      </span>
    </Link>
  );
}

/**
 * The mark only. Use this anywhere we need just the hex (favicons,
 * preview cards, future onboarding) without the wordmark.
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
