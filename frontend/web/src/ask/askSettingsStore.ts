import { create } from "zustand";
import { persist } from "zustand/middleware";
import { DEFAULT_SETTINGS, type AskSettings } from "./types";
import { normalizeModel } from "./models";

/**
 * Ask engine/model/key settings as a shared store, so the composer's
 * quick-switch pill and Settings → AI & Models edit the same state and stay
 * in sync while both are mounted.
 *
 * Persisted at a v2 key (zustand's envelope format). The v1 key held raw
 * AskSettings JSON written by the old useAskSession — migrated once below.
 */

const V1_KEY = "mnemify.ask.settings.v1";

function migrateFromV1(): AskSettings | null {
  try {
    const raw = localStorage.getItem(V1_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) || {};
    // "anthropic" was a separate provider before the Claude/BYOK merge; it is
    // now the Claude engine with a key set (wireProvider re-derives it).
    if (parsed.provider === "anthropic") parsed.provider = "claude";
    if (parsed.provider !== "claude" && parsed.provider !== "openai") {
      delete parsed.provider;
    }
    return normalizeSettings({ ...DEFAULT_SETTINGS, ...parsed });
  } catch {
    return null;
  }
}

/** The UI used to store short aliases ("sonnet"); the dropdown now works in
 *  full model ids, so map saved aliases forward once on load. */
function normalizeSettings(s: AskSettings): AskSettings {
  const model = normalizeModel(s.provider, s.model);
  return model === s.model ? s : { ...s, model };
}

type AskSettingsState = {
  settings: AskSettings;
  setSettings: (next: AskSettings) => void;
};

export const useAskSettingsStore = create<AskSettingsState>()(
  persist(
    (set) => ({
      // Seed from v1 when no v2 state exists yet; a present v2 key rehydrates
      // over this initial value.
      settings:
        (typeof localStorage !== "undefined" ? migrateFromV1() : null) ??
        DEFAULT_SETTINGS,
      setSettings: (settings) => set({ settings }),
    }),
    {
      name: "mnemify.ask.settings.v2",
      merge: (persisted, current) => {
        const p = persisted as Partial<AskSettingsState> | undefined;
        return p?.settings
          ? {
              ...current,
              settings: normalizeSettings({ ...DEFAULT_SETTINGS, ...p.settings }),
            }
          : current;
      },
    },
  ),
);
