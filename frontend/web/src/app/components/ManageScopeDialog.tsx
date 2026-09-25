import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Dialog, DialogClose } from "./ui/Dialog";
import { Button } from "./ui/Button";
import {
  TreeScopePicker,
  expandScopeWithDescendants,
  minimalScopeRoots,
  type TreeItem,
} from "./wizards/TreeScopePicker";
import { sourceMeta } from "./SourceBadge";
import {
  splitLocalScopeId,
  useDiscoverConfluence,
  useDiscoverNotion,
  useDiscoverObsidian,
  useDiscoverLocalFiles,
  useUpdateScope,
  type LocalRoot,
} from "../api/connections";

interface ManageScopeDialogProps {
  source: string; // "notion" | "confluence" | "obsidian" | "localfiles"
  open: boolean;
  onClose: () => void;
  /** The source's currently-saved scope (page/db ids, space keys, watch
   *  folders; for local files the flat `<root>::<entry>` ids). */
  currentScope: string[];
  /** Local files only: the linked folders, one tree each. */
  roots?: LocalRoot[];
}

/** Re-pick what an already-connected source harvests — no creds re-entry. */
export function ManageScopeDialog({ source, open, onClose, currentScope, roots }: ManageScopeDialogProps) {
  const meta = sourceMeta(source);
  const isLocal = source === "localfiles";

  // Local files: one tree per linked folder; the picker chooses which.
  const [activeRoot, setActiveRoot] = useState<string | null>(roots?.[0]?.path ?? null);
  useEffect(() => {
    if (open) setActiveRoot(roots?.[0]?.path ?? null);
  }, [open, roots]);

  // Discover against the *saved* credentials (token === null → .env fallback).
  const discoverNotion = useDiscoverNotion(null, open && source === "notion");
  const discoverConfluence = useDiscoverConfluence(null, open && source === "confluence");
  const discoverObsidian = useDiscoverObsidian(null, open && source === "obsidian");
  const discoverLocalFiles = useDiscoverLocalFiles(activeRoot, open && isLocal && activeRoot !== null);
  const isFolderSource = source === "obsidian" || isLocal;
  const discover =
    source === "notion"
      ? discoverNotion
      : source === "confluence"
        ? discoverConfluence
        : source === "localfiles"
          ? discoverLocalFiles
          : discoverObsidian;

  const update = useUpdateScope();

  // Local files keep the WHOLE flat scope in `selected` (every root), but
  // the picker shows one root at a time — so the tree gets that root's
  // entries decoded, and edits are re-encoded back into the full list.
  const [selected, setSelected] = useState<string[]>(currentScope);
  const [hydrated, setHydrated] = useState(false);

  // Reset local state whenever the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setSelected(currentScope);
      setHydrated(false);
    }
  }, [open, currentScope]);

  const localEntriesFor = (root: string): string[] =>
    selected
      .map(splitLocalScopeId)
      .filter((p): p is { root: string; entry: string } => p !== null && p.root === root && p.entry !== "")
      .map((p) => p.entry);
  const treeSelected = isLocal && activeRoot ? localEntriesFor(activeRoot) : selected;
  const setTreeSelected = (next: string[]) => {
    if (!isLocal || !activeRoot) {
      setSelected(next);
      return;
    }
    const others = selected.filter((id) => splitLocalScopeId(id)?.root !== activeRoot);
    const mine = next.length > 0 ? next.map((e) => `${activeRoot}::${e}`) : [`${activeRoot}::`];
    setSelected([...others, ...mine]);
  };

  const items: TreeItem[] =
    discover?.data?.items?.map((it) => ({
      id: it.id,
      title: it.title || it.id,
      subtitle: it.subtitle ?? undefined,
      kind: it.kind,
      parent_id: it.parent_id ?? null,
    })) ?? [];

  // Confluence scope has subtree semantics — the saved scope only stores the
  // topmost picked ids (space keys / root page ids). Once discover returns
  // the tree, expand the selection to the descendants so those branches
  // render fully checked instead of as lone indeterminate rows.
  useEffect(() => {
    if (open && !hydrated && source === "confluence" && items.length > 0) {
      setSelected(expandScopeWithDescendants(currentScope, items));
      setHydrated(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, hydrated, source, items.length]);

  function handleSave() {
    // Confluence: save only the topmost picked ids. Space keys harvest the
    // whole space; page ids harvest that page plus its descendants (the
    // plugin walks the subtree server-side, so pages discover didn't list
    // are still included).
    const scope =
      source === "confluence" ? minimalScopeRoots(selected, items) : selected;
    const previous = new Set(
      source === "confluence"
        ? minimalScopeRoots(currentScope, items)
        : currentScope,
    );
    const added = scope.filter((id) => !previous.has(id));
    update.mutate(
      { source, scope },
      {
        onSuccess: () => {
          const noun = isFolderSource ? "folder" : "item";
          const scopeSize = isLocal
            ? scope.filter((id) => splitLocalScopeId(id)?.entry).length
            : scope.length;
          if (added.length > 0) {
            // Scope-change no longer auto-harvests — the user chooses when to
            // pull. The Connections card surfaces a "pending" indicator until
            // they click Harvest. Reasoning: scheduled harvests aren't the
            // common path; surprise-harvests-on-scope-save trapped the user
            // in a long run they didn't ask for.
            toast.success(
              `Added ${added.length} new ${noun}${added.length === 1 ? "" : "s"} to scope.`,
              { description: "Click Harvest on this connection to pull them in." },
            );
          } else if (scopeSize === 0) {
            toast.success(`${meta.label} scope updated.`, {
              description:
                source === "obsidian"
                  ? "Harvesting the whole vault on the next run."
                  : source === "localfiles"
                    ? "Harvesting the whole folder on the next run."
                  : "Harvesting everything the integration can see on the next run.",
            });
          } else {
            toast.success(`${meta.label} scope updated.`, {
              description: `${scopeSize} ${noun}${scopeSize === 1 ? "" : "s"} in scope. Click Harvest to refresh.`,
            });
          }
          onClose();
        },
        onError: (err) => toast.error("Couldn't update scope", { description: String(err) }),
      },
    );
  }

  return (
    <ManageScopeDialogShell
      open={open}
      onClose={onClose}
      meta={meta}
      source={source}
      discover={discover}
      items={items}
      selected={treeSelected}
      setSelected={setTreeSelected}
      handleSave={handleSave}
      update={update}
      rootPicker={
        isLocal && roots && roots.length > 0 ? (
          <label className="mt-4 flex items-center gap-3 font-sans text-xs text-muted">
            Folder
            <select
              value={activeRoot ?? ""}
              onChange={(e) => setActiveRoot(e.target.value || null)}
              className="min-w-0 flex-1 rounded-lg border border-hair bg-bone/60 px-2.5 py-1.5 font-mono text-xs text-ink focus:outline-none focus:border-magenta/60"
            >
              {roots.map((r) => (
                <option key={r.path} value={r.path}>
                  {r.name} ({r.path})
                </option>
              ))}
            </select>
          </label>
        ) : null
      }
    />
  );
}

function ManageScopeDialogShell({
  open,
  onClose,
  meta,
  source,
  discover,
  items,
  selected,
  setSelected,
  handleSave,
  update,
  rootPicker,
}: {
  open: boolean;
  onClose: () => void;
  meta: { label: string };
  source: string;
  discover: { isLoading: boolean; data?: { error?: string | null } } | null;
  items: TreeItem[];
  selected: string[];
  setSelected: (next: string[]) => void;
  handleSave: () => void;
  update: { isPending: boolean };
  rootPicker?: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()} ariaLabel={`Manage ${meta.label} scope`} width="560px">
      <DialogClose onClose={onClose} />
      <header className="px-7 pt-7 pb-5 border-b border-hair shrink-0">
        <p className="eyebrow mb-1">{meta.label}</p>
        <h2 className="font-serif text-2xl text-ink leading-tight">Manage scope</h2>
        <p className="font-sans text-sm text-muted mt-2 max-w-prose">
          {source === "obsidian"
            ? "Which vault folders should Mnemify harvest? Pick a parent folder to include everything beneath it. Leave empty to harvest the whole vault."
            : source === "localfiles"
              ? "Which parts of each linked folder should Mnemify harvest? Pick sub-folders or single files; leave everything unchecked to harvest that whole folder."
            : source === "confluence"
              ? "Which spaces or pages should Mnemify harvest? Picking a page includes everything beneath it; picking a space includes the whole space. (Uses your saved credentials.)"
              : "Which pages & databases should Mnemify harvest? Expand a row to see its sub-pages — picking a parent includes everything beneath it."}
        </p>
        {rootPicker}
      </header>

      <div className="px-7 py-6 overflow-y-auto flex-1 min-h-0">
        {discover?.isLoading ? (
          <p className="font-sans text-sm text-muted animate-pulse">Loading…</p>
        ) : discover?.data?.error ? (
          <p className="font-sans text-sm text-rose">{discover.data.error}</p>
        ) : (
          <TreeScopePicker
            items={items}
            selectedIds={selected}
            onChange={setSelected}
            emptyMessage={
              source === "confluence"
                ? "No spaces visible — check that the account has access."
                : source === "obsidian"
                  ? "No folders found in the vault."
                  : source === "localfiles"
                    ? "No sub-folders — the whole folder is harvested."
                  : "No pages shared with the integration yet."
            }
            maxHeight={360}
            defaultExpandDepth={source === "localfiles" ? 1 : 0}
          />
        )}
      </div>

      <footer className="px-7 py-4 border-t border-hair flex items-center justify-end gap-3 shrink-0">
        <Button variant="ghost" size="md" onClick={onClose} disabled={update.isPending}>
          Cancel
        </Button>
        <Button variant="primary" size="md" onClick={handleSave} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save scope"}
        </Button>
      </footer>
    </Dialog>
  );
}
