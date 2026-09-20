import { useState } from "react";
import { toast } from "sonner";
import { AskSettingsForm } from "../../../ask/AskSettingsForm";
import { Button } from "../../components/ui/Button";
import { Pill } from "../../components/ui/Pill";
import {
  describeSecretStatus,
  findSecret,
  useDeleteSecret,
  useSaveSecret,
  useSecrets,
  useTestSecret,
  type SecretRow,
  type TestSecretResult,
} from "../../api/secrets";
import { cn } from "../../lib/cn";
import { CompileSettingsSection } from "./CompileSettingsSection";
import { SettingsSection } from "./SettingsSection";

/**
 * AI & Models — the single home for every model decision:
 * the server's API keys, the Ask chat engine/model/keys, and the compile
 * engine/models. (Chat settings used to hide inside the chat panel's
 * collapsible footer; compile settings had their own tab; the keys had no UI
 * at all and had to be written into `.env` by hand.)
 */
export function AiModelsSection() {
  return (
    <div className="max-w-3xl space-y-12">
      <ApiKeysSection />

      <SettingsSection
        eyebrow="Ask"
        title="Chat engine & keys"
        help={
          <>
            The engine and model the Ask dock uses to answer questions over
            your compiled map. A key entered here is stored in this browser
            only and overrides the server key above. The composer's model pill
            is a quick-switch for the same settings.
          </>
        }
      >
        <AskSettingsForm />
      </SettingsSection>

      <CompileSettingsSection />
    </div>
  );
}

/** The two keys the server itself uses. Connector tokens are on the allowlist
 *  too, but they already have wizards under Build → Sources, so showing them
 *  a second time here would give the same secret two owners. */
const SERVER_KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"] as const;

const KEY_COPY: Record<(typeof SERVER_KEYS)[number], { blurb: string; where: string }> = {
  OPENAI_API_KEY: {
    blurb:
      "Needed by the OpenAI compile engine and chat engine, and for OpenAI embeddings (multilingual, the best map quality). Without it, the Claude engines can compile with the on-device embedding model instead — English only; pick it under Embedding model below.",
    where: "platform.openai.com/api-keys",
  },
  ANTHROPIC_API_KEY: {
    blurb:
      "Needed for the Claude API compile mode, and for chatting with Claude when this machine has no logged-in claude CLI.",
    where: "console.anthropic.com/settings/keys",
  },
};

function ApiKeysSection() {
  const { data, isLoading, isError } = useSecrets();
  return (
    <SettingsSection
      eyebrow="Keys"
      title="API keys"
      help={
        <>
          Stored on this machine in <code>.env</code> under your Mnemify home,
          readable only by you (mode 0600). They are sent to OpenAI and
          Anthropic and nowhere else, and are never shown back to you — only a
          masked hint of the last four characters.
        </>
      }
    >
      {isLoading ? (
        <span className="font-sans text-sm text-muted">Loading…</span>
      ) : isError ? (
        // Don't render Save/Test buttons that would fail on submit: without
        // the rows we cannot tell "not set" from "unreachable", and offering
        // the controls anyway would look like the keys were simply missing.
        <p className="font-sans text-sm text-muted max-w-prose">
          Couldn't load the key settings from the server. Reload the page; if
          it keeps failing, the server may be running an older build without{" "}
          <code>/api/secrets</code>. You can still set{" "}
          <code>OPENAI_API_KEY</code> and <code>ANTHROPIC_API_KEY</code> in{" "}
          <code>.env</code> under your Mnemify home.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {SERVER_KEYS.map((name) => (
            <KeyRow key={name} row={findSecret(data, name)} name={name} />
          ))}
        </div>
      )}
    </SettingsSection>
  );
}

const inputCls =
  "h-8 px-2 rounded-md border bg-bone/50 font-sans text-sm text-ink focus:outline-none transition-colors border-hair focus:border-ink/40";

function KeyRow({ row, name }: { row: SecretRow | undefined; name: keyof typeof KEY_COPY }) {
  const [value, setValue] = useState("");
  const [result, setResult] = useState<TestSecretResult | null>(null);
  const save = useSaveSecret();
  const remove = useDeleteSecret();
  const test = useTestSecret();

  const copy = KEY_COPY[name];
  const label = row?.label ?? name;
  const isSet = row?.set === true;
  const typed = value.trim();

  function onSave() {
    save.mutate(
      { name, value: typed },
      {
        onSuccess: () => {
          setValue("");
          setResult(null);
          toast.success(`${label} saved.`);
        },
        onError: (err) => toast.error("Couldn't save", { description: String(err) }),
      },
    );
  }

  function onTest() {
    // Check what the user just typed if there is anything; otherwise the
    // stored key. Either way the value is not saved by testing.
    setResult(null);
    test.mutate(
      { name, value: typed || undefined },
      {
        onSuccess: setResult,
        onError: (err) => setResult({ ok: false, reason: String(err) }),
      },
    );
  }

  function onRemove() {
    remove.mutate(name, {
      onSuccess: () => {
        setValue("");
        setResult(null);
        toast.success(`${label} removed.`);
      },
      onError: (err) => toast.error("Couldn't remove", { description: String(err) }),
    });
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-hair bg-bone/40 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="font-sans text-sm text-ink">{label}</span>
        <Pill tone={isSet ? "success" : "neutral"} dot>
          {describeSecretStatus(row)}
        </Pill>
      </div>

      <p className="font-sans text-xs text-muted max-w-prose">
        {copy.blurb} Get one at <span className="text-ink">{copy.where}</span>.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setResult(null);
          }}
          placeholder={isSet ? "Replace with a new key" : "sk-…"}
          autoComplete="off"
          aria-label={label}
          className={cn(inputCls, "w-64 font-mono text-[13px]")}
        />
        <Button size="sm" onClick={onSave} disabled={!typed} loading={save.isPending}>
          Save
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={onTest}
          // Nothing to check when the field is empty and no key is stored.
          disabled={!typed && !isSet}
          loading={test.isPending}
        >
          Test
        </Button>
        {isSet && (
          <Button size="sm" variant="ghost" onClick={onRemove} loading={remove.isPending}>
            Remove
          </Button>
        )}
      </div>

      {result && (
        <p
          className={cn(
            "font-sans text-xs",
            result.ok ? "text-success" : "text-danger",
          )}
        >
          {result.ok
            ? typed
              ? "This key works."
              : "The saved key works."
            : result.reason}
        </p>
      )}
    </div>
  );
}
