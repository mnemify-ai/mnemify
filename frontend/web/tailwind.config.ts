import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        cream: "rgb(var(--c-bg) / <alpha-value>)",
        bone: "rgb(var(--c-bone) / <alpha-value>)",
        lavender: "rgb(var(--c-lavender) / <alpha-value>)",
        rose: "rgb(var(--c-rose) / <alpha-value>)",
        magenta: "rgb(var(--c-magenta) / <alpha-value>)",
        sage: "rgb(var(--c-sage) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        // Semantic intent. Prefer these over raw hue tokens in components.
        success: "rgb(var(--c-success) / <alpha-value>)",
        warning: "rgb(var(--c-warning) / <alpha-value>)",
        info: "rgb(var(--c-info) / <alpha-value>)",
        danger: "rgb(var(--c-danger) / <alpha-value>)",
        // Surface elevation — floating overlays and cards layer cream on cream.
        "surface-0": "rgb(var(--surface-0) / <alpha-value>)",
        "surface-1": "rgb(var(--surface-1) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
      },
      opacity: {
        disabled: "var(--opacity-disabled)",
        hover: "var(--opacity-hover)",
        pressed: "var(--opacity-pressed)",
      },
      fontFamily: {
        serif: ['"Newsreader"', '"Times New Roman"', "Times", "Georgia", "serif"],
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      letterSpacing: {
        eyebrow: "0.18em",
      },
      maxWidth: {
        prose: "72ch",
        // Lifted from 1440px so wider monitors get more usable width.
        // 1680px is large enough to fit a 3-column connection card grid +
        // a doc viewer split comfortably; beyond that line length on text
        // pages becomes unwieldy, so we cap rather than going truly fluid.
        page: "1680px",
      },
      transitionDuration: {
        fast: "150ms",
        base: "240ms",
        slow: "320ms",
        exit: "180ms",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.22, 1, 0.36, 1)",
        in: "cubic-bezier(0.4, 0, 1, 1)",
      },
      animation: {
        "fade-in": "fade-in 0.3s ease-out",
        "slide-in-right": "slide-in-right 0.32s cubic-bezier(0.22, 1, 0.36, 1)",
        "modal-in": "modal-in 240ms cubic-bezier(0.22, 1, 0.36, 1)",
        "skeleton-pulse": "skeleton-pulse 1.2s ease-in-out infinite",
        // On-brand celebration: a soft magenta core + expanding rings.
        "synapse-core": "synapse-core 1100ms cubic-bezier(0.22, 1, 0.36, 1) forwards",
        "synapse-ring": "synapse-ring 1100ms cubic-bezier(0.22, 1, 0.36, 1) forwards",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-in-right": {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(0)" },
        },
        "modal-in": {
          // Keep translate(-50%,-50%) inside the keyframe — the Dialog uses
          // -translate-x-1/2 -translate-y-1/2 utility classes to center itself,
          // but a CSS keyframe targeting `transform` overrides those classes
          // for its entire duration. Without the translate here the dialog
          // briefly renders at top:50% left:50% (i.e. bottom-right quadrant)
          // before snapping to center when the animation ends.
          "0%": { opacity: "0", transform: "translate(-50%, -50%) scale(0.96)" },
          "100%": { opacity: "1", transform: "translate(-50%, -50%) scale(1)" },
        },
        "skeleton-pulse": {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
        "synapse-core": {
          "0%": { transform: "scale(0)", opacity: "0" },
          "40%": { transform: "scale(2)", opacity: "1" },
          "100%": { transform: "scale(0.6)", opacity: "0" },
        },
        "synapse-ring": {
          "0%": { transform: "scale(0.4)", opacity: "0" },
          "30%": { opacity: "0.9" },
          "100%": { transform: "scale(14)", opacity: "0" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
