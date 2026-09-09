import { useAskStream } from "./useAskStream";
import { useAskSettingsStore } from "./askSettingsStore";
import { useAskThreadStore } from "./askThreadStore";

/**
 * The Ask conversation's session state, lifted out of `AskPanel` so a single
 * owner (`AskDock`) can pass it into the panel. Settings live in the shared
 * `askSettingsStore` (also edited from Settings → AI & Models); messages and
 * the draft live in the persisted thread store — all of it survives
 * unmounts, navigation, and reloads.
 */
export function useAskSession() {
  const settings = useAskSettingsStore((s) => s.settings);
  const setSettings = useAskSettingsStore((s) => s.setSettings);
  const draft = useAskThreadStore((s) => s.draft);
  const setDraft = useAskThreadStore((s) => s.setDraft);

  const stream = useAskStream(settings);

  return { settings, setSettings, draft, setDraft, ...stream };
}

export type AskSession = ReturnType<typeof useAskSession>;
