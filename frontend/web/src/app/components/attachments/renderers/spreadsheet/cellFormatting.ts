// Map an ExcelJS cell.style to our render props.
//
// ExcelJS exposes a richer style shape than SheetJS's open-source build:
//   { font: { bold, italic, underline, strike, size, color: { argb } },
//     fill: { type, pattern, fgColor: { argb } },
//     alignment: { horizontal, vertical, wrapText, indent } }
//
// We translate the subset that matters for *display fidelity* — font weight,
// color, background fill, alignment, wrapping. Number format stays SheetJS'
// `.w` string (better coverage). Borders are out of scope (XLSX borders
// are per-edge and rarely meaningful in a viewer).

import type { CSSProperties } from "react";

/** Shape we duck-type from ExcelJS cell.style. Kept narrow so we can write
 *  unit tests without importing the full ExcelJS type tree. */
export interface ExcelStyle {
  font?: {
    bold?: boolean;
    italic?: boolean;
    underline?: boolean | string;
    strike?: boolean;
    size?: number; // points
    color?: { argb?: string; theme?: number; tint?: number };
  };
  fill?: {
    type?: string;
    pattern?: string;
    fgColor?: { argb?: string; theme?: number; tint?: number };
    bgColor?: { argb?: string };
  };
  alignment?: {
    horizontal?: string;
    vertical?: string;
    wrapText?: boolean;
    indent?: number;
  };
}

export interface CellRenderProps {
  className: string;
  style: CSSProperties;
}

/** Returns the additional class + inline style derived from this cell's
 *  ExcelJS style metadata. Returns empty when there's nothing to apply
 *  (the orchestrator falls back to its existing numeric-right-align). */
export function cellStyleToProps(style: ExcelStyle | undefined): CellRenderProps {
  if (!style) return { className: "", style: {} };

  const classes: string[] = [];
  const css: CSSProperties = {};

  // Font weight, italics, decoration.
  if (style.font?.bold) classes.push("font-bold");
  if (style.font?.italic) classes.push("italic");
  if (style.font?.underline) classes.push("underline");
  if (style.font?.strike) classes.push("line-through");

  // Size: ExcelJS reports points, browsers render in px. 1pt = 96/72 px.
  if (typeof style.font?.size === "number" && style.font.size > 0) {
    css.fontSize = +((style.font.size * 96) / 72).toFixed(2);
  }

  // Font color. ARGB string is `FFRRGGBB` or sometimes `RRGGBB`.
  const fontHex = argbToHex(style.font?.color?.argb);
  if (fontHex) css.color = fontHex;

  // Fill (solid pattern only — gradients are rare and complex; skip in v1).
  if (style.fill?.type === "pattern" && style.fill.pattern === "solid") {
    const fillHex = argbToHex(style.fill.fgColor?.argb);
    if (fillHex) css.backgroundColor = fillHex;
  }

  // Horizontal alignment.
  switch (style.alignment?.horizontal) {
    case "left":
      classes.push("text-left");
      break;
    case "center":
    case "centerContinuous":
      classes.push("text-center");
      break;
    case "right":
      classes.push("text-right");
      break;
    // "fill", "justify", "distributed" — fall through; we don't model them.
  }

  // Wrap text: allow the cell to wrap to its width. Set via inline style so
  // it wins specificity over the base `.sheet-grid .sheet-cell` nowrap rule
  // (a Tailwind utility class loses that battle and the text bled horizontally
  // into neighboring cells). Keep `overflow: hidden` from the base style so
  // wrapped text clips vertically at the fixed row height — vertical clipping
  // beats horizontal text overlap when columns are dense.
  if (style.alignment?.wrapText) {
    css.whiteSpace = "normal";
    css.wordBreak = "break-word";
  }

  // Indent: ExcelJS uses Excel's "indent level" units; ~14px each in our font.
  if (typeof style.alignment?.indent === "number" && style.alignment.indent > 0) {
    css.paddingLeft = `${12 + style.alignment.indent * 14}px`;
  }

  return { className: classes.join(" "), style: css };
}

/**
 * Normalize an ExcelJS ARGB color string (`FFRRGGBB` or `RRGGBB`) to CSS
 * `#RRGGBB`. Returns null for missing/invalid input. We discard the alpha
 * channel because partial transparency over a virtualized row would look
 * weird (no painted backdrop behind the cell).
 */
export function argbToHex(argb: string | undefined): string | null {
  if (!argb || typeof argb !== "string") return null;
  const clean = argb.replace(/^#/, "").toUpperCase();
  if (clean.length === 8) {
    // ARGB
    return `#${clean.slice(2)}`;
  }
  if (clean.length === 6) {
    return `#${clean}`;
  }
  return null;
}
