import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Maximize2 } from "lucide-react";
import { KnowledgeMap } from "../../../knowledgeMap";
import { Button } from "../ui/Button";
import { Dialog, DialogClose } from "../ui/Dialog";
import { useMapFocusStore } from "../../lib/mapFocusStore";

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * "Open map" from a region workspace — the 3D map framed on this region in
 * a large dialog, fully interactive (orbit, pan, zoom, click to drill), with
 * a hand-off to the full map on Home. The canvas only exists while the
 * dialog is open, so the workspace itself carries no WebGL cost.
 */
export function RegionMapDialog({
  regionId,
  regionName,
  open,
  onOpenChange,
}: {
  regionId: string;
  regionName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const setFocusRegion = useMapFocusStore((s) => s.setFocusRegion);
  const [webgl, setWebgl] = useState<boolean | null>(null);
  useEffect(() => {
    if (open && webgl === null) setWebgl(hasWebGL());
  }, [open, webgl]);
  // HexField sets the body cursor on hover; don't leave it stuck on close.
  useEffect(() => {
    if (!open) document.body.style.cursor = "default";
  }, [open]);

  const openFullMap = () => {
    onOpenChange(false);
    setFocusRegion(regionId);
    navigate("/");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} width="min(1200px, 94vw)" ariaLabel={`${regionName} on the map`}>
      <header className="flex items-center gap-4 border-b border-hair px-6 py-4 pr-16">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-serif text-xl leading-tight text-ink">{regionName}</h2>
          <p className="mt-0.5 font-sans text-xs text-muted">
            Drag to rotate · right-drag to move · scroll or pinch to zoom · click a hex to go deeper
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={openFullMap} className="gap-1.5">
          <Maximize2 size={13} strokeWidth={1.75} aria-hidden />
          Open full map
        </Button>
      </header>
      <DialogClose onClose={() => onOpenChange(false)} />
      <div className="relative h-[72vh] overflow-hidden rounded-b-3xl bg-cream">
        {open && webgl ? (
          <div className="absolute inset-0">
            <KnowledgeMap preview focusRegionId={regionId} hideHeader hideBottomBar hideRightPanel />
          </div>
        ) : webgl === false ? (
          <div className="absolute inset-0 grid place-items-center px-6 text-center font-sans text-sm text-muted">
            This browser can't draw the 3D map (WebGL is unavailable).
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
