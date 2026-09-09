import { Page } from "react-pdf";
import type { CustomTextRendererFn } from "./searchIndex";

interface PdfPageProps {
  pageNumber: number;
  width: number;
  rotation: 0 | 90 | 180 | 270;
  /** Falsy when search is closed or page has no matches; passing `undefined`
   *  in that case lets react-pdf skip the per-item renderer call. */
  customTextRenderer?: CustomTextRendererFn;
  /** Skeleton/placeholder while pdf.js renders the canvas. */
  loading?: React.ReactNode;
  /** Fired once the text layer DOM exists; we use this in the orchestrator
   *  to flush a pending scroll-to-match for the active search match. */
  onRenderTextLayerSuccess?: () => void;
}

/**
 * Thin wrapper around react-pdf's `<Page>`. Exists to:
 *   - Stamp `data-page={n}` on the page container so the orchestrator's
 *     `querySelector('[data-page=X] mark[data-active]')` works for
 *     scroll-to-match.
 *   - Centralize the `renderAnnotationLayer: false` decision (we don't
 *     theme PDF link styling yet) so the choice lives in one spot.
 */
export function PdfPage({
  pageNumber,
  width,
  rotation,
  customTextRenderer,
  loading,
  onRenderTextLayerSuccess,
}: PdfPageProps) {
  return (
    <div data-page={pageNumber}>
      <Page
        pageNumber={pageNumber}
        width={width}
        rotate={rotation}
        renderAnnotationLayer={false}
        renderTextLayer
        customTextRenderer={customTextRenderer}
        loading={loading}
        onRenderTextLayerSuccess={onRenderTextLayerSuccess}
      />
    </div>
  );
}
