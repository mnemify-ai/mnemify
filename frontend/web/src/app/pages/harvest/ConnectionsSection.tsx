import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useConnections, useDisconnect } from "../../api/connections";
import { useStartHarvest } from "../../api/harvest";
import { ConnectionCard, type CardState } from "../../components/ConnectionCard";
import { Button } from "../../components/ui/Button";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { BuildSectionTabs } from "../../components/BuildSectionTabs";
import { ManageScopeDialog } from "../../components/ManageScopeDialog";
import { sourceMeta } from "../../components/SourceBadge";
import { NotionWizard } from "../../components/wizards/NotionWizard";
import { ConfluenceWizard } from "../../components/wizards/ConfluenceWizard";
import { ObsidianWizard } from "../../components/wizards/ObsidianWizard";
import { LocalFilesWizard } from "../../components/wizards/LocalFilesWizard";
import { PageShell } from "../../layouts/PageShell";

const SUPPORTED = ["notion", "obsidian", "confluence", "localfiles"] as const;
const COMING_SOON = [
  "jira",
  "gmail",
  "slack",
  "google_calendar",
  "google_drive",
  "outlook",
  "onedrive",
  "teams",
  "sharepoint",
  "github",
  "linear",
] as const;

export function ConnectionsSection() {
  const connections = useConnections();
  const { hash } = useLocation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const startHarvest = useStartHarvest();
  const disconnect = useDisconnect();
  const highlightedSource = hash ? hash.slice(1) : null;
  const openWizardFor = params.get("connect");
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null);
  const [scopeTarget, setScopeTarget] = useState<string | null>(null);

  const closeWizard = useCallback(() => {
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        out.delete("connect");
        return out;
      },
      { replace: true },
    );
  }, [setParams]);

  const connectionByName = useMemo(
    () => new Map((connections.data ?? []).map((c) => [c.source, c])),
    [connections.data],
  );
  const connectedCount = connections.data?.filter((c) => c.status === "connected").length ?? 0;

  function openWizard(source: string) {
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        out.set("connect", source);
        return out;
      },
      { replace: false },
    );
  }

  function handleHarvestAll() {
    startHarvest.mutate(
      { sources: null },
      {
        onSuccess: () => {
          toast.success(`Harvesting ${connectedCount} source${connectedCount === 1 ? "" : "s"}…`);
          navigate("/build/harvest");
        },
        onError: (err) => toast.error("Couldn't start harvest", { description: String(err) }),
      },
    );
  }

  function confirmDisconnect() {
    if (!disconnectTarget) return;
    const src = disconnectTarget;
    disconnect.mutate(src, {
      onSuccess: () => {
        toast.success(`${sourceMeta(src).label} ${sourceMeta(src).verb.past}.`, {
          description: "Harvested data is preserved on disk.",
        });
        setDisconnectTarget(null);
      },
      onError: (err) => {
        toast.error("Couldn't disconnect", { description: String(err) });
        setDisconnectTarget(null);
      },
    });
  }

  const scopeConn = scopeTarget ? connectionByName.get(scopeTarget) : null;

  return (
    <PageShell
      title="Connections"
      description="Wire your tools into Mnemify. Each card shows the live status of the connection — what's harvested, when, and from which workspace — and lets you re-pick scope."
      actions={
        <Button
          variant="primary"
          onClick={handleHarvestAll}
          disabled={connectedCount === 0 || startHarvest.isPending}
        >
          <Sparkles size={14} strokeWidth={1.5} />
          {connectedCount === 0 ? "Harvest all (none connected)" : "Harvest all"}
        </Button>
      }
      tabs={<BuildSectionTabs />}
    >
      <section aria-labelledby="supported-heading">
        <h2 id="supported-heading" className="sr-only">Supported sources</h2>
        {/* Auto-fit grid: as many ~440px tracks as fit. Naturally becomes
            1 / 2 / 3 columns as the viewport grows, with no dead zone where
            two crammed 470px cards look squashed. Each track also caps at
            the container width so cards never overflow on phones. */}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(440px,100%),1fr))] gap-5">
          {SUPPORTED.map((source) => {
            const conn = connectionByName.get(source) ?? null;
            const state: CardState = conn?.status === "connected" ? "connected" : "not_connected";
            return (
              <ConnectionCard
                key={source}
                source={source}
                state={state}
                connection={conn}
                highlighted={highlightedSource === source}
                onConnect={() => openWizard(source)}
                onDisconnect={() => setDisconnectTarget(source)}
                onManageScope={() => setScopeTarget(source)}
              />
            );
          })}
        </div>
      </section>

      <section aria-labelledby="comingsoon-heading" className="mt-10">
        <h2 id="comingsoon-heading" className="eyebrow mb-4">Available in a later v2.x</h2>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(260px,100%),1fr))] gap-5">
          {COMING_SOON.map((source) => (
            <ConnectionCard
              key={source}
              source={source}
              state="not_supported"
              connection={null}
              highlighted={highlightedSource === source}
              onConnect={() => {}}
              onDisconnect={() => {}}
            />
          ))}
        </div>
      </section>

      <NotionWizard open={openWizardFor === "notion"} onClose={closeWizard} />
      <ConfluenceWizard open={openWizardFor === "confluence"} onClose={closeWizard} />
      <ObsidianWizard open={openWizardFor === "obsidian"} onClose={closeWizard} />
      <LocalFilesWizard open={openWizardFor === "localfiles"} onClose={closeWizard} />

      {scopeConn && (
        <ManageScopeDialog
          source={scopeConn.source}
          open={scopeTarget !== null}
          onClose={() => setScopeTarget(null)}
          currentScope={scopeConn.scope ?? []}
          roots={scopeConn.roots}
        />
      )}

      <AlertDialog
        open={disconnectTarget !== null}
        onOpenChange={(v) => !v && setDisconnectTarget(null)}
        title={
          disconnectTarget
            ? `${sourceMeta(disconnectTarget).verb.remove} ${sourceMeta(disconnectTarget).label}?`
            : "Disconnect"
        }
        description={
          disconnectTarget &&
          (disconnectTarget === "localfiles" ? (
            <>
              Mnemify will stop reading this folder and disable it in your{" "}
              <code className="font-mono text-xs">mnemify.yaml</code>. The folder itself is
              untouched.
              <br />
              <br />
              <strong className="text-ink">Already-harvested data stays on disk.</strong> Add the
              folder again any time to pick up where you left off.
            </>
          ) : (
            <>
              Mnemify will remove the credentials from{" "}
              <code className="font-mono text-xs">.env</code> and disable the source in your{" "}
              <code className="font-mono text-xs">mnemify.yaml</code>.
              <br />
              <br />
              <strong className="text-ink">Already-harvested data stays on disk.</strong> Reconnect any
              time to pick up where you left off.
            </>
          ))
        }
        confirmLabel={disconnectTarget ? sourceMeta(disconnectTarget).verb.remove : "Disconnect"}
        tone="destructive"
        confirming={disconnect.isPending}
        onConfirm={confirmDisconnect}
      />
    </PageShell>
  );
}
