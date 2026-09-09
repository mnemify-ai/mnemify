import { describe, it, expect } from "vitest";
import { argbToHex, cellStyleToProps } from "./cellFormatting";

describe("argbToHex", () => {
  it("strips the alpha channel from an 8-char ARGB", () => {
    expect(argbToHex("FF336699")).toBe("#336699");
  });

  it("returns a 6-char RRGGBB unchanged (prefixed)", () => {
    expect(argbToHex("336699")).toBe("#336699");
  });

  it("accepts lowercase and leading #", () => {
    expect(argbToHex("ff336699")).toBe("#336699");
    expect(argbToHex("#336699")).toBe("#336699");
  });

  it("returns null for missing or malformed input", () => {
    expect(argbToHex(undefined)).toBeNull();
    expect(argbToHex("")).toBeNull();
    expect(argbToHex("123")).toBeNull();
    expect(argbToHex("not-hex")).toBeNull();
  });
});

describe("cellStyleToProps", () => {
  it("returns empty result for undefined style", () => {
    expect(cellStyleToProps(undefined)).toEqual({ className: "", style: {} });
  });

  it("maps bold + italic + underline to Tailwind classes", () => {
    const out = cellStyleToProps({
      font: { bold: true, italic: true, underline: true, strike: true },
    });
    expect(out.className.split(" ").sort()).toEqual(
      ["font-bold", "italic", "line-through", "underline"].sort(),
    );
  });

  it("converts font.size points to px", () => {
    const out = cellStyleToProps({ font: { size: 12 } });
    expect(out.style.fontSize).toBe(16); // 12 * 96/72 = 16
  });

  it("ignores zero or missing font size", () => {
    expect(cellStyleToProps({ font: { size: 0 } }).style.fontSize).toBeUndefined();
    expect(cellStyleToProps({ font: {} }).style.fontSize).toBeUndefined();
  });

  it("sets color from ARGB", () => {
    const out = cellStyleToProps({ font: { color: { argb: "FFC00000" } } });
    expect(out.style.color).toBe("#C00000");
  });

  it("only applies fill for solid patterns", () => {
    const solid = cellStyleToProps({
      fill: { type: "pattern", pattern: "solid", fgColor: { argb: "FFFFFF00" } },
    });
    expect(solid.style.backgroundColor).toBe("#FFFF00");

    const gradient = cellStyleToProps({
      fill: { type: "gradient", fgColor: { argb: "FFFFFF00" } },
    });
    expect(gradient.style.backgroundColor).toBeUndefined();

    const noFill = cellStyleToProps({});
    expect(noFill.style.backgroundColor).toBeUndefined();
  });

  it("maps horizontal alignment", () => {
    expect(
      cellStyleToProps({ alignment: { horizontal: "left" } }).className,
    ).toContain("text-left");
    expect(
      cellStyleToProps({ alignment: { horizontal: "center" } }).className,
    ).toContain("text-center");
    expect(
      cellStyleToProps({ alignment: { horizontal: "right" } }).className,
    ).toContain("text-right");
    expect(
      cellStyleToProps({ alignment: { horizontal: "centerContinuous" } })
        .className,
    ).toContain("text-center");
  });

  it("turns wrapText on via inline whiteSpace so it wins specificity over the base nowrap rule", () => {
    const out = cellStyleToProps({ alignment: { wrapText: true } });
    expect(out.style.whiteSpace).toBe("normal");
    expect(out.style.wordBreak).toBe("break-word");
    // We do NOT override overflow — base `.sheet-cell { overflow: hidden }`
    // keeps wrapped text from bleeding out vertically into the next row.
    expect(out.style.overflow).toBeUndefined();
    expect(out.className).not.toContain("whitespace-normal");
  });

  it("converts indent levels to padding-left", () => {
    const out = cellStyleToProps({ alignment: { indent: 2 } });
    expect(out.style.paddingLeft).toBe("40px"); // 12 + 2*14
  });

  it("ignores zero or missing indent", () => {
    expect(
      cellStyleToProps({ alignment: { indent: 0 } }).style.paddingLeft,
    ).toBeUndefined();
  });
});
