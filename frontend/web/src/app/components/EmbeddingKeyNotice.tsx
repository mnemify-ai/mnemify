import { Link } from "react-router-dom";
import { Cpu, KeyRound } from "lucide-react";
import { findSecret, useSecrets } from "../api/secrets";
import { LOCAL_EMBEDDING_MODEL, useLocalEmbeddings } from "../api/embeddings";
import { useCompileSettings } from "../api/compileSettings";
import type { AiMode } from "../api/terrain";
import { cn } from "../lib/cn";

/**
 * Inline warning under an engine picker: what the embedding step will do for
 * the chosen engine given the keys on this machine. Shown at the moment of
 * choosing, so the consent dialog at compile time is never the first time the
 * user hears that embeddings may run on-device.
 *
 *  - Claude engine, no OpenAI key → embeddings run on this computer (English
 *    only, coarser regions); the model download is asked for once.
 *  - Claude engine, OpenAI key set, OpenAI embeddings → an informational
 *    line: the key is used for embeddings by default; Claude only names.
 *  - OpenAI engine, no OpenAI key → the engine can't run; add a key or pick
 *    Claude.
 *  - Otherwise renders nothing.
 */
export function EmbeddingKeyNotice({ aiMode, className }: { aiMode: AiMode; className?: string }) {
  const secrets = useSecrets();
  const settings = useCompileSettings();
  const local = useLocalEmbeddings();
  if (!secrets.data || !settings.data) return null;

  const openaiKey = findSecret(secrets.data, "OPENAI_API_KEY")?.set === true;
  const localDefault = settings.data.embedding_model === LOCAL_EMBEDDING_MODEL;
  const downloaded = local.data?.downloaded === true;
  const sizeMb = local.data?.size_mb ?? 67;

  let body: React.ReactNode = null;
  let tone: "warning" | "info" = "warning";
  if (aiMode === "openai" && !openaiKey) {
    body = (
      <>
        <KeyRound size={14} strokeWidth={1.5} className="mt-0.5 shrink-0" aria-hidden />
        <span>
          <span className="text-ink">No OpenAI key is set</span>, so this engine can't run.{" "}
          <SettingsLink>Add one in Settings</SettingsLink>, or pick a Claude engine — embeddings
          then run on this computer.
        </span>
      </>
    );
  } else if ((aiMode === "claude" || aiMode === "anthropic") && (!openaiKey || localDefault)) {
    body = (
      <>
        <Cpu size={14} strokeWidth={1.5} className="mt-0.5 shrink-0" aria-hidden />
        <span>
          {openaiKey ? (
            <span className="text-ink">Embeddings run on this computer</span>
          ) : (
            <>
              <span className="text-ink">No OpenAI key is set, so embeddings will run on this computer</span>{" "}
              instead of OpenAI
            </>
          )}
          {" "}— the on-device model is English-only and groups notes a little more coarsely.
          {downloaded
            ? " The model is already downloaded."
            : ` You'll be asked once before the ${sizeMb} MB model downloads.`}
          {!openaiKey && (
            <>
              {" "}For OpenAI embeddings (multilingual, best quality),{" "}
              <SettingsLink>add an OpenAI key in Settings</SettingsLink>.
            </>
          )}
        </span>
      </>
    );
  } else if ((aiMode === "claude" || aiMode === "anthropic") && openaiKey && !localDefault) {
    tone = "info";
    body = (
      <>
        <KeyRound size={14} strokeWidth={1.5} className="mt-0.5 shrink-0" aria-hidden />
        <span>
          <span className="text-ink">Your OpenAI key is used for embeddings</span> (
          {settings.data.embedding_model}); Claude does the naming and notes. To keep the whole
          compile off OpenAI, set <SettingsLink>Embedding model to On-device in Settings</SettingsLink>.
        </span>
      </>
    );
  }
  if (!body) return null;
  return (
    <p
      role="note"
      className={cn(
        "mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 font-sans text-xs text-muted leading-relaxed",
        tone === "warning" ? "border-warning/30 bg-warning/10" : "border-hair bg-bone/40",
        className,
      )}
    >
      {body}
    </p>
  );
}

function SettingsLink({ children }: { children: React.ReactNode }) {
  return (
    <Link to="/settings/ai" className="text-magenta hover:underline">
      {children}
    </Link>
  );
}
