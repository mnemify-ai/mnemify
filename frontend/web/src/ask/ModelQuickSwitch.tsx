import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, KeyRound } from "lucide-react";
import { Popover } from "../app/components/ui/Popover";
import { Tooltip } from "../app/components/ui/Tooltip";
import { useSecrets } from "../app/api/secrets";
import { cn } from "../app/lib/cn";
import { describeAuthRoute, resolveAuthRoute, type AuthRouteTone } from "./authRoute";
import { MODEL_CATALOG, findModel, modelLabel } from "./models";
import type { AskEngine, AskSettings } from "./types";
import { useClaudeStatus } from "./useClaudeStatus";

export const PROVIDER_LABELS: Record<AskEngine, string> = {
  claude: "Claude",
  openai: "OpenAI",
};

type Props = {
  settings: AskSettings;
  onChange: (next: AskSettings) => void;
};

/**
 * Composer-footer engine/model quick switch — the fast path for the one
 * setting people actually flip mid-conversation. Keys and the Claude Code
 * status live in the full settings surface, not here. Rows come from the
 * shared model catalog; a custom id typed in Settings shows up as its own
 * (active) row so the pill never lies about what's selected.
 *
 * The pill also names how the next request authenticates — "Claude Code"
 * (the local CLI login) vs "API key" — because the Claude engine can mean
 * either and the difference is who gets billed. See `authRoute.ts`.
 */
export function ModelQuickSwitch({ settings, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const claudeStatus = useClaudeStatus();
  const secrets = useSecrets();
  const route = resolveAuthRoute(settings, secrets.data);
  const auth = describeAuthRoute(route, claudeStatus);
  // What the *Claude* section would use if picked — the CLI unless a browser
  // key is set — so the header can say so before the user switches.
  const claudeAuth = describeAuthRoute(
    settings.anthropicKey.trim() ? "browserKey" : "cli",
    claudeStatus,
  );

  const pick = (provider: AskEngine, model: string) => {
    onChange({ ...settings, provider, model });
    setOpen(false);
  };

  const isCustom = !findModel(settings.provider, settings.model);
  const label = modelLabel(settings.provider, settings.model);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      side="top"
      align="start"
      trigger={
        <button
          type="button"
          className="flex items-center gap-1 rounded-full border border-hair bg-bone/60 px-2.5 py-1 font-sans text-[11px] text-muted transition-colors hover:text-ink"
          aria-label={`Model: ${PROVIDER_LABELS[settings.provider]} ${label}, via ${auth.label}. Change model`}
        >
          {label}
          <span aria-hidden className="text-muted/60">·</span>
          <Tooltip content={auth.detail} side="top">
            <span className="flex items-center gap-1">
              <StatusDot tone={auth.tone} />
              {auth.label}
            </span>
          </Tooltip>
          <ChevronDown size={11} strokeWidth={1.5} aria-hidden />
        </button>
      }
    >
      <div className="w-64 py-1 font-sans text-sm">
        {(["claude", "openai"] as const).map((provider) => (
          <div key={provider}>
            <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-2 text-[10px] uppercase tracking-wide text-muted">
              <span>{PROVIDER_LABELS[provider]}</span>
              {provider === "claude" ? (
                <span className="flex items-center gap-1 normal-case tracking-normal" title={claudeAuth.detail}>
                  <StatusDot tone={claudeAuth.tone} />
                  via {claudeAuth.label}
                </span>
              ) : null}
            </div>
            {MODEL_CATALOG[provider].map((m) => {
              const active = settings.provider === provider && settings.model === m.id;
              return (
                <ModelRow
                  key={m.id}
                  label={m.label}
                  hint={m.hint}
                  active={active}
                  onClick={() => pick(provider, m.id)}
                />
              );
            })}
            {isCustom && settings.provider === provider && (
              <ModelRow
                label={settings.model}
                hint="Custom model id (set in Settings)."
                active
                onClick={() => setOpen(false)}
              />
            )}
          </div>
        ))}
        <div className="mt-1 border-t border-hair pt-1">
          <Link
            to="/settings/ai"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-1.5 text-muted transition-colors hover:bg-bone/60 hover:text-ink"
          >
            <KeyRound size={13} strokeWidth={1.5} aria-hidden />
            Manage engines & keys
          </Link>
        </div>
      </div>
    </Popover>
  );
}

function StatusDot({ tone }: { tone: AuthRouteTone }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        tone === "ok" && "bg-success",
        tone === "warn" && "bg-warning",
        tone === "pending" && "animate-pulse bg-muted/50",
      )}
    />
  );
}

function ModelRow({
  label,
  hint,
  active,
  onClick,
}: {
  label: string;
  hint: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-2 px-3 py-1.5 text-left transition-colors hover:bg-bone/60",
        active ? "text-ink" : "text-muted",
      )}
      aria-pressed={active}
    >
      <Check
        size={13}
        strokeWidth={2}
        aria-hidden
        className={cn("mt-[3px] shrink-0", active ? "opacity-100" : "opacity-0")}
      />
      <span className="min-w-0">
        <span className={cn("block truncate", active && "font-medium")}>{label}</span>
        <span className="block text-[11px] leading-snug text-muted">{hint}</span>
      </span>
    </button>
  );
}
