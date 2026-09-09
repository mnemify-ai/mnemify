import { useState } from "react";
import { cn } from "../lib/cn";
import { findModelOption, type ModelOption } from "../lib/modelCatalog";

/** Sentinel <option> value for "type your own model id". */
const CUSTOM = "__custom__";

const customInputCls =
  "w-full rounded-md border border-hair bg-cream px-3 py-1.5 font-mono text-[13px] text-ink outline-none focus:border-ink";

type Props = {
  id?: string;
  value: string;
  options: readonly ModelOption[];
  /** Called with the new model id — on every change for catalog picks, and
   *  on every keystroke for the custom field (unless `commitCustomOnBlur`). */
  onChange: (model: string) => void;
  /** Compile settings save on blur (each save is a PUT); the Ask form edits a
   *  local store and can take every keystroke. */
  commitCustomOnBlur?: boolean;
  customPlaceholder?: string;
  customHint?: string;
  selectClassName?: string;
  inputClassName?: string;
  /** Wraps the hint line under the control. */
  hintClassName?: string;
  className?: string;
};

/**
 * Model picker: a <select> of curated models (label + one-line hint + exact
 * id) with a "Custom model id…" escape hatch that reveals a text field. Shared
 * by the Ask chat settings and the compile settings so both surfaces offer the
 * same lineup and behave the same way.
 */
export function ModelSelect({
  id,
  value,
  options,
  onChange,
  commitCustomOnBlur = false,
  customPlaceholder,
  customHint = "Sent to the provider as-is.",
  selectClassName,
  inputClassName,
  hintClassName,
  className,
}: Props) {
  // Alias-aware: a legacy "sonnet" saved in the config selects the Sonnet row.
  const hit = findModelOption(options, value);
  // Sticky while the user is typing, so the select doesn't snap back to a
  // preset mid-keystroke if the partial id happens to match one.
  const [customOpen, setCustomOpen] = useState(false);
  const isCustom = customOpen || !hit;

  return (
    <div className={cn("space-y-1", className)}>
      <select
        id={id}
        value={isCustom ? CUSTOM : hit.id}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM) {
            setCustomOpen(true);
            return;
          }
          setCustomOpen(false);
          onChange(v);
        }}
        className={cn(
          "w-full rounded-md border border-hair bg-cream px-3 py-1.5 font-sans text-sm text-ink outline-none focus:border-ink",
          selectClassName,
        )}
      >
        {options.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        <option value={CUSTOM}>Custom model id…</option>
      </select>
      {isCustom ? (
        <>
          {commitCustomOnBlur ? (
            <input
              // Uncontrolled: re-seed when a catalog pick changes the value.
              key={value}
              type="text"
              aria-label="Custom model id"
              defaultValue={value}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== value) onChange(v);
              }}
              placeholder={customPlaceholder}
              autoComplete="off"
              spellCheck={false}
              className={cn(customInputCls, inputClassName)}
            />
          ) : (
            <input
              type="text"
              aria-label="Custom model id"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={customPlaceholder}
              autoComplete="off"
              spellCheck={false}
              className={cn(customInputCls, inputClassName)}
            />
          )}
          <span className={cn("block text-[11px] text-muted", hintClassName)}>{customHint}</span>
        </>
      ) : (
        <span className={cn("block text-[11px] text-muted", hintClassName)}>
          {hit.hint} <code className="font-mono text-[10px] text-muted/80">{hit.id}</code>
        </span>
      )}
    </div>
  );
}
