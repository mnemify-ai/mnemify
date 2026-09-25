import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import {
  Compass,
  FileText,
  Hammer,
  Home,
  MessageSquare,
  Plug,
  Settings,
  Sparkles,
  Tag as TagIcon,
} from "lucide-react";

import { useAskDockStore } from "../../ask/askDockStore";
import { Dialog } from "./ui/Dialog";
import { AlertDialog } from "./ui/AlertDialog";
import { useMapData } from "../data/MapDataProvider";
import { tagIdToLabel } from "../data/selectors";
import { useStartHarvest } from "../api/harvest";
import { useCommandPalette } from "../lib/commandPalette";
import { cn } from "../lib/cn";

const MAX_NOTE_RESULTS = 8;
const MAX_TAG_RESULTS = 8;

/**
 * Global ⌘K command palette. Mounted once at the route-tree root
 * (DashboardLayout) so all routes inherit it.
 */
export function CommandPalette() {
  const open = useCommandPalette((s) => s.open);
  const setOpen = useCommandPalette((s) => s.setOpen);
  const toggle = useCommandPalette((s) => s.toggle);
  const [search, setSearch] = useState("");
  const [pendingHarvestSource, setPendingHarvestSource] = useState<
    string | null
  >(null);
  const navigate = useNavigate();
  const { data } = useMapData();
  const startHarvest = useStartHarvest();

  // Toggle on ⌘K (macOS) / Ctrl+K (others). Close on Esc (cmdk handles Esc
  // inside its own dialog; we still close from our handler if the dialog
  // didn't catch it).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isToggle =
        e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey) && !e.altKey;
      if (isToggle) {
        e.preventDefault();
        toggle();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  // Reset search when closing.
  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  const run = useCallback(
    (fn: () => void) => {
      setOpen(false);
      // Defer to the next tick so the dialog finishes closing before we
      // navigate or mutate — avoids focus tug-of-war with Radix.
      window.setTimeout(fn, 0);
    },
    [],
  );

  // ── Notes + tags (substring filter against the search box) ────────────
  const notesResults = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    const all = data.notes.notes;
    const matches = q
      ? all.filter((n) => n.title.toLowerCase().includes(q))
      : all;
    return matches.slice(0, MAX_NOTE_RESULTS);
  }, [data, search]);

  const tagResults = useMemo(() => {
    if (!data) return [] as { id: string; label: string }[];
    const q = search.trim().toLowerCase();
    const labelFor = (id: string) =>
      data.indexes.tagLabelById.get(id) ?? tagIdToLabel(id);
    const all = data.renderData.tagIndex.map((id) => ({ id, label: labelFor(id) }));
    const matches = q
      ? all.filter(
          (t) => t.label.toLowerCase().includes(q) || t.id.toLowerCase().includes(q),
        )
      : all;
    return matches.slice(0, MAX_TAG_RESULTS);
  }, [data, search]);

  // ── Action handlers ────────────────────────────────────────────────────
  const requestHarvest = useCallback((source: string) => {
    setOpen(false);
    setPendingHarvestSource(source);
  }, []);

  const confirmHarvest = useCallback(() => {
    if (!pendingHarvestSource) return;
    startHarvest.mutate({ sources: [pendingHarvestSource] });
    setPendingHarvestSource(null);
    navigate("/build/harvest");
  }, [pendingHarvestSource, startHarvest, navigate]);

  const sourceLabel = (source: string) =>
    source.charAt(0).toUpperCase() + source.slice(1);

  return (
    <>
    <Dialog
      open={open}
      onOpenChange={setOpen}
      ariaLabel="Command palette"
      width="620px"
      className="!top-[18%] !-translate-y-0 p-0"
    >
      <Command
        label="Command palette"
        // cmdk's built-in scorer handles ranking; we still keep our own
        // slice() above to cap notes/tags lists.
        className="flex flex-col max-h-[70vh]"
      >
        <div className="px-5 pt-5 pb-3 border-b border-hair">
          <Command.Input
            autoFocus
            value={search}
            onValueChange={setSearch}
            placeholder="Search notes, tags, or jump to…"
            className={cn(
              "w-full bg-transparent outline-none font-serif text-xl",
              "text-ink placeholder:text-muted/70 placeholder:italic",
              "transition-colors duration-200",
            )}
          />
        </div>

        <Command.List className="overflow-y-auto flex-1 px-2 py-2">
          <Command.Empty className="px-4 py-8 text-center font-serif italic text-muted">
            Nothing matches "{search}".
          </Command.Empty>

          {/* Notes ----------------------------------------------------- */}
          {notesResults.length > 0 && (
            <Command.Group
              heading="Notes"
              className={cn(
                "px-1 py-1",
                "[&_[cmdk-group-heading]]:eyebrow",
                "[&_[cmdk-group-heading]]:px-3",
                "[&_[cmdk-group-heading]]:pt-2",
                "[&_[cmdk-group-heading]]:pb-1",
              )}
            >
              {notesResults.map((note) => (
                <PaletteItem
                  key={`note:${note.id}`}
                  value={`note ${note.title} ${note.primaryTagId}`}
                  icon={<FileText size={15} strokeWidth={1.5} />}
                  label={note.title}
                  hint={note.source}
                  onSelect={() =>
                    run(() =>
                      navigate(
                        `/?tag=${encodeURIComponent(note.primaryTagId)}`,
                      ),
                    )
                  }
                />
              ))}
            </Command.Group>
          )}

          {/* Tags ------------------------------------------------------ */}
          {tagResults.length > 0 && (
            <Command.Group
              heading="Tags"
              className={cn(
                "px-1 py-1",
                "[&_[cmdk-group-heading]]:eyebrow",
                "[&_[cmdk-group-heading]]:px-3",
                "[&_[cmdk-group-heading]]:pt-2",
                "[&_[cmdk-group-heading]]:pb-1",
              )}
            >
              {tagResults.map((tag) => (
                <PaletteItem
                  key={`tag:${tag.id}`}
                  value={`tag ${tag.label} ${tag.id}`}
                  icon={<TagIcon size={15} strokeWidth={1.5} />}
                  label={tag.label}
                  hint="Open in map"
                  onSelect={() =>
                    run(() =>
                      navigate(`/?tag=${encodeURIComponent(tag.id)}`),
                    )
                  }
                />
              ))}
            </Command.Group>
          )}

          {/* Navigation ------------------------------------------------ */}
          <Command.Group
            heading="Navigation"
            className={cn(
              "px-1 py-1",
              "[&_[cmdk-group-heading]]:eyebrow",
              "[&_[cmdk-group-heading]]:px-3",
              "[&_[cmdk-group-heading]]:pt-2",
              "[&_[cmdk-group-heading]]:pb-1",
            )}
          >
            {data && (
              <PaletteItem
                value="ask chat question brain"
                icon={<MessageSquare size={15} strokeWidth={1.5} />}
                label="Ask your map"
                hint="⌘J"
                onSelect={() => run(() => useAskDockStore.getState().openDock())}
              />
            )}
            <PaletteItem
              value="nav home map"
              icon={<Home size={15} strokeWidth={1.5} />}
              label="Map"
              hint="/"
              onSelect={() => run(() => navigate("/"))}
            />
            <PaletteItem
              value="nav build harvest"
              icon={<Sparkles size={15} strokeWidth={1.5} />}
              label="Build — Harvest"
              hint="/build/harvest"
              onSelect={() => run(() => navigate("/build/harvest"))}
            />
            <PaletteItem
              value="nav build compile report"
              icon={<Hammer size={15} strokeWidth={1.5} />}
              label="Build — Compile"
              hint="/build/compile"
              onSelect={() => run(() => navigate("/build/compile"))}
            />
            <PaletteItem
              value="nav documents docs"
              icon={<FileText size={15} strokeWidth={1.5} />}
              label="Documents"
              hint="/documents"
              onSelect={() => run(() => navigate("/documents"))}
            />
            <PaletteItem
              value="nav settings general"
              icon={<Settings size={15} strokeWidth={1.5} />}
              label="Settings — General"
              hint="/settings"
              onSelect={() => run(() => navigate("/settings"))}
            />
            <PaletteItem
              value="nav build sources connections"
              icon={<Plug size={15} strokeWidth={1.5} />}
              label="Build — Sources"
              hint="/build/sources"
              onSelect={() => run(() => navigate("/build/sources"))}
            />
            <PaletteItem
              value="nav settings data"
              icon={<Settings size={15} strokeWidth={1.5} />}
              label="Settings — Data"
              hint="/settings/data"
              onSelect={() => run(() => navigate("/settings/data"))}
            />
            <PaletteItem
              value="connect notion wizard"
              icon={<Plug size={15} strokeWidth={1.5} />}
              label="Connect Notion…"
              hint="Wizard"
              onSelect={() =>
                run(() => navigate("/build/sources?connect=notion"))
              }
            />
            <PaletteItem
              value="connect obsidian wizard"
              icon={<Plug size={15} strokeWidth={1.5} />}
              label="Connect Obsidian…"
              hint="Wizard"
              onSelect={() =>
                run(() =>
                  navigate("/build/sources?connect=obsidian"),
                )
              }
            />
            <PaletteItem
              value="add local files folder wizard"
              icon={<Plug size={15} strokeWidth={1.5} />}
              label="Add local files…"
              hint="Wizard"
              onSelect={() =>
                run(() =>
                  navigate("/build/sources?connect=localfiles"),
                )
              }
            />
            <PaletteItem
              value="connect confluence wizard"
              icon={<Plug size={15} strokeWidth={1.5} />}
              label="Connect Confluence…"
              hint="Wizard"
              onSelect={() =>
                run(() =>
                  navigate("/build/sources?connect=confluence"),
                )
              }
            />
          </Command.Group>

          {/* Actions --------------------------------------------------- */}
          <Command.Group
            heading="Actions"
            className={cn(
              "px-1 py-1",
              "[&_[cmdk-group-heading]]:eyebrow",
              "[&_[cmdk-group-heading]]:px-3",
              "[&_[cmdk-group-heading]]:pt-2",
              "[&_[cmdk-group-heading]]:pb-1",
            )}
          >
            <PaletteItem
              value="action reharvest notion"
              icon={<Sparkles size={15} strokeWidth={1.5} />}
              label="Re-harvest Notion"
              hint="Start a new run"
              onSelect={() => requestHarvest("notion")}
            />
            <PaletteItem
              value="action reharvest obsidian"
              icon={<Sparkles size={15} strokeWidth={1.5} />}
              label="Re-harvest Obsidian"
              hint="Start a new run"
              onSelect={() => requestHarvest("obsidian")}
            />
            <PaletteItem
              value="action reharvest local files folder"
              icon={<Sparkles size={15} strokeWidth={1.5} />}
              label="Re-harvest local files"
              hint="Start a new run"
              onSelect={() => requestHarvest("localfiles")}
            />
            <PaletteItem
              value="action reharvest confluence"
              icon={<Sparkles size={15} strokeWidth={1.5} />}
              label="Re-harvest Confluence"
              hint="Start a new run"
              onSelect={() => requestHarvest("confluence")}
            />
            <PaletteItem
              value="action open compile report"
              icon={<Compass size={15} strokeWidth={1.5} />}
              label="Open Compile report"
              hint="/build/compile"
              onSelect={() => run(() => navigate("/build/compile"))}
            />
          </Command.Group>
        </Command.List>

        <footer
          id="command-palette-hint"
          aria-describedby="command-palette-hint"
          className={cn(
            "border-t border-hair px-4 py-2",
            "flex items-center justify-between",
            "font-sans text-[11px] uppercase tracking-eyebrow text-muted",
          )}
        >
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate <span className="mx-1.5">·</span>{" "}
            <Kbd>↵</Kbd> select <span className="mx-1.5">·</span>{" "}
            <Kbd>esc</Kbd> close
          </span>
          <span className="italic font-serif normal-case tracking-normal text-[12px]">
            Mnemify
          </span>
        </footer>
      </Command>
    </Dialog>
    <AlertDialog
      open={pendingHarvestSource !== null}
      onOpenChange={(next) => {
        if (!next) setPendingHarvestSource(null);
      }}
      title={
        pendingHarvestSource
          ? `Re-harvest ${sourceLabel(pendingHarvestSource)}?`
          : "Re-harvest?"
      }
      description="This kicks off a fresh harvest run. You can cancel it from the Harvest page once it's running."
      confirmLabel="Start harvest"
      cancelLabel="Not now"
      onConfirm={confirmHarvest}
    />
    </>
  );
}

// ─── Subcomponents ────────────────────────────────────────────────────────

interface PaletteItemProps {
  value: string;
  icon: React.ReactNode;
  label: string;
  hint?: string;
  onSelect: () => void;
}

function PaletteItem({ value, icon, label, hint, onSelect }: PaletteItemProps) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-xl cursor-pointer",
        "transition-colors duration-200",
        "text-ink",
        "data-[selected=true]:bg-bone/80",
        "data-[selected=true]:shadow-[inset_0_0_0_1px_rgb(var(--c-magenta)/0.18)]",
        "hover:bg-bone/60",
      )}
    >
      <span className="text-muted shrink-0">{icon}</span>
      <span className="font-sans text-sm flex-1 truncate">{label}</span>
      {hint && (
        <span className="font-sans text-[11px] text-muted shrink-0 truncate max-w-[40%]">
          {hint}
        </span>
      )}
    </Command.Item>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[1.25rem] px-1 h-[1.1rem] rounded border border-hair bg-bone/80 font-mono text-[10px] text-ink/80 align-middle">
      {children}
    </kbd>
  );
}
