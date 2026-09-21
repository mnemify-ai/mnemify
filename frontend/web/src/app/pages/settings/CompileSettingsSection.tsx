import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Segmented } from "../../components/ui/Segmented";
import { AlertDialog } from "../../components/ui/AlertDialog";
import {
  type CompileSettings,
  type EffortLevel,
  type EmbeddingModel,
  useCompileSettings,
  useUpdateCompileSettings,
} from "../../api/compileSettings";
import { CLAUDE_CLI_UNAVAILABLE_HINT, isClaudeCliAvailable, useHealth } from "../../api/system";
import type { AiMode } from "../../api/terrain";
import { SettingsSection } from "./SettingsSection";
import { ModelSelect } from "../../components/ModelSelect";
import { CLAUDE_MODELS, OPENAI_MODELS } from "../../lib/modelCatalog";
import { cn } from "../../lib/cn";
import { LOCAL_EMBEDDING_MODEL, prepareLocalEmbeddings, useLocalEmbeddings } from "../../api/embeddings";
import { Pill } from "../../components/ui/Pill";
import { EmbeddingKeyNotice } from "../../components/EmbeddingKeyNotice";

const AI_MODE_OPTIONS: ReadonlyArray<{ value: AiMode; label: string }> = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Claude API" },
  { value: "claude", label: "Claude CLI" },
  { value: "local", label: "Local" },
];

/** Modes that use the per-step Claude model split (CLI and API). */
const CLAUDE_MODEL_MODES: ReadonlyArray<AiMode> = ["claude", "anthropic"];

const EMBEDDING_OPTIONS: ReadonlyArray<{ value: EmbeddingModel; label: string }> = [
  { value: "text-embedding-3-large", label: "OpenAI 3-large" },
  { value: "text-embedding-3-small", label: "OpenAI 3-small" },
  { value: LOCAL_EMBEDDING_MODEL, label: "On-device" },
];

const EFFORT_OPTIONS: ReadonlyArray<{ value: EffortLevel; label: string }> = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "", label: "Default" },
];

const ONOFF: ReadonlyArray<{ value: "on" | "off"; label: string }> = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];

const CONC_MIN = 1;
const CONC_MAX = 32;

const inputCls =
  "h-8 px-2 rounded-md border bg-bone/50 font-sans text-sm text-ink focus:outline-none transition-colors border-hair focus:border-ink/40";

export function CompileSettingsSection() {
  const { data, isLoading } = useCompileSettings();
  const update = useUpdateCompileSettings();
  // The claude CLI is macOS/Linux only — on Windows the mode stays visible but
  // unselectable, so the hint below can say what to use instead.
  const health = useHealth();
  const claudeCli = isClaudeCliAvailable(health.data?.platform);
  const aiModeOptions = claudeCli
    ? AI_MODE_OPTIONS
    : AI_MODE_OPTIONS.map((o) =>
        o.value === "claude"
          ? { ...o, disabled: true, title: CLAUDE_CLI_UNAVAILABLE_HINT }
          : o,
      );

  // Local working copy. The backend PATCH requires the full object, so every
  // save sends the whole draft (one field changed at a time).
  const [draft, setDraft] = useState<CompileSettings | null>(null);
  // Embedding change is special — it needs a fresh recompile to take effect, so
  // it routes through a confirm dialog rather than saving immediately.
  const [pendingEmbedding, setPendingEmbedding] = useState<EmbeddingModel | null>(null);

  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);

  function save(next: CompileSettings) {
    setDraft(next);
    update.mutate(next, {
      onSuccess: () => toast.success("Compile settings saved."),
      onError: (err) => toast.error("Couldn't save", { description: String(err) }),
    });
  }

  if (isLoading || draft == null) {
    return (
      <div className="max-w-3xl">
        <SettingsSection eyebrow="Compile" title="How compiles run">
          <span className="font-sans text-sm text-muted">Loading…</span>
        </SettingsSection>
      </div>
    );
  }

  const d = draft;

  return (
    <div className="max-w-3xl">
      <SettingsSection
        eyebrow="Compile"
        title="How compiles run"
        help={
          <>
            Defaults for building your knowledge map. Each compile uses these unless you
            override them in the compile dialog. Changing the AI engine or models
            affects how names and notes read; changing the embedding model affects how
            notes <em>group</em> — and needs a fresh recompile to take effect.
          </>
        }
      >
        <div className="flex flex-col gap-6">
          {/* AI engine */}
          <Field
            label="AI engine"
            hint={
              claudeCli
                ? "OpenAI (OPENAI_API_KEY), Claude API (ANTHROPIC_API_KEY — works anywhere), Claude CLI (your subscription, local only), or Local heuristics (no LLM). If the engine fails mid-compile, the compile stops with an error instead of degrading — switch to Local here if you want a no-LLM build."
                : `OpenAI (OPENAI_API_KEY), Claude API (ANTHROPIC_API_KEY), or Local heuristics (no LLM). ${CLAUDE_CLI_UNAVAILABLE_HINT}. If the engine fails mid-compile, the compile stops with an error instead of degrading — switch to Local here if you want a no-LLM build.`
            }
          >
            <Segmented<AiMode>
              value={d.ai_mode}
              onValueChange={(v) => save({ ...d, ai_mode: v })}
              options={aiModeOptions}
              ariaLabel="AI engine"
            />
            <EmbeddingKeyNotice aiMode={d.ai_mode} className="max-w-prose" />
          </Field>

          {/* Claude models — both Claude engines (CLI + API). Two independent
              picks: the high-volume chunk extraction step and the region/topic
              naming step. */}
          {CLAUDE_MODEL_MODES.includes(d.ai_mode) && (
            <>
              <Field label="Chunk analysis model" hint="Runs once per chunk — hundreds of calls per compile. A lighter model keeps it fast and cheap.">
                <ModelSelect
                  value={d.claude_extract_model}
                  options={CLAUDE_MODELS}
                  onChange={(v) => save({ ...d, claude_extract_model: v })}
                  commitCustomOnBlur
                  customPlaceholder="e.g. claude-opus-4-7"
                  customHint="Any Anthropic model id, or a Claude Code alias like “opus”. Sent as-is."
                  className="w-72"
                  selectClassName={cn(inputCls, "w-full py-0")}
                  inputClassName={cn(inputCls, "w-full font-mono text-[13px]")}
                />
              </Field>
              <Field label="Region & topic naming model" hint="Writes the region and topic names you actually read — quality shows here, so it defaults to the strongest tier.">
                <ModelSelect
                  value={d.claude_name_model}
                  options={CLAUDE_MODELS}
                  onChange={(v) => save({ ...d, claude_name_model: v })}
                  commitCustomOnBlur
                  customPlaceholder="e.g. claude-opus-4-7"
                  customHint="Any Anthropic model id, or a Claude Code alias like “opus”. Sent as-is."
                  className="w-72"
                  selectClassName={cn(inputCls, "w-full py-0")}
                  inputClassName={cn(inputCls, "w-full font-mono text-[13px]")}
                />
              </Field>
            </>
          )}

          {/* Effort — every LLM engine. Two steps, two knobs: extraction is
              hundreds of checkable calls (low); naming + notes are what the
              user reads (medium). */}
          {d.ai_mode !== "local" && (
            <>
              <Field
                label="Chunk analysis effort"
                hint="How hard the model thinks on each extraction call. Low is the big saver: at the provider default the model reasons at length on every one of hundreds of calls, and on a Claude subscription that is what burns the session limit. Extraction output is structured and checked, so Low rarely costs quality."
              >
                <Segmented<EffortLevel>
                  value={d.extract_effort ?? ""}
                  onValueChange={(v) => save({ ...d, extract_effort: v })}
                  options={EFFORT_OPTIONS}
                  ariaLabel="Chunk analysis effort"
                />
              </Field>
              <Field
                label="Naming & notes effort"
                hint="Effort for region/topic names and the compiled notes you read on the map. Medium keeps them sharp without the cost of High. Changing effort never invalidates caches — only new work is affected."
              >
                <Segmented<EffortLevel>
                  value={d.name_effort ?? ""}
                  onValueChange={(v) => save({ ...d, name_effort: v })}
                  options={EFFORT_OPTIONS}
                  ariaLabel="Naming and notes effort"
                />
              </Field>
              <RecommendedConfigNote mode={d.ai_mode} />
            </>
          )}

          {/* OpenAI model — openai only */}
          {d.ai_mode === "openai" && (
            <Field label="OpenAI model" hint="The chat model used for extraction + naming. Compiles make many calls — a cheaper model like Luna keeps the bill down.">
              <ModelSelect
                value={d.openai_model}
                options={OPENAI_MODELS}
                onChange={(v) => save({ ...d, openai_model: v })}
                commitCustomOnBlur
                customPlaceholder="e.g. gpt-5.6-terra"
                customHint="Any OpenAI chat model id. Sent as-is."
                className="w-72"
                selectClassName={cn(inputCls, "w-full py-0")}
                inputClassName={cn(inputCls, "w-full font-mono text-[13px]")}
              />
            </Field>
          )}

          {/* Embedding model — confirm before change (recompile required) */}
          <Field
            label="Embedding model"
            hint="Drives clustering / region structure. The OpenAI models need OPENAI_API_KEY and are multilingual. On-device (bge-small, 384-d) runs on this computer with no key — English only, and regions group a little more coarsely."
          >
            <div className="flex flex-col gap-2">
              <Segmented<EmbeddingModel>
                value={d.embedding_model}
                onValueChange={(v) => {
                  if (v !== d.embedding_model) setPendingEmbedding(v);
                }}
                options={EMBEDDING_OPTIONS}
                ariaLabel="Embedding model"
              />
              <LocalModelStatus selected={d.embedding_model === LOCAL_EMBEDDING_MODEL} />
            </div>
          </Field>

          {/* Parallel LLM calls */}
          <Field label="Parallel LLM calls" hint="Max concurrent calls during extraction (1–32). Higher is faster but adds rate-limit pressure.">
            <input
              type="number"
              min={CONC_MIN}
              max={CONC_MAX}
              step={1}
              defaultValue={d.llm_concurrency}
              onBlur={(e) => {
                const n = Number(e.target.value);
                if (Number.isInteger(n) && n >= CONC_MIN && n <= CONC_MAX && n !== d.llm_concurrency) {
                  save({ ...d, llm_concurrency: n });
                } else {
                  e.target.value = String(d.llm_concurrency); // revert invalid
                }
              }}
              className={cn(inputCls, "w-20")}
            />
          </Field>

          {/* Auto-compile after harvest */}
          <Field
            label="Compile automatically after harvest"
            hint="When on, a harvest that finds new or updated pages kicks off a compile right away — your map stays fresh without a click. When off, you get a 'Compile now?' nudge instead."
          >
            <Segmented<"on" | "off">
              value={d.auto_compile_after_harvest ? "on" : "off"}
              onValueChange={(v) => save({ ...d, auto_compile_after_harvest: v === "on" })}
              options={ONOFF}
              ariaLabel="Compile automatically after harvest"
            />
          </Field>

          {/* Claude call logging */}
          <Field label="Log Claude calls" hint="When on, each claude call logs model + timing + tokens to the server log. Handy to verify the Opus/Sonnet split.">
            <Segmented<"on" | "off">
              value={d.claude_call_logging ? "on" : "off"}
              onValueChange={(v) => save({ ...d, claude_call_logging: v === "on" })}
              options={ONOFF}
              ariaLabel="Claude call logging"
            />
          </Field>

          <p className="font-sans text-xs text-muted">
            {update.isPending ? "Saving…" : "Saved automatically as you change each field."}
          </p>
        </div>
      </SettingsSection>

      <AlertDialog
        open={pendingEmbedding !== null}
        onOpenChange={(open) => {
          if (!open) setPendingEmbedding(null); // cancel → Segmented stays on saved value
        }}
        title="Change the embedding model?"
        description={
          pendingEmbedding === LOCAL_EMBEDDING_MODEL
            ? "The on-device model runs on this computer with no API key. It is English-only and groups notes a little more coarsely than OpenAI's models; the ~67 MB model downloads once into your Mnemify data folder. The change takes effect after a fresh recompile (Compile → Recompile from scratch)."
            : "This changes how notes cluster into regions. It only takes effect after a fresh recompile (Compile → Recompile from scratch) — the embedding cache and the Ask search index both key on the model + dimensions. Until you recompile, search and the existing map keep using the old model."
        }
        confirmLabel={pendingEmbedding === LOCAL_EMBEDDING_MODEL ? "Download & save" : "Change & save"}
        cancelLabel="Cancel"
        confirming={update.isPending}
        onConfirm={() => {
          if (pendingEmbedding) {
            save({ ...d, embedding_model: pendingEmbedding });
            if (pendingEmbedding === LOCAL_EMBEDDING_MODEL) {
              // Fetch the model now so the next compile doesn't stall on it.
              prepareLocalEmbeddings().catch((err) =>
                toast.error("Couldn't start the model download", { description: String(err) }),
              );
            }
          }
          setPendingEmbedding(null);
        }}
      />
    </div>
  );
}

/** Download state of the on-device embedding model. Polls while downloading;
 *  quiet (one line) otherwise so the field doesn't shout when OpenAI is used. */
function LocalModelStatus({ selected }: { selected: boolean }) {
  const { data } = useLocalEmbeddings();
  if (!data) return null;
  const tone =
    data.status === "ready" ? "success" : data.status === "failed" ? "danger" : "neutral";
  const label =
    data.status === "ready"
      ? "On-device model downloaded"
      : data.status === "downloading"
        ? "Downloading on-device model…"
        : data.status === "failed"
          ? "On-device model download failed"
          : "On-device model not downloaded";
  if (!selected && data.status !== "downloading") return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Pill tone={tone} dot>
        {label}
      </Pill>
      {data.status === "failed" && data.error && (
        <span className="font-sans text-xs text-danger">{data.error}</span>
      )}
      {(data.status === "idle" || data.status === "failed") && (
        <button
          type="button"
          onClick={() =>
            prepareLocalEmbeddings().catch((err) =>
              toast.error("Couldn't start the model download", { description: String(err) }),
            )
          }
          className="font-sans text-xs text-magenta hover:underline"
        >
          {data.status === "failed" ? "Retry download" : `Download (${data.size_mb} MB)`}
        </button>
      )}
    </div>
  );
}

/** The fastest / cheapest configuration that still produces a good map, so a
 *  user hitting a subscription limit or a big bill knows what to change first.
 *  Kept in one place; the compile report's per-stage token usage is where the
 *  effect is verified. */
function RecommendedConfigNote({ mode }: { mode: AiMode }) {
  const isClaude = mode === "claude" || mode === "anthropic";
  return (
    <div className="rounded-lg border border-hair bg-bone/40 px-4 py-3 max-w-prose">
      <p className="font-sans text-sm text-ink mb-1.5">Recommended to save time &amp; cost</p>
      <ul className="font-sans text-xs text-muted space-y-1 list-disc pl-4">
        <li>
          <strong className="text-ink font-medium">Chunk analysis:</strong>{" "}
          {isClaude ? "Haiku" : "a small / mini model"} at <strong className="text-ink font-medium">Low</strong> effort.
          This step is ~90% of every compile’s tokens and its output is checked against a schema, so the
          cheapest tier is usually enough.
        </li>
        <li>
          <strong className="text-ink font-medium">Naming &amp; notes:</strong>{" "}
          {isClaude ? "Sonnet or Opus" : "your main model"} at <strong className="text-ink font-medium">Medium</strong>.
          This is the text you actually read; it is a small share of the calls.
        </li>
        {mode === "claude" && (
          <li>
            On a Claude subscription, a compile that stops on the usage limit is resumable: everything already
            analyzed is saved, and <em>Resume compile</em> on the Compile page only spends what is left.
          </li>
        )}
        <li>
          After a compile, the report shows tokens per stage — compare two runs before settling on a
          configuration. Only unchanged documents are cached; changing models or effort never re-analyzes
          what is already done.
        </li>
      </ul>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  // items-start so an inline-flex Segmented pill hugs its options instead of
  // being stretched to full width by the column's default align-items: stretch.
  return (
    <div className="flex flex-col items-start gap-1.5">
      <span className="font-sans text-sm text-ink">{label}</span>
      {children}
      {hint && <span className="font-sans text-xs text-muted max-w-prose">{hint}</span>}
    </div>
  );
}
