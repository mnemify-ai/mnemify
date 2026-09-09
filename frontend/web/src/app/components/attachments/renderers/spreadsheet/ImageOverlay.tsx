// Absolute-positioned overlay drawing embedded images on top of the
// virtualized base rows. Anchors come from ExcelJS (`useSheetParse.ts`)
// and use display rows (0 = header, 1+ = data). We convert to data-row
// indices before projecting.
//
// Sizing note: image WIDTH/HEIGHT come from `nativeWidthPx`/`nativeHeightPx`
// — Excel's intended pixel size computed against the document's own column
// widths and row heights. Our display columns are widened for readability,
// so reusing display geometry for sizing would balloon images. Position
// (top/left) still uses display geometry so the image hovers over the
// correct cell. Zoom multiplies both axes so the image scales with the grid.

import { emuToPx, intersectsRowRange, type SheetGeometry } from "./geometry";
import type { SheetImage } from "./useSheetParse";

interface ImageOverlayProps {
  images: SheetImage[];
  geometry: SheetGeometry;
  rowNumGutterPx: number;
  visibleDataRowStart: number;
  visibleDataRowEnd: number;
  zoom: number;
}

export function ImageOverlay({
  images,
  geometry,
  rowNumGutterPx,
  visibleDataRowStart,
  visibleDataRowEnd,
  zoom,
}: ImageOverlayProps) {
  if (images.length === 0) return null;

  return (
    <>
      {images.map((img) => {
        // Display-row → data-row conversion. Images anchored above the
        // header (tlRow = 0) are clipped — we treat them as data row 0.
        const dataTlRow = Math.max(0, img.tlRow - 1);
        const dataBrRow =
          img.brRow != null ? Math.max(0, img.brRow - 1) : undefined;
        const endRow = dataBrRow ?? dataTlRow;
        if (!intersectsRowRange(dataTlRow, endRow, visibleDataRowStart, visibleDataRowEnd))
          return null;

        // Position: top-left of the anchor cell in display coordinates
        // (already zoom-scaled by effectiveColWidths/RowHeights).
        const left =
          geometry.colLefts[img.tlCol] + emuToPx(img.tlColOffsetEmu) * zoom;
        const top =
          geometry.rowTops[dataTlRow] + emuToPx(img.tlRowOffsetEmu) * zoom;

        // Size: Excel-native pixels × zoom so the image scales with the grid
        // but doesn't get stretched to fill our widened display columns.
        const width = img.nativeWidthPx * zoom;
        const height = img.nativeHeightPx * zoom;
        if (width <= 0 || height <= 0) return null;

        return (
          <img
            key={img.id}
            src={img.blobUrl}
            alt=""
            className="sheet-image"
            style={{
              position: "absolute",
              left: left + rowNumGutterPx,
              top,
              width,
              height,
              pointerEvents: "none",
            }}
          />
        );
      })}
    </>
  );
}
