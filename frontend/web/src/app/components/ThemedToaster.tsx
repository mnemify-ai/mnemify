import { Toaster } from "sonner";

import { useTheme } from "../../knowledgeMap/util/useTheme";

/*
  Toaster: 4s auto-dismiss is the calm middle of the 3-5s window.
  Sonner manages aria internally — non-error toasts use aria-live="polite"
  by default and the toaster element exposes role="region". Sonner's
  `ToastOptions` does not currently expose an `ariaProps` field
  (see node_modules/sonner/dist/index.d.ts), so we rely on its built-in
  polite-by-default behavior. `containerAriaLabel` gives the region a
  descriptive name for SR users.

  Theme comes from the passive `<html>.dark` observer rather than
  `useThemeMode` — that hook owns the writer/persistence, and a second
  instance here would not track Settings-page toggles.
*/
export function ThemedToaster() {
  const theme = useTheme();

  return (
    <Toaster
      position="bottom-right"
      theme={theme}
      closeButton
      duration={4000}
      // Always show every toast in full instead of Sonner's default
      // stacked-behind-the-front behavior — without `expand`, back-to-back
      // notifications collapse into a pile and only the top one is
      // legible until the user hovers. `gap` adds breathing room between
      // them so the close-button hit targets don't overlap.
      expand
      gap={12}
      visibleToasts={5}
      containerAriaLabel="Notifications"
      toastOptions={{
        // On-brand styling: cream surface, hair border, serif title,
        // magenta accent for success icons. Avoid Sonner's stock
        // richColors (green/red) which read as off-brand. All classes are
        // CSS-var-backed tokens, so they follow `.dark` on their own.
        classNames: {
          toast:
            "!bg-cream !border !border-hair !text-ink !rounded-xl !shadow-sm",
          title: "!font-serif !text-[15px] !text-ink",
          description: "!font-sans !text-xs !text-muted",
          actionButton: "!bg-magenta !text-cream",
          cancelButton: "!bg-bone !text-ink",
          closeButton: "!bg-bone !text-muted !border-hair",
          success: "!text-magenta",
          error: "!text-rose",
        },
      }}
    />
  );
}
