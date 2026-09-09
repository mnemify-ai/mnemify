import { useEffect, useId, useMemo, useState } from "react";
import { Eye, EyeOff, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { toastSynapse } from "../../lib/toast";
import { WizardModal } from "./WizardModal";
import { TreeScopePicker, type TreeItem } from "./TreeScopePicker";
import { WizardSetupSteps } from "./WizardSetupSteps";
import { LocalTrustNote } from "./LocalTrustNote";
import { Button } from "../ui/Button";
import { SynapseBurst, shouldShowFirstSynapseBurst } from "../SynapseBurst";
import {
  useValidateNotion,
  useDiscoverNotion,
  useSaveNotion,
} from "../../api/connections";
import { cn } from "../../lib/cn";

interface NotionWizardProps {
  open: boolean;
  onClose: () => void;
}

type ValidatedState =
  | { kind: "idle" }
  | { kind: "ok"; workspace: string; visible: number }
  | { kind: "error"; reason: string };

export function NotionWizard({ open, onClose }: NotionWizardProps) {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [revealToken, setRevealToken] = useState(false);
  const [validated, setValidated] = useState<ValidatedState>({ kind: "idle" });
  const [scope, setScope] = useState<string[]>([]);
  const [scopeInitialized, setScopeInitialized] = useState(false);
  // First-ever-connect particle burst. Gated by localStorage so it fires at
  // most once per browser profile. Per the E5 scoping decision, only the
  // NotionWizard wires the burst (Notion is the most common entry point in
  // the codebase). Concretely: the burst plays on the user's first successful
  // Notion connect on this machine. Connecting Obsidian or Confluence first
  // does NOT consume the gate (those wizards don't call
  // shouldShowFirstSynapseBurst), so the next Notion connect after them will
  // still play. Future work can extend the gate to the other wizards if
  // we want "first synapse" to mean "first of any kind".
  const [burstActive, setBurstActive] = useState(false);

  const validate = useValidateNotion();
  const discover = useDiscoverNotion(
    token || null,
    open && validated.kind === "ok",
  );
  const save = useSaveNotion();

  // Force a re-validate whenever the token changes after a previous result.
  function updateToken(next: string) {
    setToken(next);
    if (validated.kind !== "idle") setValidated({ kind: "idle" });
  }

  // Reset on close. We deliberately don't call `save.reset()` — handleSave
  // closes the modal *before* the POST resolves, and reset() detaches the
  // observer from the in-flight mutation, which would swallow the toast and
  // first-synapse burst callbacks.
  useEffect(() => {
    if (!open) {
      setStep(1);
      setToken("");
      setRevealToken(false);
      setValidated({ kind: "idle" });
      setScope([]);
      setScopeInitialized(false);
      validate.reset();
    }
    // we deliberately don't include reset functions in deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Pre-select everything once discover lands.
  useEffect(() => {
    if (!scopeInitialized && discover.data?.items) {
      setScope(discover.data.items.map((it) => it.id));
      setScopeInitialized(true);
    }
  }, [discover.data, scopeInitialized]);

  function validateAndAdvance() {
    setValidated({ kind: "idle" });
    validate.mutate(token.trim(), {
      onSuccess: (res) => {
        if (res.ok) {
          setValidated({
            kind: "ok",
            workspace: res.workspace_name,
            visible: res.visible_count,
          });
          setStep(2);
        } else {
          setValidated({ kind: "error", reason: res.reason });
        }
      },
      onError: (err) => setValidated({ kind: "error", reason: String(err) }),
    });
  }

  function handleSave() {
    // Close the modal immediately and let the save run in the background — the
    // POST can take several seconds and the frozen dialog felt broken. Capture
    // the workspace label by value since `validated` resets on close.
    const workspaceLabel = validated.kind === "ok" ? validated.workspace : "Notion";
    const burstGate = shouldShowFirstSynapseBurst();
    save.mutate(
      { token: token.trim(), scope },
      {
        onSuccess: () => {
          toastSynapse(workspaceLabel);
          if (burstGate) setBurstActive(true);
        },
        onError: (err) =>
          toast.error("Couldn't save Notion connection", { description: String(err) }),
      },
    );
    onClose();
  }

  const scopeItems: TreeItem[] = useMemo(
    () =>
      (discover.data?.items ?? []).map((it) => ({
        id: it.id,
        title: it.title || "Untitled",
        kind: it.kind,
        parent_id: it.parent_id ?? null,
      })),
    [discover.data],
  );

  // We still need to render the burst after `open` flips to false (since
  // closing the modal is exactly when we want the burst visible). Only bail
  // when neither the wizard nor the burst is active.
  if (!open && !burstActive) return null;

  if (!open) {
    // Burst-only render: modal has closed, particles still in flight.
    return <SynapseBurst onDone={() => setBurstActive(false)} />;
  }

  const visibleCount =
    discover.data?.total_accessible ??
    (validated.kind === "ok" ? validated.visible : 0);

  return (
    <WizardModal
      source="notion"
      open={open}
      onClose={onClose}
      step={step}
      totalSteps={2}
      title={
        step === 1
          ? "Connect your Notion workspace"
          : "Which pages should Mnemify learn from?"
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
      continueDisabled={
        (step === 1 && !token.trim()) ||
        (step === 2 && scope.length === 0)
      }
      continueLabel={step === 2 ? `Save (${scope.length})` : undefined}
      pending={save.isPending || (step === 1 && validate.isPending)}
    >
      {step === 1 && (
        <Step1Setup
          token={token}
          revealToken={revealToken}
          onToken={updateToken}
          onReveal={() => setRevealToken((v) => !v)}
          validated={validated}
        />
      )}
      {step === 2 && (
        <Step2Scope
          items={scopeItems}
          selectedIds={scope}
          onChange={setScope}
          loading={discover.isLoading}
          error={discover.data?.error || (discover.error ? String(discover.error) : null)}
          visible={visibleCount}
          discovering={discover.isFetching}
          onRescan={() => discover.refetch()}
        />
      )}
    </WizardModal>
  );
}

// ─── Step components ───────────────────────────────────────────────────

function Step1Setup({
  token,
  revealToken,
  onToken,
  onReveal,
  validated,
}: {
  token: string;
  revealToken: boolean;
  onToken: (v: string) => void;
  onReveal: () => void;
  validated: ValidatedState;
}) {
  const tokenInputId = useId();
  return (
    <WizardSetupSteps
      steps={[
        {
          title: <>Create a Notion integration</>,
          link: {
            href: "https://www.notion.so/my-integrations",
            label: "notion.so/my-integrations",
          },
          body: <>Pick a name (e.g. <em>Mnemify</em>) and copy the token it generates.</>,
        },
        {
          title: <>Share each page or database with the integration</>,
          body: (
            <>
              In Notion, open a page → click <code className="font-mono text-[11px]">···</code> →
              <em> Connections</em> → select your integration. Repeat for everything you want
              Mnemify to learn from.
            </>
          ),
        },
        {
          title: <>Paste the token below and click Continue</>,
          body: <>Mnemify checks the token can see your pages before saving anything.</>,
        },
      ]}
    >
      <div>
        <label htmlFor={tokenInputId} className="font-sans text-xs text-muted mb-1.5 block">
          Notion integration token
        </label>
        <div className="relative">
          <input
            id={tokenInputId}
            type={revealToken ? "text" : "password"}
            value={token}
            onChange={(e) => onToken(e.target.value)}
            placeholder="secret_••••••••••••••••••••"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={validated.kind === "error" || undefined}
            aria-describedby={validated.kind === "error" ? `${tokenInputId}-error` : undefined}
            className={cn(
              "w-full px-3 py-2.5 pr-10 rounded-lg bg-bone/60 border font-mono text-sm placeholder:text-muted/60 focus:outline-none",
              validated.kind === "error"
                ? "border-danger/60 focus:border-danger"
                : "border-hair focus:border-magenta/60",
            )}
          />
          <button
            type="button"
            onClick={onReveal}
            aria-label={revealToken ? "Hide token" : "Show token"}
            className="absolute top-1/2 right-2 -translate-y-1/2 p-1.5 text-muted hover:text-ink"
          >
            {revealToken ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
        {validated.kind === "error" && (
          <p
            id={`${tokenInputId}-error`}
            role="alert"
            className="mt-1.5 font-sans text-xs text-danger"
          >
            {validated.reason}
          </p>
        )}
        <LocalTrustNote className="mt-2.5">
          Your token is stored in a local{" "}
          <code className="font-mono text-[11px]">.env</code> on this machine and
          never leaves it.
        </LocalTrustNote>
      </div>
    </WizardSetupSteps>
  );
}

function Step2Scope({
  items,
  selectedIds,
  onChange,
  loading,
  error,
  visible,
  discovering,
  onRescan,
}: {
  items: TreeItem[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  loading: boolean;
  error: string | null;
  visible: number;
  discovering: boolean;
  onRescan: () => void;
}) {
  if (loading) {
    return (
      <div className="py-12 text-center">
        <p className="font-sans text-sm text-muted animate-pulse">
          Loading accessible pages…
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
    <div>
      <div className="flex items-start justify-between gap-3 mb-4">
        <p className="font-sans text-sm text-muted max-w-prose">
          Pick the pages and databases Mnemify should harvest. Expand a row
          to see its sub-pages — picking a parent includes everything beneath it.
        </p>
        <Button
          variant="ghost"
          size="md"
          onClick={onRescan}
          disabled={discovering}
        >
          <RefreshCw
            size={14}
            strokeWidth={1.5}
            className={discovering ? "animate-spin" : undefined}
          />
          Rescan pages
        </Button>
      </div>
      {visible === 0 && !discovering ? (
        <p className="font-sans text-xs text-muted mb-3">
          No pages shared with the integration yet. Share at least one in Notion,
          then click <em>Rescan pages</em>.
        </p>
      ) : null}
      <TreeScopePicker
        items={items}
        selectedIds={selectedIds}
        onChange={onChange}
        emptyMessage="No pages visible yet. Share some in Notion, then click Rescan pages."
      />
    </div>
  );
}

