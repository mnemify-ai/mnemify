import { ModelSelect } from "./ModelSelect";
import { CLAUDE_MODELS } from "../lib/modelCatalog";
import type { ClaudeModel } from "../api/compileSettings";

/**
 * Per-run Claude model pickers shown in the compile dialog when the engine is
 * Claude CLI or Claude API. Two independent choices — the high-volume chunk
 * extraction step and the region/topic naming step — mirroring Settings →
 * AI & Models, and using the same dropdown as every other model chooser.
 * Defaults come from the saved compile settings (extract = Sonnet, name = Opus).
 */
export function ClaudeModelSelectors({
  extractModel,
  nameModel,
  onExtractChange,
  onNameChange,
}: {
  extractModel: ClaudeModel;
  nameModel: ClaudeModel;
  onExtractChange: (v: ClaudeModel) => void;
  onNameChange: (v: ClaudeModel) => void;
}) {
  return (
    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-3xl">
      <ModelField label="Chunk analysis model" value={extractModel} onChange={onExtractChange} />
      <ModelField label="Region & topic naming model" value={nameModel} onChange={onNameChange} />
    </div>
  );
}

function ModelField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: ClaudeModel;
  onChange: (v: ClaudeModel) => void;
}) {
  return (
    <label className="block">
      <span className="block font-sans text-xs text-muted mb-1.5">{label}</span>
      <ModelSelect
        value={value}
        options={CLAUDE_MODELS}
        onChange={onChange}
        customPlaceholder="e.g. claude-opus-4-7"
        customHint="Any Anthropic model id, or a Claude Code alias like “opus”. Sent as-is."
      />
    </label>
  );
}
