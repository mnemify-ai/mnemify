import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { toastSynapse } from "../../lib/toast";
import { WizardModal } from "./WizardModal";
import { LocalTrustNote } from "./LocalTrustNote";
import { FolderBrowser } from "../FolderBrowser";
import { SynapseBurst, shouldShowFirstSynapseBurst } from "../SynapseBurst";
import { TreeScopePicker, type TreeItem } from "./TreeScopePicker";
import { FolderPathField, type FolderValidatedState } from "./FolderPathField";
import {
  useValidateObsidian,
  useSaveObsidian,
  useDiscoverObsidian,
} from "../../api/connections";

// Kept as a re-export so existing imports of the tilde helper keep working.
export { detectTildeMistake } from "./FolderPathField";

interface ObsidianWizardProps {
  open: boolean;
  onClose: () => void;
}

type ValidatedState = FolderValidatedState;

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
        subtitle: it.subtitle ?? undefined,
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
  return (
    <FolderPathField
      label="Vault path"
      value={vaultPath}
      onChange={onVaultPath}
      validated={validated}
      onBrowse={onBrowse}
      placeholder="~/Documents/MyVault"
      intro={
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
      }
    >
      <LocalTrustNote className="-mt-1">
        Your vault is read in place on this machine — nothing is uploaded and
        nothing leaves it.
      </LocalTrustNote>
    </FolderPathField>
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

