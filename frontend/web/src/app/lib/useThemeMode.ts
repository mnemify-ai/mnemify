import { useEffect, useState } from "react";

export type ThemeMode = "light" | "dark";

const STORAGE_KEY = "mnemify:theme";

function readStored(): ThemeMode | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function readApplied(): ThemeMode {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Write + apply a theme. index.html applies the stored value at boot. */
export function setThemeMode(mode: ThemeMode) {
  document.documentElement.classList.toggle("dark", mode === "dark");
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

/**
 * Theme state synced across every consumer (TopBar toggle, Settings picker):
 * writes go through `setThemeMode`, reads observe `<html>`'s class list, so
 * two mounted instances can never disagree.
 */
export function useThemeMode(): [ThemeMode, (next: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(() => readStored() ?? readApplied());

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => {
      const next = readApplied();
      setMode((prev) => (prev === next ? prev : next));
    };
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    sync();
    return () => observer.disconnect();
  }, []);

  return [mode, setThemeMode];
}
