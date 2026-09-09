// Cartographer chart decorations rendered as fixed-position DOM overlays
// instead of being baked into the paper texture. They sit at consistent
// screen positions regardless of camera angle / zoom — no more "title
// landed inside the hex cluster" or "compass off-screen" depending on
// orbit. The styling pulls from the same theme tokens the rest of the
// knowledge-map chrome uses, so they swap cleanly between light and dark.

export function CartographerDecorations() {
  return (
    <>
      <div
        className="absolute top-[84px] left-7 pointer-events-none z-[4] font-[ui-serif,'Newsreader',Georgia,serif] [text-shadow:0_1px_2px_rgba(0,0,0,0.25)]"
        aria-hidden
      >
        <div className="text-[28px] italic font-medium text-ink/[0.78] tracking-[0.01em] leading-[1.1]">
          Map of Your Knowledge
        </div>
        <div className="text-[14px] italic text-ink/[0.52] mt-1 tracking-[0.04em]">
          drawn · MMXXVI
        </div>
      </div>

      {/* Bottom-LEFT corner, not bottom-right: the canvas's bottom-right is
          owned by the Ask dock (ask/AskBubble.tsx), whose desktop inset —
          md:right-[var(--ask-bubble-inset)], set on the dock wrapper in
          app/layouts/DashboardLayout.tsx — lands at this same canvas-right
          edge, so the bubble sat right on top of the rose at every breakpoint.
          The left corner is clear (title is top-left, the hint is top-centre)
          and balances the chrome-heavy right side. */}
      <div
        className="absolute bottom-6 left-6 pointer-events-none z-[4] drop-shadow-[0_2px_4px_rgba(0,0,0,0.35)]"
        aria-hidden
      >
        <CompassRose />
      </div>
    </>
  );
}

function CompassRose() {
  // SVG compass mirrors the cartographer-mockup canvas drawing: outer +
  // inner rings, 8-point star with cardinal points emphasised, N/E/S/W
  // letters around the rim. Uses currentColor everywhere so the parent
  // can theme it with one CSS variable.
  return (
    <svg
      width="120"
      height="120"
      viewBox="-70 -70 140 140"
      className="text-ink/[0.62] block"
    >
      {/* Outer + inner rings */}
      <circle cx="0" cy="0" r="55" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="0" cy="0" r="43" fill="none" stroke="currentColor" strokeWidth="0.9" opacity="0.7" />

      {/* Cardinal star points (long) */}
      <g fill="currentColor" opacity="0.78">
        <polygon points="0,-55  7,0  0,7  -7,0" />
        <polygon points="55,0  0,7  -7,0  0,-7" transform="rotate(90)" />
        <polygon points="0,55  7,0  0,-7  -7,0" transform="rotate(180)" />
        <polygon points="-55,0  0,-7  7,0  0,7" transform="rotate(270)" />
      </g>
      {/* Inter-cardinal star points (shorter, lighter) */}
      <g fill="currentColor" opacity="0.46">
        <polygon points="0,-38  4,0  0,4  -4,0" transform="rotate(45)" />
        <polygon points="0,-38  4,0  0,4  -4,0" transform="rotate(135)" />
        <polygon points="0,-38  4,0  0,4  -4,0" transform="rotate(225)" />
        <polygon points="0,-38  4,0  0,4  -4,0" transform="rotate(315)" />
      </g>

      {/* Cardinal letters */}
      <g
        fill="currentColor"
        opacity="0.92"
        fontFamily='ui-serif, "Newsreader", Georgia, serif'
        fontSize="13"
        fontWeight="600"
        textAnchor="middle"
        dominantBaseline="central"
      >
        <text x="0" y="-63">N</text>
        <text x="63" y="0">E</text>
        <text x="0" y="63">S</text>
        <text x="-63" y="0">W</text>
      </g>
    </svg>
  );
}
