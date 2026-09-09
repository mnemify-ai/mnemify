import { useEffect, useState } from "react";
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
  useDiscoverConfluence,
  useDiscoverNotion,
  useDiscoverObsidian,
  useUpdateScope,
} from "../api/connections";

interface ManageScopeDialogProps {
  source: string; // "notion" | "confluence" | "obsidian"
  open: boolean;
  onClose: () => void;
  /** The source's currently-saved scope (page/db ids, space keys, watch folders). */
  currentScope: string[];
}

/** Re-pick what an already-connected source harvests — no creds re-entry. */
export function ManageScopeDialog({ source, open, onClose, currentScope }: ManageScopeDialogProps) {
  const meta = sourceMeta(source);

  // Discover against the *saved* credentials (token === null → .env fallback).
  const discoverNotion = useDiscoverNotion(null, open && source === "notion");
  const discoverConfluence = useDiscoverConfluence(null, open && source === "confluence");
  const discoverObsidian = useDiscoverObsidian(null, open && source === "obsidian");
  const discover =
    source === "notion"
      ? discoverNotion
      : source === "confluence"
        ? discoverConfluence
        : discoverObsidian;

  const update = useUpdateScope();

  const [selected, setSelected] = useState<string[]>(currentScope);
  const [hydrated, setHydrated] = useState(false);

  // Reset local state whenever the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setSelected(currentScope);
      setHydrated(false);
    }
  }, [open, currentScope]);

  const items: TreeItem[] =
    discover?.data?.items?.map((it) => ({
      id: it.id,
      title: it.title || it.id,
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
          const noun = source === "obsidian" ? "folder" : "item";
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
          } else if (scope.length === 0) {
            toast.success(`${meta.label} scope updated.`, {
              description:
                source === "obsidian"
                  ? "Harvesting the whole vault on the next run."
                  : "Harvesting everything the integration can see on the next run.",
            });
          } else {
            toast.success(`${meta.label} scope updated.`, {
              description: `${scope.length} ${noun}${scope.length === 1 ? "" : "s"} in scope. Click Harvest to refresh.`,
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
      selected={selected}
      setSelected={setSelected}
      handleSave={handleSave}
      update={update}
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
            : source === "confluence"
              ? "Which spaces or pages should Mnemify harvest? Picking a page includes everything beneath it; picking a space includes the whole space. (Uses your saved credentials.)"
              : "Which pages & databases should Mnemify harvest? Expand a row to see its sub-pages — picking a parent includes everything beneath it."}
        </p>
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
                  : "No pages shared with the integration yet."
            }
            maxHeight={360}
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
