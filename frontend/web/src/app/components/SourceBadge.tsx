import { cn } from "../lib/cn";

interface SourceMeta {
  label: string;
  /** Tailwind classes for the brand dot. */
  dotClass: string;
}

const SOURCE_META: Record<string, SourceMeta> = {
  obsidian:        { label: "Obsidian",        dotClass: "bg-[#7E66E3]" },
  notion:          { label: "Notion",          dotClass: "bg-ink" },
  confluence:      { label: "Confluence",      dotClass: "bg-[#2563EB]" },
  jira:            { label: "Jira",            dotClass: "bg-[#0052CC]" },
  gmail:           { label: "Gmail",           dotClass: "bg-[#D93025]" },
  slack:           { label: "Slack",           dotClass: "bg-[#611F69]" },
  google_calendar: { label: "Google Calendar", dotClass: "bg-[#1A73E8]" },
  google_drive:    { label: "Google Drive",    dotClass: "bg-[#0F9D58]" },
  outlook:         { label: "Outlook",         dotClass: "bg-[#0078D4]" },
  onedrive:        { label: "OneDrive",        dotClass: "bg-[#0364B8]" },
  teams:           { label: "Microsoft Teams", dotClass: "bg-[#6264A7]" },
  sharepoint:      { label: "SharePoint",      dotClass: "bg-[#038387]" },
  github:          { label: "GitHub",          dotClass: "bg-ink" },
  linear:          { label: "Linear",          dotClass: "bg-[#5E6AD2]" },
};

export function sourceMeta(source: string): SourceMeta {
  return SOURCE_META[source] ?? { label: capitalize(source), dotClass: "bg-muted" };
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

interface SourceBadgeProps {
  source: string;
  size?: "sm" | "md";
  className?: string;
  showLabel?: boolean;
}

export function SourceBadge({ source, size = "md", className, showLabel = true }: SourceBadgeProps) {
  const meta = sourceMeta(source);
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        className={cn(
          "rounded-full shrink-0",
          meta.dotClass,
          size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2",
        )}
        aria-hidden
      />
      {showLabel && (
        <span
          className={cn(
            "font-sans text-ink",
            size === "sm" ? "text-xs" : "text-sm",
          )}
        >
          {meta.label}
        </span>
      )}
    </span>
  );
}

/** Just the dot, no label — for compact rows in DocTable. */
export function SourceDot({ source, size = "md", className }: Omit<SourceBadgeProps, "showLabel">) {
  return <SourceBadge source={source} size={size} showLabel={false} className={className} />;
}
