import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Bookmark,
  ChevronRight,
  Database,
  FileText,
  Files,
  Folder,
  Minus,
  Search,
  User,
  Check,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";

export interface TreeItem {
  id: string;
  title: string;
  subtitle?: string;
  /** `"filegroup"` rows are virtual: a collapsible "N files here" bucket that
   *  holds a folder's `"file"` rows. Toggling it toggles its files, its
   *  check state is derived from them, and its id is never part of the
   *  selection — only real folders and files are saved. */
  kind?: string;
  parent_id?: string | null;
}

/** Virtual rows (see `TreeItem.kind`): never selected themselves. */
export function isVirtual(item: TreeItem): boolean {
  return item.kind === "filegroup";
}

interface TreeScopePickerProps {
  items: TreeItem[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  emptyMessage?: string;
  maxHeight?: number;
  /** Rows at depth < this start expanded (0 = everything collapsed). The
   *  local-folder picker uses 1 so the root's files and first-level folders
   *  are visible without clicking. */
  defaultExpandDepth?: number;
}

const ROW_HEIGHT = 44;
const INDENT = 20;

function kindIcon(kind: string | undefined): LucideIcon {
  if (kind === "database") return Database;
  if (kind === "space") return Bookmark;
  if (kind === "personal_space") return User;
  if (kind === "folder") return Folder;
  if (kind === "filegroup") return Files;
  return FileText;
}

interface NodeShape {
  id: string;
  item: TreeItem;
  children: NodeShape[];
}

function buildTree(items: TreeItem[]): NodeShape[] {
  const map = new Map<string, NodeShape>();
  for (const it of items) {
    map.set(it.id, { id: it.id, item: it, children: [] });
  }
  const roots: NodeShape[] = [];
  for (const node of map.values()) {
    const parentId = node.item.parent_id;
    if (parentId && map.has(parentId)) {
      map.get(parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

/**
 * Collect the id of `node` and every descendant.
 */
function descendantIds(node: NodeShape, out: string[] = []): string[] {
  if (!isVirtual(node.item)) out.push(node.id);
  for (const child of node.children) descendantIds(child, out);
  return out;
}

/**
 * Reduce a selection to its topmost roots: ids whose ancestors are all
 * unselected. Used by sources with subtree semantics (Confluence) so the
 * saved scope is "these 2 pages" rather than the 2 pages plus every
 * descendant the picker auto-checked. Unknown ids (e.g. saved scope for
 * nodes discover didn't return) are kept as-is so we never silently drop
 * the user's saved data.
 */
export function minimalScopeRoots(selectedIds: string[], items: TreeItem[]): string[] {
  const byId = new Map(items.map((it) => [it.id, it]));
  const selected = new Set(selectedIds);
  return selectedIds.filter((id) => {
    const item = byId.get(id);
    if (!item) return true;
    let cursor = item.parent_id ?? null;
    let depth = 0;
    while (cursor && depth < 100) {
      if (selected.has(cursor)) return false;
      cursor = byId.get(cursor)?.parent_id ?? null;
      depth += 1;
    }
    return true;
  });
}

/**
 * Inverse of `minimalScopeRoots`: expand a saved root-only scope to include
 * every discovered descendant, so the tree picker renders subtree scope as
 * fully-checked branches instead of lone indeterminate rows.
 */
export function expandScopeWithDescendants(scope: string[], items: TreeItem[]): string[] {
  const childrenByParent = new Map<string, string[]>();
  for (const it of items) {
    if (!it.parent_id) continue;
    const siblings = childrenByParent.get(it.parent_id) ?? [];
    siblings.push(it.id);
    childrenByParent.set(it.parent_id, siblings);
  }
  const out = new Set(scope);
  const queue = [...scope];
  while (queue.length > 0) {
    const id = queue.pop()!;
    for (const child of childrenByParent.get(id) ?? []) {
      if (!out.has(child)) {
        out.add(child);
        queue.push(child);
      }
    }
  }
  return [...out];
}

type CheckState = "checked" | "unchecked" | "indeterminate";

function nodeCheckState(node: NodeShape, selected: Set<string>): CheckState {
  const virtual = isVirtual(node.item);
  if (node.children.length === 0) {
    return !virtual && selected.has(node.id) ? "checked" : "unchecked";
  }
  // A virtual group has no vote of its own — its state is purely its files'.
  let allChecked = virtual ? true : selected.has(node.id);
  let anyChecked = virtual ? false : selected.has(node.id);
  for (const child of node.children) {
    const cs = nodeCheckState(child, selected);
    if (cs === "checked") {
      anyChecked = true;
    } else if (cs === "indeterminate") {
      return "indeterminate";
    } else {
      allChecked = false;
    }
    if (cs !== "checked") allChecked = false;
    if (cs !== "unchecked") anyChecked = true;
  }
  if (allChecked) return "checked";
  if (anyChecked) return "indeterminate";
  return "unchecked";
}

interface FlatRow {
  node: NodeShape;
  depth: number;
  hasChildren: boolean;
}

function flattenVisible(
  nodes: NodeShape[],
  expanded: Set<string>,
  out: FlatRow[] = [],
  depth = 0,
): FlatRow[] {
  for (const node of nodes) {
    out.push({ node, depth, hasChildren: node.children.length > 0 });
    if (node.children.length > 0 && expanded.has(node.id)) {
      flattenVisible(node.children, expanded, out, depth + 1);
    }
  }
  return out;
}

export function TreeScopePicker({
  items,
  selectedIds,
  onChange,
  emptyMessage = "Nothing to pick yet.",
  maxHeight = 360,
  defaultExpandDepth = 0,
}: TreeScopePickerProps) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const tree = useMemo(() => buildTree(items), [items]);

  // Seed the expanded set once items arrive (they load async). Only ever
  // adds, so a user's collapse of a seeded row isn't undone on re-render.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current || defaultExpandDepth <= 0 || tree.length === 0) return;
    seededRef.current = true;
    const seed = new Set<string>();
    function walk(nodes: NodeShape[], depth: number) {
      for (const n of nodes) {
        if (depth < defaultExpandDepth && n.children.length > 0) {
          seed.add(n.id);
          walk(n.children, depth + 1);
        }
      }
    }
    walk(tree, 0);
    setExpanded((prev) => new Set([...prev, ...seed]));
  }, [tree, defaultExpandDepth]);

  // When searching, we collapse to a flat-filter view: every node whose title
  // matches (or whose descendant matches) is shown, with ancestors expanded.
  const filteredTree = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return tree;

    function matches(node: NodeShape): boolean {
      const title = node.item.title.toLowerCase();
      if (title.includes(q) || node.id.toLowerCase().includes(q)) return true;
      return node.children.some(matches);
    }
    function pruneClone(nodes: NodeShape[]): NodeShape[] {
      const out: NodeShape[] = [];
      for (const n of nodes) {
        if (!matches(n)) continue;
        out.push({ ...n, children: pruneClone(n.children) });
      }
      return out;
    }
    return pruneClone(tree);
  }, [tree, search]);

  // While searching, auto-expand all surviving branches so matches are visible.
  const effectiveExpanded = useMemo(() => {
    if (!search.trim()) return expanded;
    const out = new Set<string>();
    function walk(nodes: NodeShape[]) {
      for (const n of nodes) {
        out.add(n.id);
        walk(n.children);
      }
    }
    walk(filteredTree);
    return out;
  }, [search, expanded, filteredTree]);

  const rows = useMemo(
    () => flattenVisible(filteredTree, effectiveExpanded),
    [filteredTree, effectiveExpanded],
  );

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleNode(node: NodeShape) {
    const state = nodeCheckState(node, selectedSet);
    const ids = descendantIds(node);
    const next = new Set(selectedSet);
    if (state === "checked") {
      // Fully checked → uncheck everything beneath (and the node itself).
      for (const id of ids) next.delete(id);
    } else {
      // Unchecked or indeterminate → check everything beneath.
      for (const id of ids) next.add(id);
    }
    onChange([...next]);
  }

  function selectAll() {
    const next = new Set<string>();
    function walk(nodes: NodeShape[]) {
      for (const n of nodes) {
        if (!isVirtual(n.item)) next.add(n.id);
        walk(n.children);
      }
    }
    walk(tree);
    onChange([...next]);
  }
  const selectableCount = useMemo(
    () => items.filter((it) => !isVirtual(it)).length,
    [items],
  );
  function deselectAll() {
    onChange([]);
  }

  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="relative flex-1">
          <Search
            size={14}
            strokeWidth={1.5}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter…"
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-bone/60 border border-hair font-sans text-sm placeholder:text-muted/60 focus:outline-none focus:border-magenta/60"
          />
        </div>
        <div className="flex items-center gap-1 text-xs">
          <button
            type="button"
            onClick={selectAll}
            className="font-sans text-[11px] text-muted hover:text-magenta px-2 py-1 rounded"
          >
            Select all
          </button>
          <span className="text-muted/40" aria-hidden>
            ·
          </span>
          <button
            type="button"
            onClick={deselectAll}
            className="font-sans text-[11px] text-muted hover:text-magenta px-2 py-1 rounded"
          >
            Deselect
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between font-sans text-[11px] text-muted mb-2">
        <span>
          {selectedSet.size.toLocaleString()} / {selectableCount.toLocaleString()} selected
        </span>
        {search && (
          <span className="tabular-nums">{rows.length.toLocaleString()} matches</span>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="bg-bone/40 border border-hair rounded-xl py-12 text-center font-sans text-sm text-muted">
          {items.length === 0 ? emptyMessage : "No matches for that filter."}
        </div>
      ) : (
        <div
          ref={parentRef}
          className="bg-bone/40 border border-hair rounded-xl overflow-y-auto"
          style={{ maxHeight }}
        >
          <div
            style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}
          >
            {rowVirtualizer.getVirtualItems().map((vrow) => {
              const row = rows[vrow.index];
              const node = row.node;
              const Icon = kindIcon(node.item.kind);
              const isFile = node.item.kind === "file";
              const isGroup = isVirtual(node.item);
              const state = nodeCheckState(node, selectedSet);
              const isExpanded = effectiveExpanded.has(node.id);
              return (
                <div
                  key={node.id}
                  className={cn(
                    "absolute top-0 left-0 w-full flex items-center px-2 gap-1.5",
                    "border-b border-hair/40 hover:bg-cream/60 transition-colors",
                    state === "checked" && "bg-magenta/5",
                  )}
                  style={{
                    height: ROW_HEIGHT,
                    transform: `translateY(${vrow.start}px)`,
                    paddingLeft: 8 + row.depth * INDENT,
                  }}
                >
                  {row.hasChildren ? (
                    <button
                      type="button"
                      onClick={() => toggleExpand(node.id)}
                      aria-label={isExpanded ? "Collapse" : "Expand"}
                      className="h-5 w-5 flex items-center justify-center rounded hover:bg-bone shrink-0 text-muted"
                    >
                      <ChevronRight
                        size={13}
                        strokeWidth={2}
                        className={cn(
                          "transition-transform duration-fast",
                          isExpanded && "rotate-90",
                        )}
                      />
                    </button>
                  ) : (
                    <span className="h-5 w-5 shrink-0" aria-hidden />
                  )}
                  <button
                    type="button"
                    onClick={() => toggleNode(node)}
                    className="flex-1 min-w-0 flex items-center gap-2.5 text-left py-1"
                  >
                    <span
                      className={cn(
                        "h-4 w-4 rounded border flex items-center justify-center shrink-0",
                        state === "checked" && "bg-magenta border-magenta",
                        state === "indeterminate" && "bg-magenta/30 border-magenta",
                        state === "unchecked" && "border-line/30 bg-cream",
                      )}
                      aria-hidden
                    >
                      {state === "checked" && (
                        <Check size={11} strokeWidth={3} className="text-cream" />
                      )}
                      {state === "indeterminate" && (
                        <Minus size={11} strokeWidth={3} className="text-magenta" />
                      )}
                    </span>
                    <Icon
                      size={14}
                      strokeWidth={1.5}
                      className={cn("shrink-0", isGroup ? "text-magenta/70" : "text-muted")}
                      aria-hidden
                    />
                    <span className="flex-1 min-w-0">
                      <span
                        className={cn(
                          "block truncate",
                          isFile
                            ? "font-sans text-[13px] text-ink"
                            : isGroup
                              ? "font-sans text-[12px] uppercase tracking-eyebrow text-muted"
                              : "font-serif text-sm text-ink",
                        )}
                      >
                        {node.item.title}
                      </span>
                      {node.item.subtitle && (
                        <span className="block font-mono text-[10px] text-muted truncate">
                          {node.item.subtitle}
                        </span>
                      )}
                    </span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
