import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { toastSynapse } from "../../lib/toast";
import { WizardModal } from "./WizardModal";
import { LocalTrustNote } from "./LocalTrustNote";
import { FolderBrowser } from "../FolderBrowser";
import { SynapseBurst, shouldShowFirstSynapseBurst } from "../SynapseBurst";
import { TreeScopePicker, type TreeItem } from "./TreeScopePicker";
import { FolderPathField, type FolderValidatedState } from "./FolderPathField";
import {
  useValidateLocalFiles,
  useSaveLocalFiles,
  useDiscoverLocalFiles,
} from "../../api/connections";

interface LocalFilesWizardProps {
  open: boolean;
  onClose: () => void;
}

/** Human labels for the per-format counts the validate route returns. */
const FORMAT_LABEL: Record<string, string> = {
  md: "Markdown",
  txt: "text",
  pdf: "PDF",
};

export function formatCountSummary(byFormat: Record<string, number> | undefined): string {
  if (!byFormat) return "";
  const parts = Object.entries(byFormat)
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a)
    .map(([fmt, n]) => `${n} ${FORMAT_LABEL[fmt] ?? fmt}`);
  return parts.join(" · ");
}

/** Connect any folder of .md / .txt / .pdf files. Two steps: pick the folder,
 *  optionally narrow to sub-folders. Same shape as the Obsidian wizard minus
 *  the vault check — the folder is read in place, nothing is uploaded. */
export function LocalFilesWizard({ open, onClose }: LocalFilesWizardProps) {
  const [step, setStep] = useState(1);
  const [rootPath, setRootPath] = useState("");
  const [scope, setScope] = useState<string[]>([]);
  const [validated, setValidated] = useState<FolderValidatedState>({ kind: "idle" });
  const [browserOpen, setBrowserOpen] = useState(false);
  const [burstActive, setBurstActive] = useState(false);

  const validate = useValidateLocalFiles();
  const save = useSaveLocalFiles();
  const discover = useDiscoverLocalFiles(
    rootPath.trim() || null,
    open && step >= 2 && validated.kind === "ok",
  );

  const folderItems: TreeItem[] = useMemo(
    () =>
      (discover.data?.items ?? []).map((it) => ({
        id: it.id,
        title: it.title || it.id,
        subtitle: it.subtitle ?? undefined,
        kind: it.kind || "folder",
        parent_id: it.parent_id ?? null,
      })),
    [discover.data],
  );

  function updateRootPath(next: string) {
    setRootPath(next);
    if (validated.kind !== "idle") setValidated({ kind: "idle" });
  }

  useEffect(() => {
    if (!open) {
      setStep(1);
      setRootPath("");
      setScope([]);
      setValidated({ kind: "idle" });
      setBrowserOpen(false);
      validate.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function validateAndAdvance() {
    setValidated({ kind: "idle" });
    validate.mutate(rootPath.trim(), {
      onSuccess: (res) => {
        if (res.ok) {
          setValidated({ kind: "ok", fileCount: res.file_count, byFormat: res.by_format });
          setStep(2);
        } else {
          setValidated({
            kind: "error",
            reason: res.reason ?? "Folder validation failed.",
          });
        }
      },
      onError: (err) => setValidated({ kind: "error", reason: String(err) }),
    });
  }

  function handleSave() {
    const burstGate = shouldShowFirstSynapseBurst();
    save.mutate(
      { root_path: rootPath.trim(), scope },
      {
        onSuccess: (res) => {
          if (res.root_count > 1) {
            toast.success(`Folder linked. ${res.root_count} folders now.`, {
              description: "Run a harvest to pull the new one in.",
            });
          } else {
            toastSynapse("Local files");
            if (burstGate) setBurstActive(true);
          }
        },
        onError: (err) =>
          toast.error("Couldn't save the folder connection", { description: String(err) }),
      },
    );
    onClose();
  }

  if (!open && !burstActive) return null;
  if (!open) return <SynapseBurst onDone={() => setBurstActive(false)} />;

  const found = validated.kind === "ok" ? validated : null;

  return (
    <>
      <WizardModal
        source="localfiles"
        open={open}
        onClose={onClose}
        step={step}
        totalSteps={2}
        title={step === 1 ? "Which folder?" : "Limit this folder to specific sub-folders or files?"}
        onBack={step > 1 ? () => setStep(step - 1) : undefined}
        onContinue={() => {
          if (step === 1) {
            if (validated.kind === "ok") setStep(2);
            else validateAndAdvance();
          } else {
            handleSave();
          }
        }}
        continueDisabled={step === 1 && !rootPath.trim()}
        continueLabel={step === 2 ? "Save" : undefined}
        pending={save.isPending || (step === 1 && validate.isPending)}
      >
        {step === 1 ? (
          <FolderPathField
            label="Folder path"
            value={rootPath}
            onChange={updateRootPath}
            validated={validated}
            onBrowse={() => setBrowserOpen(true)}
            placeholder="~/Documents/Notes"
            intro={
              <p className="font-sans text-sm text-muted max-w-prose leading-relaxed">
                Point Mnemify at any folder on this computer. It reads{" "}
                <code className="font-mono text-xs">.md</code>,{" "}
                <code className="font-mono text-xs">.txt</code> and{" "}
                <code className="font-mono text-xs">.pdf</code> files, including
                sub-folders. PDFs need a text layer — scanned PDFs are skipped.
              </p>
            }
          >
            <LocalTrustNote className="-mt-1">
              The folder is read in place on this machine — nothing is uploaded
              and nothing leaves it.
            </LocalTrustNote>
          </FolderPathField>
        ) : (
          <div className="space-y-4">
            {found && (
              <p className="font-sans text-xs text-sage">
                Found {found.fileCount} file{found.fileCount === 1 ? "" : "s"}
                {found.byFormat && found.fileCount > 0
                  ? ` — ${formatCountSummary(found.byFormat)}`
                  : ""}
                .
              </p>
            )}
            {discover.isFetching ? (
              <p className="py-8 text-center font-sans text-sm text-muted animate-pulse">
                Scanning sub-folders…
              </p>
            ) : discover.data?.error ? (
              <p className="py-4 font-sans text-sm text-rose">{discover.data.error}</p>
            ) : (
              <>
                <p className="font-sans text-sm text-muted max-w-prose leading-relaxed">
                  Leave everything unchecked to harvest the whole folder. Otherwise
                  pick sub-folders, or expand a folder's “files here” row to pick
                  single files — picking a folder includes everything beneath it.
                </p>
                <TreeScopePicker
                  items={folderItems}
                  selectedIds={scope}
                  onChange={setScope}
                  defaultExpandDepth={1}
                  emptyMessage="No supported files here — add .md, .txt or .pdf files, or pick another folder."
                />
              </>
            )}
          </div>
        )}
      </WizardModal>
      <FolderBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
        onSelect={(picked) => updateRootPath(picked)}
        initialPath={rootPath || "~"}
        vaultsOnly={false}
      />
    </>
  );
}
