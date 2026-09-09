import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, X } from "lucide-react";
import { KnowledgeMap } from "../../knowledgeMap";
import { Button } from "./ui/Button";

/**
 * A read-only "feel the payoff first" sample map for the empty state. Points
 * the real <KnowledgeMap> at a bundled v3 render-data fixture (public/demo/*) so a
 * brand-new user can orbit, drill regions, and click tags before investing in
 * connect → harvest → compile. The map's own bottom-bar doc/source summary
 * resolves to nothing here (no compiled map / connections), so it quietly
 * shows just the demo's structure counts — no special-casing needed.
 */
export function DemoTerrain({ onExit }: { onExit: () => void }) {
  const navigate = useNavigate();
  const [selectedTagId, setSelectedTagId] = useState<string | null>(null);

  return (
    <div className="relative min-h-dvh w-screen overflow-hidden">
      <div className="absolute inset-0 z-0">
        <KnowledgeMap
          dataUrl="/demo/render-data.json"
          notesUrl="/demo/notes.json"
          hideHeader
          hideBreadcrumb
          // The drill-down panel reads app-level map data, which is null in
          // the empty state where the demo lives — hide it to avoid a throw.
          hideRightPanel
          selectedTagId={selectedTagId}
          onTagSelect={setSelectedTagId}
        />
      </div>

      {/* Watermark banner — names this a sample and routes onward. */}
      <div className="pointer-events-none absolute inset-x-0 top-20 z-20 flex justify-center px-4">
        <div className="pointer-events-auto glass-panel rounded-full pl-4 pr-2 py-1.5 shadow-sm flex flex-wrap items-center justify-center gap-x-3 gap-y-2 max-w-[calc(100vw-2rem)] animate-fade-in motion-reduce:animate-none">
          <span className="font-sans text-xs text-ink flex items-center gap-1.5">
            <Sparkles size={14} strokeWidth={1.75} className="text-magenta shrink-0" aria-hidden />
            <span>
              <span className="font-medium">Sample map</span>
              <span className="text-muted"> — a preview built from example notes</span>
            </span>
          </span>
          <span className="flex items-center gap-2">
            <Button size="sm" variant="primary" onClick={() => navigate("/build/sources")}>
              Connect a source
            </Button>
            <button
              type="button"
              onClick={onExit}
              aria-label="Exit sample map"
              className="grid place-items-center w-7 h-7 rounded-full text-muted hover:text-ink hover:bg-lavender/60 transition-colors shrink-0"
            >
              <X size={14} strokeWidth={1.75} aria-hidden />
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
