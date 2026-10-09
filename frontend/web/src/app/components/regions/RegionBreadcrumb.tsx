import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import type { RegionPathEntry } from "../../api/regions";
import { RegionSwitcher } from "./RegionSwitcher";

/** "All regions › Parent › current ⌄" — ancestors are links, the current
 *  region is the switcher dropdown. */
export function RegionBreadcrumb({ path, currentId }: { path: RegionPathEntry[]; currentId: string }) {
  const ancestors = path.filter((p) => p.id !== currentId);
  return (
    <nav aria-label="Region path" className="flex flex-wrap items-center gap-1 font-sans text-sm text-muted">
      <Link to="/regions" className="hover:text-ink">All regions</Link>
      {ancestors.map((p) => (
        <span key={p.id} className="inline-flex items-center gap-1">
          <ChevronRight size={14} strokeWidth={1.5} aria-hidden />
          <Link to={`/regions/${encodeURIComponent(p.id)}`} className="hover:text-ink">{p.name}</Link>
        </span>
      ))}
      <ChevronRight size={14} strokeWidth={1.5} aria-hidden />
      <RegionSwitcher currentId={currentId} />
    </nav>
  );
}
