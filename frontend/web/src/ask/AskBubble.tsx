// The "ask your map" bubble — the app's one *visible* launcher for the Ask
// dock, mounted by DashboardLayout so it follows you across every route (⌘J
// and the command palette are the keyboard ways in). Carries the old
// OracleOrb's glass pill: compass-rose glyph, magenta beam aura, persistent
// label.
// Launcher only — the conversation lives in <AskDock>; clicking just opens it.

import { useAskDockStore } from "./askDockStore";
import { AskGlyph } from "./AskDock";

export function AskBubble() {
  const open = useAskDockStore((s) => s.open);
  // Nothing to launch while the dock is showing.
  if (open) return null;

  return (
    // Below `md` the dock itself is display:none, so a launcher there would
    // toggle invisible state — hide it at the same breakpoint.
    <div className="hidden md:block">
      <button
        type="button"
        onClick={() => useAskDockStore.getState().openDock()}
        aria-label="Ask your map anything"
        aria-keyshortcuts="Meta+J Control+J"
        className="group relative inline-flex h-12 items-center gap-2 rounded-full glass-panel pl-1.5 pr-1.5 sm:pr-4 shadow-lg transition-transform duration-200 hover:scale-[1.03] active:scale-95"
        style={{
          boxShadow:
            "0 8px 24px rgb(0 0 0 / 0.30), inset 0 1px 0 rgb(255 255 255 / 0.2)",
        }}
      >
        <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full">
          {/* Soft beam glow aura */}
          <span
            aria-hidden
            className="absolute inset-0 rounded-full animate-pulse motion-reduce:animate-none"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, rgb(var(--c-magenta) / 0.34), transparent 68%)",
              filter: "blur(6px)",
            }}
          />
          <AskGlyph size={20} />
        </span>
        <span className="hidden sm:inline whitespace-nowrap pr-0.5 font-sans text-sm text-ink">
          Ask your map
        </span>
      </button>
    </div>
  );
}
