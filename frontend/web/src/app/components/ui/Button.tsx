import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-sans font-medium transition-colors disabled:opacity-disabled disabled:pointer-events-none whitespace-nowrap",
  {
    variants: {
      variant: {
        primary: "bg-magenta text-cream hover:bg-magenta/90",
        secondary: "bg-bone text-ink border border-hair hover:bg-lavender/40",
        ghost: "text-ink hover:bg-bone/60",
        link: "text-magenta underline-offset-4 hover:underline px-0",
        destructive: "bg-danger text-cream hover:bg-danger/90",
      },
      size: {
        sm: "h-8 px-3 text-xs rounded-full",
        md: "h-10 px-4 text-sm rounded-full",
        lg: "h-12 px-6 text-sm rounded-full",
        icon: "h-9 w-9 rounded-full",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    /**
     * When true, the button is marked `aria-busy`, click events are blocked
     * (via the standard `disabled` attribute), and a small spinner replaces
     * any leading icon supplied via children.
     */
    loading?: boolean;
  };

const spinnerSizeFor = (size: ButtonProps["size"]): number => {
  switch (size) {
    case "sm":
      return 12;
    case "lg":
      return 16;
    case "icon":
      return 16;
    default:
      return 14;
  }
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, disabled, children, ...props }, ref) => {
    const isDisabled = disabled || loading;
    return (
      <button
        ref={ref}
        aria-busy={loading || undefined}
        disabled={isDisabled}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      >
        {loading && (
          <Loader2
            size={spinnerSizeFor(size)}
            strokeWidth={2}
            className="animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
