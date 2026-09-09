import * as RadixRadioGroup from "@radix-ui/react-radio-group";
import { cn } from "../../lib/cn";

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: string;
}

export interface SegmentedProps<T extends string = string> {
  value: T;
  onValueChange: (value: T) => void;
  options: ReadonlyArray<SegmentedOption<T>>;
  /** Accessible label for the group. Required for screen readers. */
  ariaLabel?: string;
  /** Compact (h-8) vs default (h-9). */
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
}

/**
 * Two-or-more-option segmented control. Built on Radix RadioGroup so it
 * inherits keyboard navigation (←/→) and a11y semantics for free.
 */
export function Segmented<T extends string = string>({
  value,
  onValueChange,
  options,
  ariaLabel,
  size = "md",
  className,
  disabled,
}: SegmentedProps<T>) {
  const itemHeight = size === "sm" ? "h-7" : "h-8";
  const containerPad = size === "sm" ? "p-0.5" : "p-1";

  return (
    <RadixRadioGroup.Root
      value={value}
      onValueChange={(v) => onValueChange(v as T)}
      aria-label={ariaLabel}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full",
        "bg-bone/70 border border-hair",
        containerPad,
        disabled && "opacity-disabled pointer-events-none",
        className,
      )}
    >
      {options.map((opt) => (
        <RadixRadioGroup.Item
          key={opt.value}
          value={opt.value}
          className={cn(
            "px-3 rounded-full font-sans text-xs font-medium",
            "transition-colors duration-base ease-out",
            "outline-none whitespace-nowrap",
            itemHeight,
            "data-[state=checked]:bg-ink data-[state=checked]:text-cream",
            "data-[state=unchecked]:text-muted data-[state=unchecked]:hover:text-ink",
          )}
        >
          {opt.label}
        </RadixRadioGroup.Item>
      ))}
    </RadixRadioGroup.Root>
  );
}
