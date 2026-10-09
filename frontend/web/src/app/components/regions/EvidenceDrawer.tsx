import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { SourceInspector } from "../../../ask/SourceInspector";
import type { TerrainFocusTarget } from "../../../ask/citationDisplay";
import { useDocIdForNote } from "../../../knowledgeMap/util/useDocResolver";
import { useMapDataReady } from "../../data/MapDataProvider";
import { useMapFocusStore } from "../../lib/mapFocusStore";
import { toastInfo } from "../../lib/toast";

export type EvidenceTarget = {
  /** Harvest-manifest doc id when the server could resolve one. */
  docId: string | null;
  /** Map note id — used to fall back to a title join, and for the URL. */
  noteId: string | null;
  excerpt: string;
  regionId: string;
};

/**
 * "Review evidence" / "Source: … →" — opens the source document in the Ask
 * dock's evidence inspector so the passage can be read beside the item that
 * cites it. Resolution order: the server's doc id, then a (source, title)
 * join on the map note, then the note's external URL as a last resort.
 */
export function EvidenceDrawer({ target, onClose }: { target: EvidenceTarget | null; onClose: () => void }) {
  const navigate = useNavigate();
  const requestFocus = useMapFocusStore((s) => s.requestFocus);
  const { notes } = useMapDataReady();
  const note = useMemo(
    () => (target?.noteId ? notes.notes.find((n) => n.id === target.noteId) ?? null : null),
    [notes.notes, target?.noteId],
  );
  const joined = useDocIdForNote(target && !target.docId ? note : null);
  const docId = target?.docId ?? joined.docId;

  // Nothing to inspect locally → open the source itself, once.
  useEffect(() => {
    if (!target || docId || joined.loading) return;
    if (note?.sourceUrl) window.open(note.sourceUrl, "_blank", "noopener,noreferrer");
    else toastInfo("The source document is not in your harvested set any more.");
    onClose();
  }, [target, docId, joined.loading, note?.sourceUrl, onClose]);

  const inspectorTarget = target && docId
    ? {
        docId,
        heading: null,
        excerpt: target.excerpt,
        updatedAt: note?.updatedAt ?? null,
        sourceUrl: note?.sourceUrl ?? null,
        terrainFocus: { kind: "region", id: target.regionId } as TerrainFocusTarget,
      }
    : null;

  return (
    <SourceInspector
      target={inspectorTarget}
      onClose={onClose}
      onShowOnTerrain={(focus) => {
        if (focus.kind === "region") requestFocus(focus.id);
        navigate(focus.kind === "tag" ? `/?tag=${encodeURIComponent(focus.id)}` : "/");
      }}
    />
  );
}
