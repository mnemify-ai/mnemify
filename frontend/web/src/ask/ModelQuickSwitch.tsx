import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, KeyRound } from "lucide-react";
import { Popover } from "../app/components/ui/Popover";
import { cn } from "../app/lib/cn";
import { MODEL_CATALOG, findModel, modelLabel } from "./models";
import type { AskEngine, AskSettings } from "./types";

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
 */
export function ModelQuickSwitch({ settings, onChange }: Props) {
  const [open, setOpen] = useState(false);

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
          aria-label={`Model: ${PROVIDER_LABELS[settings.provider]} ${label}. Change model`}
        >
          {label}
          <ChevronDown size={11} strokeWidth={1.5} aria-hidden />
        </button>
      }
    >
      <div className="w-64 py-1 font-sans text-sm">
        {(["claude", "openai"] as const).map((provider) => (
          <div key={provider}>
            <div className="px-3 pb-1 pt-2 text-[10px] uppercase tracking-wide text-muted">
              {PROVIDER_LABELS[provider]}
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
