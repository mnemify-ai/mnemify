import type { CSSProperties, HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type BaseProps = Omit<HTMLAttributes<HTMLDivElement>, "children">;

interface LineSkeletonProps extends BaseProps {
  variant?: "line";
  /** CSS width — e.g. "100%", "12ch", 240. Default "100%". */
  width?: string | number;
}

interface BlockSkeletonProps extends BaseProps {
  variant: "block";
  /** CSS aspect-ratio, e.g. "16/9". When set, height is derived from width. */
  aspectRatio?: string;
  width?: string | number;
  height?: string | number;
}

interface CircleSkeletonProps extends BaseProps {
  variant: "circle";
  /** Diameter — px number or any CSS length. Default 32. */
  size?: string | number;
}

export type SkeletonProps =
  | LineSkeletonProps
  | BlockSkeletonProps
  | CircleSkeletonProps;

const toCssLength = (v: string | number | undefined): string | undefined =>
  typeof v === "number" ? `${v}px` : v;

/**
 * Loading-state placeholder. Three variants:
 *  - `line` (default): 1em tall, custom `width`.
 *  - `block`: rectangular, `aspectRatio` or explicit `height`/`width`.
 *  - `circle`: round, `size` diameter.
 *
 * Honors `prefers-reduced-motion` via Tailwind's `motion-reduce:animate-none`.
 */
export function Skeleton(props: SkeletonProps) {
  const base =
    "bg-bone/60 animate-skeleton-pulse motion-reduce:animate-none";

  if (props.variant === "block") {
    const { variant: _v, aspectRatio, width, height, className, style, ...rest } = props;
    const mergedStyle: CSSProperties = {
      width: toCssLength(width) ?? "100%",
      ...(aspectRatio ? { aspectRatio } : {}),
      ...(height !== undefined ? { height: toCssLength(height) } : {}),
      ...style,
    };
    return (
      <div
        aria-hidden="true"
        className={cn(base, "rounded-xl", className)}
        style={mergedStyle}
        {...rest}
      />
    );
  }

  if (props.variant === "circle") {
    const { variant: _v, size = 32, className, style, ...rest } = props;
    const dim = toCssLength(size);
    return (
      <div
        aria-hidden="true"
        className={cn(base, "rounded-full shrink-0", className)}
        style={{ width: dim, height: dim, ...style }}
        {...rest}
      />
    );
  }

  // line (default)
  const { variant: _v, width = "100%", className, style, ...rest } = props;
  return (
    <div
      aria-hidden="true"
      className={cn(base, "rounded", className)}
      style={{ width: toCssLength(width), height: "1em", ...style }}
      {...rest}
    />
  );
}
