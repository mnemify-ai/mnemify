import { useEffect, useId, useMemo, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { toastSynapse } from "../../lib/toast";
import { WizardModal } from "./WizardModal";
import { TreeScopePicker, minimalScopeRoots, type TreeItem } from "./TreeScopePicker";
import { WizardSetupSteps } from "./WizardSetupSteps";
import { LocalTrustNote } from "./LocalTrustNote";
import { SynapseBurst, shouldShowFirstSynapseBurst } from "../SynapseBurst";
import {
  useValidateConfluence,
  useDiscoverConfluence,
  useSaveConfluence,
  type ConfluenceCreds,
} from "../../api/connections";
import { cn } from "../../lib/cn";

interface ConfluenceWizardProps {
  open: boolean;
  onClose: () => void;
}

type ValidatedState =
  | { kind: "idle" }
  | { kind: "ok"; workspace: string; visible: number }
  | { kind: "error"; reason: string };

export function ConfluenceWizard({ open, onClose }: ConfluenceWizardProps) {
  const [step, setStep] = useState(1);
  const [baseUrl, setBaseUrl] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [revealToken, setRevealToken] = useState(false);
  const [validated, setValidated] = useState<ValidatedState>({ kind: "idle" });
  const [scope, setScope] = useState<string[]>([]);
  const [scopeInitialized, setScopeInitialized] = useState(false);
  const [burstActive, setBurstActive] = useState(false);

  const validate = useValidateConfluence();
  const creds: ConfluenceCreds | null =
    validated.kind === "ok"
      ? {
          base_url: baseUrl.trim().replace(/\/$/, ""),
          email: email.trim(),
          token: token.trim(),
        }
      : null;
  const discover = useDiscoverConfluence(creds, open && step >= 2);
  const save = useSaveConfluence();

  // Reset validation whenever any credential changes — re-Test required.
  function resetValidationIfDirty() {
    if (validated.kind !== "idle") setValidated({ kind: "idle" });
  }
  function updateBaseUrl(next: string) {
    setBaseUrl(next);
    resetValidationIfDirty();
  }
  function updateEmail(next: string) {
    setEmail(next);
    resetValidationIfDirty();
  }
  function updateToken(next: string) {
    setToken(next);
    resetValidationIfDirty();
  }

  // We deliberately don't call `save.reset()` here — handleSave closes the
  // modal *before* the POST resolves, and reset() detaches the observer from
  // the in-flight mutation, which would swallow the toast + burst callbacks.
  useEffect(() => {
    if (!open) {
      setStep(1);
      setBaseUrl("");
      setEmail("");
      setToken("");
      setRevealToken(false);
      setValidated({ kind: "idle" });
      setScope([]);
      setScopeInitialized(false);
      validate.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!scopeInitialized && discover.data?.items) {
      setScope(discover.data.items.map((it) => it.id));
      setScopeInitialized(true);
    }
  }, [discover.data, scopeInitialized]);

  const fieldsFilled =
    baseUrl.trim().length > 0 && email.trim().length > 0 && token.trim().length > 0;

  function validateAndAdvance() {
    setValidated({ kind: "idle" });
    validate.mutate(
      {
        base_url: baseUrl.trim().replace(/\/$/, ""),
        email: email.trim(),
        token: token.trim(),
      },
      {
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
      },
    );
  }

  function handleSave() {
    if (!creds) return;
    // Close the modal immediately and let the save run in the background.
    const workspaceLabel = validated.kind === "ok" ? validated.workspace : "Confluence";
    const burstGate = shouldShowFirstSynapseBurst();
    // Persist only the topmost picked ids: space keys harvest whole spaces,
    // page ids harvest that page + descendants. Sending the raw selection
    // would bloat the config with every descendant page id.
    save.mutate(
      { ...creds, scope: minimalScopeRoots(scope, scopeItems) },
      {
        onSuccess: () => {
          toastSynapse(workspaceLabel);
          if (burstGate) setBurstActive(true);
        },
        onError: (err) =>
          toast.error("Couldn't save Confluence connection", { description: String(err) }),
      },
    );
    onClose();
  }

  const scopeItems: TreeItem[] = useMemo(
    () =>
      (discover.data?.items ?? []).map((it) => ({
        id: it.id,
        title: it.title || it.id,
        subtitle: it.id,
        kind: it.kind || "space",
        parent_id: it.parent_id ?? null,
      })),
    [discover.data],
  );

  if (!open && !burstActive) return null;

  if (!open) {
    return <SynapseBurst onDone={() => setBurstActive(false)} />;
  }

  return (
    <WizardModal
      source="confluence"
      open={open}
      onClose={onClose}
      step={step}
      totalSteps={2}
      title={
        step === 1
          ? "Connect your Confluence workspace"
          : "Which spaces should Mnemify watch?"
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
        (step === 1 && !fieldsFilled) ||
        (step === 2 && scope.length === 0)
      }
      continueLabel={step === 2 ? `Save (${scope.length})` : undefined}
      pending={save.isPending || (step === 1 && validate.isPending)}
    >
      {step === 1 ? (
        <Step1Credentials
          baseUrl={baseUrl}
          email={email}
          token={token}
          revealToken={revealToken}
          onBaseUrl={updateBaseUrl}
          onEmail={updateEmail}
          onToken={updateToken}
          onReveal={() => setRevealToken((v) => !v)}
          validated={validated}
        />
      ) : (
        <Step2Spaces
          items={scopeItems}
          selectedIds={scope}
          onChange={setScope}
          loading={discover.isLoading}
          error={discover.data?.error || (discover.error ? String(discover.error) : null)}
        />
      )}
    </WizardModal>
  );
}

function Step1Credentials({
  baseUrl,
  email,
  token,
  revealToken,
  onBaseUrl,
  onEmail,
  onToken,
  onReveal,
  validated,
}: {
  baseUrl: string;
  email: string;
  token: string;
  revealToken: boolean;
  onBaseUrl: (v: string) => void;
  onEmail: (v: string) => void;
  onToken: (v: string) => void;
  onReveal: () => void;
  validated: ValidatedState;
}) {
  const baseUrlId = useId();
  const emailId = useId();
  const tokenId = useId();
  return (
    <WizardSetupSteps
      steps={[
        {
          title: <>Generate an API token in your Atlassian account</>,
          link: {
            href: "https://id.atlassian.com/manage-profile/security/api-tokens",
            label: "id.atlassian.com/manage-profile",
          },
          body: <>Copy the token — Atlassian only shows it once.</>,
        },
        {
          title: <>Confirm your site's base URL</>,
          body: (
            <>
              It usually looks like <code className="font-mono text-[11px]">https://yourco.atlassian.net/wiki</code>.
              Use the address from your browser when you're on a Confluence page.
            </>
          ),
        },
        {
          title: <>Paste your base URL, login email, and token below — then click Continue</>,
          body: <>Mnemify verifies the credentials against your site before saving anything.</>,
        },
      ]}
    >
      <Field label="Confluence base URL" htmlFor={baseUrlId}>
        <input
          id={baseUrlId}
          type="url"
          value={baseUrl}
          onChange={(e) => onBaseUrl(e.target.value)}
          placeholder="https://acme.atlassian.net/wiki"
          autoComplete="off"
          className="w-full px-3 py-2.5 rounded-lg bg-bone/60 border border-hair font-mono text-sm placeholder:text-muted/60 focus:outline-none focus:border-magenta/60"
        />
      </Field>

      <Field label="Email" htmlFor={emailId}>
        <input
          id={emailId}
          type="email"
          value={email}
          onChange={(e) => onEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          className="w-full px-3 py-2.5 rounded-lg bg-bone/60 border border-hair font-sans text-sm placeholder:text-muted/60 focus:outline-none focus:border-magenta/60"
        />
      </Field>

      <Field label="API token" htmlFor={tokenId}>
        <div className="relative">
          <input
            id={tokenId}
            type={revealToken ? "text" : "password"}
            value={token}
            onChange={(e) => onToken(e.target.value)}
            placeholder="••••••••••••••••••••"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={validated.kind === "error" || undefined}
            aria-describedby={validated.kind === "error" ? `${tokenId}-error` : undefined}
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
            id={`${tokenId}-error`}
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
      </Field>
    </WizardSetupSteps>
  );
}

function Step2Spaces({
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
          Loading accessible spaces…
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
      <p className="font-sans text-sm text-muted mb-4 max-w-prose">
        Each row shows the <strong>space key</strong> (the actual identifier
        the harvester uses) and the space name. Pick the ones you want Mnemify
        to learn from.
      </p>
      <TreeScopePicker
        items={items}
        selectedIds={selectedIds}
        onChange={onChange}
        emptyMessage="No spaces visible to that account."
      />
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="font-sans text-xs text-muted mb-1.5 block">{label}</label>
      {children}
    </div>
  );
}

