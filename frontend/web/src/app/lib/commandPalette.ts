// Shared open-state for the global ⌘K command palette. Lifting it out of
// CommandPalette's local useState lets any surface (e.g. the TopBar search
// trigger) open the palette without prop-drilling or synthetic key events.
import { create } from "zustand";

interface CommandPaletteState {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const useCommandPalette = create<CommandPaletteState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set((s) => ({ open: !s.open })),
}));
