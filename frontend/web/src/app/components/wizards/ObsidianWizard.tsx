import { useEffect, useId, useMemo, useState, type DragEvent } from "react";
import { ExternalLink, FolderOpen, FolderSearch } from "lucide-react";
import { toast } from "sonner";
import { toastSynapse } from "../../lib/toast";
import { WizardModal } from "./WizardModal";
import { LocalTrustNote } from "./LocalTrustNote";
import { Button } from "../ui/Button";
import { FolderBrowser } from "../FolderBrowser";
import { SynapseBurst, shouldShowFirstSynapseBurst } from "../SynapseBurst";
import { TreeScopePicker, type TreeItem } from "./TreeScopePicker";
import {
  useValidateObsidian,
  useSaveObsidian,
  useDiscoverObsidian,
  type BrowseDirResult,
} from "../../api/connections";
import { apiFetch } from "../../api/client";
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

interface ObsidianWizardProps {
  open: boolean;
  onClose: () => void;
}

type ValidatedState =
  | { kind: "idle" }
  | { kind: "ok"; fileCount: number }
  | { kind: "error"; reason: string };

export function ObsidianWizard({ open, onClose }: ObsidianWizardProps) {
  const [step, setStep] = useState(1);
  const [vaultPath, setVaultPath] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [validated, setValidated] = useState<ValidatedState>({ kind: "idle" });
  const [browserOpen, setBrowserOpen] = useState(false);
  const [burstActive, setBurstActive] = useState(false);

  const validate = useValidateObsidian();
  const save = useSaveObsidian();
  const discover = useDiscoverObsidian(
    vaultPath.trim() || null,
    open && step >= 2 && validated.kind === "ok",
  );

  const folderItems: TreeItem[] = useMemo(
    () =>
      (discover.data?.items ?? []).map((it) => ({
        id: it.id,
        title: it.title || it.id,
        kind: it.kind || "folder",
        parent_id: it.parent_id ?? null,
      })),
    [discover.data],
  );

  // Reset validation whenever the user edits the path — forces a re-Validate.
  function updateVaultPath(next: string) {
    setVaultPath(next);
    if (validated.kind !== "idle") setValidated({ kind: "idle" });
  }

  // We deliberately don't call `save.reset()` here — handleSave closes the
  // modal *before* the POST resolves, and reset() detaches the observer from
  // the in-flight mutation, which would swallow the toast + burst callbacks.
  useEffect(() => {
    if (!open) {
      setStep(1);
      setVaultPath("");
      setScope([]);
      setValidated({ kind: "idle" });
      setBrowserOpen(false);
      validate.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function validateAndAdvance() {
    setValidated({ kind: "idle" });
    validate.mutate(vaultPath.trim(), {
      onSuccess: (res) => {
        if (res.ok) {
          setValidated({ kind: "ok", fileCount: res.file_count });
          setStep(2);
        } else {
          setValidated({
            kind: "error",
            reason: res.reason ?? "Vault validation failed.",
          });
        }
      },
      onError: (err) => setValidated({ kind: "error", reason: String(err) }),
    });
  }

  function handleSave() {
    // Close the modal immediately and let the save run in the background.
    const burstGate = shouldShowFirstSynapseBurst();
    save.mutate(
      { vault_path: vaultPath.trim(), scope },
      {
        onSuccess: () => {
          toastSynapse("Obsidian");
          if (burstGate) setBurstActive(true);
        },
        onError: (err) =>
          toast.error("Couldn't save Obsidian connection", { description: String(err) }),
      },
    );
    onClose();
  }

  if (!open && !burstActive) return null;

  if (!open) {
    return <SynapseBurst onDone={() => setBurstActive(false)} />;
  }

  return (
    <>
      <WizardModal
        source="obsidian"
        open={open}
        onClose={onClose}
        step={step}
        totalSteps={2}
        title={
          step === 1
            ? "Where is your vault?"
            : "Limit the harvest to specific folders?"
        }
        onBack={step > 1 ? () => setStep(step - 1) : undefined}
        onContinue={() => {
          if (step === 1) {
            if (validated.kind === "ok") setStep(2);
            else validateAndAdvance();
          } else {
            handleSave();
          }
        }}
        continueDisabled={step === 1 && !vaultPath.trim()}
        continueLabel={step === 2 ? "Save" : undefined}
        pending={save.isPending || (step === 1 && validate.isPending)}
      >
        {step === 1 ? (
          <Step1Path
            vaultPath={vaultPath}
            onVaultPath={updateVaultPath}
            validated={validated}
            onBrowse={() => setBrowserOpen(true)}
          />
        ) : (
          <Step2Scope
            items={folderItems}
            selectedIds={scope}
            onChange={setScope}
            loading={discover.isFetching}
            error={discover.data?.error || null}
          />
        )}
      </WizardModal>
      <FolderBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
        onSelect={(picked) => updateVaultPath(picked)}
        initialPath={vaultPath || "~"}
        vaultsOnly
      />
    </>
  );
}

function Step1Path({
  vaultPath,
  onVaultPath,
  validated,
  onBrowse,
}: {
  vaultPath: string;
  onVaultPath: (v: string) => void;
  validated: ValidatedState;
  onBrowse: () => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [tildeSuggestion, setTildeSuggestion] = useState<string | null>(null);
  const vaultPathId = useId();

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
        onVaultPath(resolved);
        setTildeSuggestion(null);
      } else {
        onVaultPath(folderName);
        toast.message("Couldn't auto-resolve the full path — please complete it manually.");
      }
    } finally {
      setResolving(false);
    }
  }

  function handleBlur() {
    setTildeSuggestion(detectTildeMistake(vaultPath));
  }

  function handleChange(next: string) {
    onVaultPath(next);
    // Clear any stale suggestion as soon as the user edits.
    if (tildeSuggestion) setTildeSuggestion(null);
  }

  function applyTildeFix() {
    if (!tildeSuggestion) return;
    onVaultPath(tildeSuggestion);
    setTildeSuggestion(null);
  }

  return (
    <div className="space-y-5">
      <p className="font-sans text-sm text-muted max-w-prose leading-relaxed">
        Mnemify reads your vault directly from disk — no Obsidian process needed.
        Point it at the folder that contains the{" "}
        <code className="font-mono text-xs">.obsidian/</code> sub-folder.{" "}
        <a
          href="https://help.obsidian.md/Files+and+folders/Vault"
          target="_blank"
          rel="noreferrer"
          className="text-magenta hover:underline inline-flex items-center gap-1"
        >
          More about vaults
          <ExternalLink size={11} aria-hidden />
        </a>
      </p>

      <div>
        <label htmlFor={vaultPathId} className="font-sans text-xs text-muted mb-1.5 block">Vault path</label>
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
              id={vaultPathId}
              type="text"
              value={vaultPath}
              onChange={(e) => handleChange(e.target.value)}
              onBlur={handleBlur}
              placeholder={resolving ? "Resolving dropped folder…" : "~/Documents/MyVault"}
              autoComplete="off"
              spellCheck={false}
              disabled={resolving}
              aria-invalid={validated.kind === "error" || undefined}
              aria-describedby={validated.kind === "error" ? `${vaultPathId}-error` : undefined}
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
          id={`${vaultPathId}-error`}
          role="alert"
          className="font-sans text-xs text-danger -mt-3"
        >
          {validated.reason}
        </p>
      )}

      <LocalTrustNote className="-mt-1">
        Your vault is read in place on this machine — nothing is uploaded and
        nothing leaves it.
      </LocalTrustNote>
    </div>
  );
}

function Step2Scope({
  items,
  selectedIds,
  onChange,
  loading,
  error,
}: {
  items: TreeItem[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="py-12 text-center">
        <p className="font-sans text-sm text-muted animate-pulse">
          Scanning vault folders…
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="py-8">
        <p className="font-sans text-sm text-rose">{error}</p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p className="font-sans text-sm text-muted max-w-prose leading-relaxed">
        Leave everything unchecked to harvest the whole vault. Otherwise pick
        folders — picking a parent includes every nested folder beneath it.
      </p>
      <TreeScopePicker
        items={items}
        selectedIds={selectedIds}
        onChange={onChange}
        emptyMessage="No folders found in this vault."
      />
    </div>
  );
}

