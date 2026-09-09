import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import * as RadixPopover from "@radix-ui/react-popover";
import { Check, ChevronDown } from "lucide-react";
import { Tooltip } from "../../../ui/Tooltip";
import { cn } from "../../../../lib/cn";
import type { ZoomMode } from "./state";

interface ZoomMenuProps {
  zoom: number;
  zoomMode: ZoomMode;
  /** Sets an explicit zoom value (flips zoomMode to "custom"). */
  onZoomChange: (value: number) => void;
  /** Sets the zoom mode; the orchestrator's effect derives the value from
   *  container + natural dimensions. */
  onZoomModeChange: (mode: ZoomMode) => void;
}

const PERCENT_PRESETS = [50, 75, 100, 125, 150, 200, 300];

const MIN_PERCENT = 25;
const MAX_PERCENT = 500;

export function ZoomMenu({
  zoom,
  zoomMode,
  onZoomChange,
  onZoomModeChange,
}: ZoomMenuProps) {
  const [open, setOpen] = useState(false);
  const pct = Math.round(zoom * 100);

  // Local draft for the editable input. Keeps in sync with the external pct
  // unless the user is mid-edit (focused). On commit (Enter/blur) we clamp +
  // call onZoomChange.
  const [draft, setDraft] = useState<string>(String(pct));
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setDraft(String(pct));
    }
  }, [pct]);

  function commit() {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(pct));
      return;
    }
    const clamped = Math.max(MIN_PERCENT, Math.min(MAX_PERCENT, parsed));
    onZoomChange(clamped / 100);
    setDraft(String(clamped));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    inputRef.current?.blur();
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setDraft(String(pct));
      inputRef.current?.blur();
    }
  }

  function pickMode(mode: ZoomMode) {
    onZoomModeChange(mode);
    setOpen(false);
  }

  function pickPercent(p: number) {
    onZoomChange(p / 100);
    setOpen(false);
  }

  return (
    <RadixPopover.Root open={open} onOpenChange={setOpen}>
      <RadixPopover.Anchor asChild>
        <form
          onSubmit={handleSubmit}
          className={cn(
            "inline-flex items-center h-9 rounded-full",
            "hover:bg-bone/60 focus-within:bg-bone/60 transition-colors",
            "pl-2 pr-0.5",
          )}
        >
          <Tooltip content="Zoom (type a percent)" side="bottom">
            <input
              ref={inputRef}
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={draft}
              onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
              onFocus={(e) => e.target.select()}
              onBlur={commit}
              onKeyDown={handleKey}
              aria-label="Zoom percent"
              className={cn(
                "w-[3.5ch] bg-transparent border-0 outline-none",
                "font-mono tabular-nums text-[12px] text-ink text-right",
                "focus:outline-none",
              )}
            />
          </Tooltip>
          <span
            className="font-mono tabular-nums text-[12px] text-muted select-none"
            aria-hidden
          >
            %
          </span>
          <RadixPopover.Trigger asChild>
            <button
              type="button"
              aria-label="Zoom presets"
              aria-haspopup="menu"
              aria-expanded={open}
              className={cn(
                "inline-flex items-center justify-center h-7 w-7 ml-0.5 rounded-full",
                "text-muted hover:text-ink hover:bg-bone transition-colors",
              )}
            >
              <ChevronDown size={13} strokeWidth={1.75} aria-hidden />
            </button>
          </RadixPopover.Trigger>
        </form>
      </RadixPopover.Anchor>

      <RadixPopover.Portal>
        <RadixPopover.Content
          side="bottom"
          align="end"
          sideOffset={6}
          className={cn(
            "z-50 outline-none min-w-[180px]",
            "bg-cream border border-hair rounded-xl shadow-lg",
            "p-2 font-sans text-sm text-ink",
            "data-[state=open]:animate-fade-in",
            "motion-reduce:animate-none",
          )}
        >
          <ul role="menu" className="flex flex-col gap-0.5">
            <ModeItem
              label="Fit width"
              active={zoomMode === "fitWidth"}
              onSelect={() => pickMode("fitWidth")}
            />
            <ModeItem
              label="Fit page"
              active={zoomMode === "fitPage"}
              onSelect={() => pickMode("fitPage")}
            />
            <ModeItem
              label="Actual size"
              active={zoomMode === "actual"}
              onSelect={() => pickMode("actual")}
            />
            <li className="my-1 border-t border-hair" />
            {PERCENT_PRESETS.map((p) => (
              <PercentItem
                key={p}
                percent={p}
                active={zoomMode === "custom" && pct === p}
                onSelect={() => pickPercent(p)}
              />
            ))}
          </ul>
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}

function ModeItem({
  label,
  active,
  onSelect,
}: {
  label: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        role="menuitemradio"
        aria-checked={active}
        onClick={onSelect}
        className={cn(
          "w-full flex items-center justify-between gap-3 px-2 py-1.5 rounded-md",
          "text-left font-sans text-sm text-ink",
          "hover:bg-bone/70 transition-colors",
        )}
      >
        <span>{label}</span>
        {active && (
          <Check size={13} strokeWidth={2} className="text-magenta" aria-hidden />
        )}
      </button>
    </li>
  );
}

function PercentItem({
  percent,
  active,
  onSelect,
}: {
  percent: number;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        role="menuitemradio"
        aria-checked={active}
        onClick={onSelect}
        className={cn(
          "w-full flex items-center justify-between gap-3 px-2 py-1.5 rounded-md",
          "text-left font-mono tabular-nums text-[13px] text-ink",
          "hover:bg-bone/70 transition-colors",
        )}
      >
        <span>{percent}%</span>
        {active && (
          <Check size={13} strokeWidth={2} className="text-magenta" aria-hidden />
        )}
      </button>
    </li>
  );
}
