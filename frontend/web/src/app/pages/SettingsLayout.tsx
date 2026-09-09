import { NavLink, Outlet } from "react-router-dom";
import { PageShell } from "../layouts/PageShell";
import { cn } from "../lib/cn";

// Connections live under /build/sources — the connect→harvest flow is one
// journey now. /settings/connections still redirects for deep links, and
// /settings/compile redirects into AI & Models (its contents merged there).
const TABS = [
  { to: "/settings", label: "General", end: true },
  { to: "/settings/ai", label: "AI & Models", end: false },
  { to: "/settings/data", label: "Data", end: false },
  { to: "/settings/schedules", label: "Schedules", end: false },
  { to: "/settings/audit", label: "Audit", end: false },
];

export function SettingsLayout() {
  return (
    <PageShell eyebrow="Preferences" title="Settings" noDivider>
      <a
        href="#settings-main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:bg-cream focus:border focus:border-hair focus:rounded focus:px-3 focus:py-1 focus:font-sans focus:text-sm focus:text-ink focus:z-50"
      >
        Skip to settings content
      </a>
      <nav className="flex items-center gap-1 mt-2 mb-10 border-b border-hair" aria-label="Settings sections">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              cn(
                "relative px-4 py-2.5 -mb-px font-sans uppercase tracking-eyebrow text-[11px] transition-colors",
                "focus:outline-none focus-visible:!shadow-none focus-visible:!rounded-none",
                isActive ? "text-ink border-b-2 border-magenta" : "text-muted hover:text-ink border-b-2 border-transparent",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div id="settings-main" tabIndex={-1} className="outline-none">
        <Outlet />
      </div>
    </PageShell>
  );
}
