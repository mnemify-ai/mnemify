// Toolbar Popover listing all hidden columns and rows for the active sheet.
// Used as the discovery + restoration UI when a user has hidden things and
// can't easily find them again (the 2px magenta strip in the header is a
// visual cue, but this menu is the catalog).

import { useState } from "react";
import { EyeOff } from "lucide-react";
import { Popover } from "../../../ui/Popover";
import { Tooltip } from "../../../ui/Tooltip";
import { cn } from "../../../../lib/cn";

interface HideMenuProps {
  hiddenCols: number[];
  hiddenRows: number[];
  onShowCol: (col: number) => void;
  onShowRow: (row: number) => void;
  onShowAll: () => void;
}

export function HideMenu({
  hiddenCols,
  hiddenRows,
  onShowCol,
  onShowRow,
  onShowAll,
}: HideMenuProps) {
  const [open, setOpen] = useState(false);
  const total = hiddenCols.length + hiddenRows.length;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="end"
      side="bottom"
      trigger={
        <Tooltip content="Hidden columns and rows" side="bottom">
          <button
            type="button"
            aria-label="Hidden items"
            className={cn(
              "relative inline-flex items-center justify-center h-9 w-9 rounded-full",
              "text-muted hover:text-ink hover:bg-bone/60 transition-colors",
            )}
          >
            <EyeOff size={15} strokeWidth={1.5} aria-hidden />
            {total > 0 && (
              <span
                className={cn(
                  "absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full",
                  "bg-magenta text-cream font-mono text-[10px] leading-4 text-center",
                )}
                aria-label={`${total} hidden`}
              >
                {total}
              </span>
            )}
          </button>
        </Tooltip>
      }
      className="min-w-[240px] max-w-[320px]"
    >
      {total === 0 ? (
        <p className="px-2 py-3 font-sans text-sm text-muted text-center">
          Nothing hidden.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {hiddenCols.length > 0 && (
            <Section
              title="Columns"
              items={hiddenCols}
              format={(c) => columnLabel(c)}
              onShow={onShowCol}
            />
          )}
          {hiddenRows.length > 0 && (
            <Section
              title="Rows"
              items={hiddenRows}
              format={(r) => `Row ${r + 1}`}
              onShow={onShowRow}
            />
          )}
          <button
            type="button"
            onClick={() => {
              onShowAll();
              setOpen(false);
            }}
            className={cn(
              "mt-1 mx-2 mb-1 px-2 py-1.5 rounded-md",
              "font-sans text-[12px] text-magenta hover:bg-bone/70 transition-colors",
              "text-left",
            )}
          >
            Show all
          </button>
        </div>
      )}
    </Popover>
  );
}

function Section({
  title,
  items,
  format,
  onShow,
}: {
  title: string;
  items: number[];
  format: (n: number) => string;
  onShow: (n: number) => void;
}) {
  return (
    <div className="flex flex-col">
      <p className="eyebrow px-2 pt-1.5 pb-1">{title}</p>
      <ul className="max-h-[180px] overflow-y-auto">
        {items.map((n) => (
          <li key={n}>
            <button
              type="button"
              onClick={() => onShow(n)}
              className={cn(
                "w-full flex items-center justify-between gap-2 px-2 py-1 rounded-md",
                "text-left font-sans text-sm text-ink hover:bg-bone/70 transition-colors",
              )}
            >
              <span>{format(n)}</span>
              <span className="font-mono text-[11px] text-muted">Show</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A1-style column label: 0→A, 25→Z, 26→AA, 701→ZZ. */
export function columnLabel(col: number): string {
  let n = col;
  let out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}
