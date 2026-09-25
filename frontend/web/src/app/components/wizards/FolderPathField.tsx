import { useId, useState, type DragEvent, type ReactNode } from "react";
import { FolderOpen, FolderSearch } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../ui/Button";
import { apiFetch } from "../../api/client";
import type { BrowseDirResult } from "../../api/connections";
import { cn } from "../../lib/cn";

/** Common parent directories to probe when resolving a dropped folder's full path. */
const PROBE_PARENTS = ["~/Documents", "~/Notes", "~", "~/Desktop", "~/Dropbox", "~/iCloud"];

/** Probe `/browse-dir` across common parent dirs for a folder matching `name`.
 *  Returns the first resolved absolute path, or null if no match / endpoint missing. */
async function resolveDroppedFolder(name: string): Promise<string | null> {
  for (const parent of PROBE_PARENTS) {
    try {
      const res = await apiFetch<BrowseDirResult>("/api/connections/browse-dir", {
        method: "POST",
        body: JSON.stringify({ path: parent }),
      });
      if (res.error || !res.entries) continue;
      const hit = res.entries.find((e) => e.name === name);
      if (hit) {
        // Normalise: res.path is absolute; append the matched name.
        const base = res.path.endsWith("/") ? res.path : `${res.path}/`;
        return `${base}${hit.name}`;
      }
    } catch {
      // endpoint missing / network — surface as null and let the caller fall back.
      return null;
    }
  }
  return null;
}

/** Detect doubled-tilde / inverse-tilde mistakes. Returns the corrected path
 *  or null if the input is already clean. */
export function detectTildeMistake(path: string): string | null {
  const trimmed = path.trim();
  if (!trimmed) return null;
  // `~/Users/<name>/rest` → `~/rest` (since ~ already resolves to /Users/<name>)
  const doubled = /^~\/Users\/[^/]+\/?(.*)$/.exec(trimmed);
  if (doubled) {
    const rest = doubled[1] ?? "";
    return rest ? `~/${rest}` : "~";
  }
  // `/Users/<name>/~/rest` → `~/rest`
  const inverse = /^\/Users\/[^/]+\/~\/?(.*)$/.exec(trimmed);
  if (inverse) {
    const rest = inverse[1] ?? "";
    return rest ? `~/${rest}` : "~";
  }
  return null;
}

export type FolderValidatedState =
  | { kind: "idle" }
  | { kind: "ok"; fileCount: number; byFormat?: Record<string, number> }
  | { kind: "error"; reason: string };

interface FolderPathFieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  validated: FolderValidatedState;
  onBrowse: () => void;
  placeholder?: string;
  /** Explanatory copy rendered above the input. */
  intro?: ReactNode;
  /** Trust / hint copy rendered below the input. */
  children?: ReactNode;
}

/** Path input shared by the folder-backed wizards (Obsidian vault, local
 *  folder): typed path, dropped folder (resolved server-side against common
 *  parents), or the Browse… dialog, plus the tilde-mistake nudge. */
export function FolderPathField({
  label,
  value,
  onChange,
  validated,
  onBrowse,
  placeholder = "~/Documents/MyFolder",
  intro,
  children,
}: FolderPathFieldProps) {
  const [dragOver, setDragOver] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [tildeSuggestion, setTildeSuggestion] = useState<string | null>(null);
  const inputId = useId();

  function handleDragEnter(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }
  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "link";
    if (!dragOver) setDragOver(true);
  }
  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    // Only clear when leaving the wrapper, not when crossing into a child.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setDragOver(false);
  }

  async function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const items = e.dataTransfer?.items;
    if (!items || items.length === 0) return;

    // Extract the first dropped folder's name via webkitGetAsEntry().
    let folderName: string | null = null;
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i];
      if (item.kind !== "file") continue;
      // webkitGetAsEntry is non-standard but widely supported.
      type ItemWithEntry = DataTransferItem & {
        webkitGetAsEntry?: () => { isDirectory: boolean; name: string } | null;
      };
      const entry = (item as ItemWithEntry).webkitGetAsEntry?.();
      if (entry && entry.isDirectory) {
        folderName = entry.name;
        break;
      }
    }

    if (!folderName) {
      toast.error("Drop a folder, not a file.");
      return;
    }

    setResolving(true);
    try {
      const resolved = await resolveDroppedFolder(folderName);
      if (resolved) {
        onChange(resolved);
        setTildeSuggestion(null);
      } else {
        onChange(folderName);
        toast.message("Couldn't auto-resolve the full path — please complete it manually.");
      }
    } finally {
      setResolving(false);
    }
  }

  function handleBlur() {
    setTildeSuggestion(detectTildeMistake(value));
  }

  function handleChange(next: string) {
    onChange(next);
    // Clear any stale suggestion as soon as the user edits.
    if (tildeSuggestion) setTildeSuggestion(null);
  }

  function applyTildeFix() {
    if (!tildeSuggestion) return;
    onChange(tildeSuggestion);
    setTildeSuggestion(null);
  }

  return (
    <div className="space-y-5">
      {intro}

      <div>
        <label htmlFor={inputId} className="font-sans text-xs text-muted mb-1.5 block">
          {label}
        </label>
        <div
          className={cn(
            "relative flex items-stretch gap-2 rounded-lg transition-colors",
            dragOver && "ring-2 ring-magenta/40 ring-offset-2 ring-offset-cream",
          )}
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div className="relative flex-1">
            <FolderOpen
              size={14}
              strokeWidth={1.5}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
              aria-hidden
            />
            <input
              id={inputId}
              type="text"
              value={value}
              onChange={(e) => handleChange(e.target.value)}
              onBlur={handleBlur}
              placeholder={resolving ? "Resolving dropped folder…" : placeholder}
              autoComplete="off"
              spellCheck={false}
              disabled={resolving}
              aria-invalid={validated.kind === "error" || undefined}
              aria-describedby={validated.kind === "error" ? `${inputId}-error` : undefined}
              className={cn(
                "w-full pl-9 pr-3 py-2.5 rounded-lg bg-bone/60 border font-mono text-sm placeholder:text-muted/60 focus:outline-none transition-colors",
                dragOver
                  ? "border-dashed border-magenta/60 bg-magenta/5"
                  : validated.kind === "error"
                    ? "border-danger/60 focus:border-danger"
                    : "border-hair focus:border-magenta/60",
              )}
            />
          </div>
          <Button variant="secondary" size="md" onClick={onBrowse}>
            <FolderSearch size={14} strokeWidth={1.5} />
            Browse…
          </Button>
        </div>
        {tildeSuggestion ? (
          <div className="mt-1.5 flex items-center gap-2 flex-wrap">
            <p className="font-sans text-[11px] text-muted">
              Did you mean <code className="font-mono text-ink">{tildeSuggestion}</code>?
            </p>
            <Button variant="ghost" size="sm" onClick={applyTildeFix}>
              Use this
            </Button>
          </div>
        ) : (
          <p className="font-sans text-[11px] text-muted mt-1.5">
            Tip: drag a folder onto the input, or type a path. Tilde (
            <code className="font-mono">~</code>) is your home directory — don't double up.
          </p>
        )}
      </div>

      {validated.kind === "error" && (
        <p
          id={`${inputId}-error`}
          role="alert"
          className="font-sans text-xs text-danger -mt-3"
        >
          {validated.reason}
        </p>
      )}

      {children}
    </div>
  );
}
