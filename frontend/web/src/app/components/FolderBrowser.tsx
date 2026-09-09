import { useState, useEffect } from "react";
import {
  ChevronRight,
  Folder,
  FolderOpen,
  Home,
  ArrowLeft,
  Check,
} from "lucide-react";
import { useBrowseDir } from "../api/connections";
import { Dialog, DialogClose } from "./ui/Dialog";
import { Button } from "./ui/Button";
import { Badge } from "./ui/Badge";
import { cn } from "../lib/cn";

interface FolderBrowserProps {
  open: boolean;
  onClose: () => void;
  /** Called with an absolute filesystem path when the user picks a folder. */
  onSelect: (absolutePath: string) => void;
  /** Initial directory to land on. Defaults to ~. */
  initialPath?: string | null;
  /**
   * Only treat directories with `.obsidian/` as selectable.
   * When false, any folder can be picked.
   */
  vaultsOnly?: boolean;
}

export function FolderBrowser({
  open,
  onClose,
  onSelect,
  initialPath = "~",
  vaultsOnly = true,
}: FolderBrowserProps) {
  const [path, setPath] = useState<string | null>(open ? initialPath : null);

  // Reset path each time the modal opens.
  useEffect(() => {
    if (open) setPath(initialPath ?? "~");
    else setPath(null);
  }, [open, initialPath]);

  const browse = useBrowseDir(open ? path : null);
  const data = browse.data;

  function navigateInto(name: string) {
    if (!data) return;
    setPath(`${data.path.replace(/\/$/, "")}/${name}`);
  }

  function navigateUp() {
    if (data?.parent) setPath(data.parent);
  }

  function pickCurrent() {
    if (!data) return;
    onSelect(data.path);
    onClose();
  }

  const canPick = !vaultsOnly || (data?.is_self_vault ?? false);

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && onClose()}
      width="620px"
      ariaLabel="Pick a folder"
    >
      <DialogClose onClose={onClose} />
      <header className="px-6 pt-6 pb-4 border-b border-hair shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <FolderOpen
            size={18}
            strokeWidth={1.5}
            className="text-magenta"
            aria-hidden
          />
          <h2 className="font-serif text-xl text-ink">Pick a folder</h2>
        </div>
        <PathBreadcrumb path={data?.path ?? path ?? "~"} onJump={setPath} />
        <div className="flex items-center gap-2 mt-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPath("~")}
            disabled={browse.isFetching}
          >
            <Home size={13} strokeWidth={1.5} />
            Home
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={navigateUp}
            disabled={!data?.parent || browse.isFetching}
          >
            <ArrowLeft size={13} strokeWidth={1.5} />
            Up
          </Button>
          {data?.is_self_vault && (
            <Badge tone="sage" className="ml-2">
              <Check size={10} strokeWidth={3} aria-hidden />
              This folder is a vault
            </Badge>
          )}
        </div>
      </header>

      <div className="px-3 py-2 overflow-y-auto" style={{ maxHeight: "50vh" }}>
        {browse.isLoading ? (
          <div className="py-12 text-center font-sans text-sm text-muted animate-pulse">
            Reading directory…
          </div>
        ) : data?.error ? (
          <div className="m-3 px-4 py-3 rounded-lg bg-rose/10 border border-rose/30 font-sans text-sm text-rose">
            {data.error}
          </div>
        ) : !data || data.entries.length === 0 ? (
          <div className="py-12 text-center font-sans text-sm text-muted">
            No subfolders here. Navigate up or pick this folder if it's a vault.
          </div>
        ) : (
          <ul>
            {data.entries.map((e) => (
              <li key={e.name}>
                <button
                  type="button"
                  onClick={() => navigateInto(e.name)}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 rounded-lg",
                    "text-left transition-colors hover:bg-bone/60",
                  )}
                >
                  <Folder
                    size={16}
                    strokeWidth={1.5}
                    className={cn(
                      "shrink-0",
                      e.is_vault ? "text-magenta" : "text-muted",
                    )}
                    aria-hidden
                  />
                  <span className="font-sans text-sm text-ink truncate flex-1">
                    {e.name}
                  </span>
                  {e.is_vault && (
                    <Badge tone="sage" className="shrink-0 !py-0">
                      vault
                    </Badge>
                  )}
                  <ChevronRight
                    size={14}
                    strokeWidth={1.5}
                    className="text-muted/50 shrink-0"
                    aria-hidden
                  />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <footer className="px-6 py-4 border-t border-hair flex items-center justify-between gap-3 shrink-0">
        <p className="font-sans text-[11px] text-muted max-w-xs">
          {vaultsOnly ? (
            data?.is_self_vault ? (
              "This folder contains an Obsidian vault — ready to pick."
            ) : (
              "Navigate into a folder marked with the vault badge, then pick it."
            )
          ) : (
            "Pick any folder."
          )}
        </p>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={pickCurrent}
            disabled={!canPick}
          >
            Use this folder
          </Button>
        </div>
      </footer>
    </Dialog>
  );
}

function PathBreadcrumb({
  path,
  onJump,
}: {
  path: string;
  onJump: (path: string) => void;
}) {
  if (!path) return null;
  const parts = path.split("/").filter(Boolean);
  return (
    <nav
      aria-label="Path"
      className="flex items-center flex-wrap gap-1 font-mono text-xs text-muted"
    >
      <button
        type="button"
        onClick={() => onJump("/")}
        className="hover:text-ink transition-colors"
      >
        /
      </button>
      {parts.map((part, idx) => {
        const full = "/" + parts.slice(0, idx + 1).join("/");
        const isLast = idx === parts.length - 1;
        return (
          <span key={full} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onJump(full)}
              className={cn(
                "hover:text-ink transition-colors px-1 rounded",
                isLast && "text-ink font-medium",
              )}
            >
              {part}
            </button>
            {!isLast && (
              <ChevronRight size={10} className="text-muted/50" aria-hidden />
            )}
          </span>
        );
      })}
    </nav>
  );
}
