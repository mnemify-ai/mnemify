import { useEffect, type CSSProperties, type ReactNode } from "react";
import { Drawer as Vaul } from "vaul";
import { X } from "lucide-react";
import {
  dockInsetCss,
  dockOverlayInset,
  useAskDockStore,
} from "../../../ask/askDockStore";
import { cn } from "../../lib/cn";

interface SideDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  className?: string;
  /** Width breakpoint for the drawer body. Default 420px. */
  width?: string;
  /**
   * Stop short of the Ask dock instead of covering it (desktop only — below
   * `md` the dock is `display:none`, so the drawer keeps the full width).
   *
   * Opt-in, because it's only right for drawers that show *content the
   * conversation is talking about* — a cited source, a change list you might
   * ask about. A drawer that replaces the page's own controls (the mobile
   * filter sheets) has no such relationship and stays flush right.
   */
  avoidAskDock?: boolean;
}

/**
 * Right-sliding drawer. Used for TagProvenanceDrawer, DocDrawer, the mobile
 * filter/sources sheets and the citation source inspector — every transient
 * panel in the app arrives from the same edge.
 *
 * Vaul ships with bottom-sheet defaults, which is why `direction="right"` is
 * passed explicitly below: it's what makes this a side panel (with the same
 * gesture + escape handling) rather than a sheet.
 */
export function SideDrawer({
  open,
  onOpenChange,
  children,
  className,
  width = "420px",
  avoidAskDock = false,
}: SideDrawerProps) {
  // Selecting a constant 0 for the common case is deliberate: every drawer in
  // the app renders this component, and without the guard all of them would
  // re-render on every dock open/close/resize-release.
  const dockInset = useAskDockStore((s) =>
    avoidAskDock ? dockOverlayInset(s) : 0,
  );

  // A maximized dock owns the whole shell row, so there is nowhere beside it
  // to be. Claim a slot for as long as this drawer is open: the dock restores
  // its docked width on the way in and refuses to re-maximize until we let go.
  useEffect(() => {
    if (!avoidAskDock || !open) return;
    const { openOverlay, closeOverlay } = useAskDockStore.getState();
    openOverlay();
    return closeOverlay;
  }, [avoidAskDock, open]);

  const reduceMotion =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  return (
    <Vaul.Root
      open={open}
      onOpenChange={onOpenChange}
      direction="right"
      modal={false}
    >
      <Vaul.Portal>
        {/* `pointer-events-none` keeps the dim visible but lets clicks
            fall through to the KnowledgeMap canvas behind it. Without this,
            opening a tag drawer freezes hex interaction even though
            `modal={false}` says the page should stay interactive. */}
        <Vaul.Overlay className="fixed inset-0 bg-ink/12 motion-reduce:animate-none pointer-events-none" />
        <Vaul.Content
          aria-describedby={undefined}
          // Vaul applies its own slide-in / slide-out keyframes via
          // `[data-state=open|closed]` on the `[data-vaul-drawer]` element
          // (slideFromRight / slideToRight). That means our enter is already
          // gated by `data-state="open"` and an exit animation runs on close
          // — no need to reapply `animate-slide-in-*` here (it would double-
          // animate on open). We only need to honor reduced-motion: setting
          // `data-vaul-animate="false"` disables Vaul's built-in keyframes,
          // and `motion-reduce:animate-none` belt-and-suspenders the case
          // where any classname-driven keyframe sneaks in.
          data-vaul-animate={reduceMotion ? "false" : undefined}
          className={cn(
            "fixed top-0 bottom-0 right-0 z-40 flex flex-col bg-cream shadow-xl outline-none",
            avoidAskDock && [
              "md:right-[var(--ask-dock-inset)]",
              // The inset eats into the available width, so cap it rather
              // than letting a 480px drawer run off the left edge on a
              // laptop with a wide dock.
              "md:max-w-[calc(100vw-var(--ask-dock-inset))]",
              // Vaul paints an overscroll mask —
              //   [data-vaul-drawer]:not([data-vaul-custom-container=true])::after
              //   { content:''; background: inherit }
              //   [data-vaul-drawer-direction=right]::after
              //   { left:100%; top:0; bottom:0; width:200% }
              // — i.e. two drawer-widths of `bg-cream` hanging off the right
              // edge. Harmless at `right: 0` (it's off-screen); the moment we
              // pull that edge inward it repaints the dock cream. Vaul only
              // suppresses it for a custom portal container, which we don't
              // use, so kill it here. `!` is load-bearing: the injected
              // selector is (0,2,1) and out-specifies a plain `after:` utility.
              "after:!content-none",
            ],
            "border-l border-hair motion-reduce:animate-none",
            className,
          )}
          style={
            avoidAskDock
              ? ({
                  width,
                  // Re-clamped to this viewport, exactly the way the dock
                  // clamps its own aside — see `dockInsetCss`.
                  "--ask-dock-inset": dockInsetCss(dockInset),
                  // Inline, not `transition-[right]`: Vaul's injected
                  // `[data-vaul-drawer]{transition:transform .5s …}` ties a
                  // Tailwind utility on specificity and wins on source order
                  // (its <style> is appended to <head> at module eval, after
                  // the bundle's stylesheet), so the class would silently do
                  // nothing. Vaul's transform transition is re-declared here
                  // because this shorthand replaces it, and drag snap-back
                  // needs it.
                  transition: reduceMotion
                    ? "none"
                    : "right 240ms cubic-bezier(0.22, 1, 0.36, 1), transform 500ms cubic-bezier(0.32, 0.72, 0, 1)",
                } as CSSProperties)
              : { width }
          }
        >
          <Vaul.Title className="sr-only">Tag detail</Vaul.Title>
          <button
            type="button"
            aria-label="Close panel"
            onClick={() => onOpenChange(false)}
            className="absolute top-3 right-3 p-3 rounded-full text-muted hover:text-ink hover:bg-bone/80 transition-colors before:content-[''] before:absolute before:inset-[-4px]"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
          {children}
        </Vaul.Content>
      </Vaul.Portal>
    </Vaul.Root>
  );
}
