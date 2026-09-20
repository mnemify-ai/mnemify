import { Link, useNavigate } from "react-router-dom";
import { Cpu, Languages, Sparkles } from "lucide-react";
import { Dialog, DialogClose } from "./ui/Dialog";
import { Button } from "./ui/Button";
import { useLocalEmbeddingsPrompt } from "../lib/localEmbeddingsPromptStore";

/**
 * Shown when a compile is refused for want of an `OPENAI_API_KEY` (Claude
 * engines use OpenAI only for embeddings). Explains the trade-off before
 * anything is downloaded, links straight to the key field in Settings, and
 * only on "Use the on-device model" does `startCompileWithConsent` fetch the
 * ~67 MB model and retry. Mounted once in DashboardLayout; every compile
 * button reaches it through `useStartCompile`.
 */
export function LocalEmbeddingsDialog() {
  const request = useLocalEmbeddingsPrompt((s) => s.request);
  const settle = useLocalEmbeddingsPrompt((s) => s.settle);
  const navigate = useNavigate();
  const open = request !== null;
  const info = request?.refusal.local_embeddings;
  const downloaded = info?.downloaded === true;
  const sizeMb = info?.size_mb ?? 67;
  // Keyless install still on the default OpenAI engine: offer the engine
  // switch in the same click. Otherwise the engine is already Claude.
  const switchTo = request?.refusal.suggested_ai_mode ?? null;
  const claudeName =
    switchTo === "claude"
      ? "your logged-in Claude Code"
      : switchTo === "anthropic"
        ? "your Anthropic API key"
        : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) settle(null);
      }}
      width="520px"
      ariaLabel="No OpenAI key configured"
    >
      <DialogClose onClose={() => settle(null)} />
      <div className="p-7 pr-12">
        <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted mb-2">
          Before compiling
        </p>
        <h2 className="font-serif text-xl text-ink mb-3">No OpenAI key is configured</h2>
        <p className="font-sans text-sm text-muted leading-relaxed">
          {claudeName ? (
            <>
              Mnemify can build your map with Claude instead, using {claudeName}. Claude writes
              the names and notes, but it can't produce embeddings — the vectors that decide how
              notes group into regions. Those normally come from OpenAI; without a key, a small
              embedding model can run on this computer instead.
            </>
          ) : (
            <>
              Claude writes the names and notes on your map, but it can't produce embeddings — the
              vectors that decide how notes group into regions. Mnemify normally gets those from
              OpenAI. Without a key, it can run a small embedding model on this computer instead.
            </>
          )}
        </p>

        <ul className="mt-4 flex flex-col gap-3">
          <li className="flex gap-3">
            <Cpu size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink" aria-hidden />
            <p className="font-sans text-sm text-muted leading-relaxed">
              <span className="text-ink">Runs on your PC.</span>{" "}
              {downloaded
                ? "The model is already downloaded, so nothing else is fetched."
                : `A one-time ${sizeMb} MB download, stored in your Mnemify data folder. Compiling takes a few minutes longer than with OpenAI.`}
            </p>
          </li>
          <li className="flex gap-3">
            <Sparkles size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink" aria-hidden />
            <p className="font-sans text-sm text-muted leading-relaxed">
              <span className="text-ink">The map will look different.</span> Regions form from a
              different embedding space, so grouping is a little coarser than with OpenAI's model.
              For the best results, add an OpenAI key.
            </p>
          </li>
          <li className="flex gap-3">
            <Languages size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink" aria-hidden />
            <p className="font-sans text-sm text-muted leading-relaxed">
              <span className="text-ink">English only.</span> The on-device model understands
              English. OpenAI's embeddings are multilingual — if your notes are in other
              languages, use a key.
            </p>
          </li>
        </ul>

        <p className="mt-4 font-sans text-xs text-muted">
          You can switch back any time under{" "}
          <Link
            to="/settings/ai"
            onClick={() => settle(null)}
            className="text-magenta hover:underline"
          >
            Settings → AI &amp; Models
          </Link>
          .
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" size="md" onClick={() => settle(null)}>
            Not now
          </Button>
          <Button
            variant="secondary"
            size="md"
            onClick={() => {
              settle(null);
              navigate("/settings/ai");
            }}
          >
            Add OpenAI key
          </Button>
          <Button variant="primary" size="md" onClick={() => settle("local")}>
            {switchTo
              ? downloaded
                ? "Use Claude + on-device model"
                : `Use Claude + download model (${sizeMb} MB)`
              : downloaded
                ? "Use the on-device model"
                : `Download & use (${sizeMb} MB)`}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
