import { describe, expect, it } from "vitest";
import { isSampleHome, isSamplePath, toSamplePath } from "./samplePaths";

describe("toSamplePath", () => {
  it("keeps map links inside the sample", () => {
    expect(toSamplePath("/")).toBe("/sample");
    expect(toSamplePath("/?tag=tag.x")).toBe("/sample?tag=tag.x");
  });

  it("prefixes the pages the sample can show", () => {
    expect(toSamplePath("/regions")).toBe("/sample/regions");
    expect(toSamplePath("/regions/node_1/memory")).toBe("/sample/regions/node_1/memory");
    expect(toSamplePath("/action-items")).toBe("/sample/action-items");
    expect(toSamplePath("/documents?source=notion")).toBe("/sample/documents?source=notion");
  });

  it("leaves the way out alone", () => {
    expect(toSamplePath("/build/sources")).toBeNull();
    expect(toSamplePath("/settings")).toBeNull();
    expect(toSamplePath("/regionsfoo")).toBeNull();
    expect(toSamplePath("https://stencil.notion.site/x")).toBeNull();
    expect(toSamplePath("//evil.example")).toBeNull();
    expect(toSamplePath("activity")).toBeNull();
  });

  it("is idempotent", () => {
    expect(toSamplePath("/sample/regions")).toBe("/sample/regions");
    expect(toSamplePath("/sample?tag=a")).toBe("/sample?tag=a");
  });
});

describe("isSamplePath", () => {
  it("matches the sample subtree only", () => {
    expect(isSamplePath("/sample")).toBe(true);
    expect(isSamplePath("/sample/regions/x")).toBe(true);
    expect(isSamplePath("/samples")).toBe(false);
    expect(isSamplePath("/")).toBe(false);
  });

  it("treats /sample/ as the sample map", () => {
    expect(isSampleHome("/sample/")).toBe(true);
    expect(isSampleHome("/sample/regions")).toBe(false);
  });
});
