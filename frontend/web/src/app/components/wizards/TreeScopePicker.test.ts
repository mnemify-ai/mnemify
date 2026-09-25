import { describe, expect, it } from "vitest";
import { expandScopeWithDescendants, isVirtual, minimalScopeRoots, type TreeItem } from "./TreeScopePicker";

const items: TreeItem[] = [
  { id: "notes", title: "notes", kind: "folder", parent_id: null },
  { id: "files:notes", title: "2 files here", kind: "filegroup", parent_id: "notes" },
  { id: "file:notes/a.md", title: "a.md", kind: "file", parent_id: "files:notes" },
  { id: "file:notes/b.txt", title: "b.txt", kind: "file", parent_id: "files:notes" },
];

describe("virtual file groups", () => {
  it("only filegroup rows are virtual", () => {
    expect(items.filter(isVirtual).map((i) => i.id)).toEqual(["files:notes"]);
  });

  it("expanding a folder reaches through the group to its files", () => {
    expect(expandScopeWithDescendants(["notes"], items).sort()).toEqual(
      ["notes", "files:notes", "file:notes/a.md", "file:notes/b.txt"].sort(),
    );
  });

  it("a file picked under an unpicked folder stays a root", () => {
    expect(minimalScopeRoots(["file:notes/a.md"], items)).toEqual(["file:notes/a.md"]);
  });
});
