# Mnemify app icons

Everything here is generated from `mnemify-logo-source.png` (the isometric "M",
1254×1254 on flat `#F7F7F7`). Two intermediate variants are produced and then
reused by every output:

* **mark** — the M keyed out to transparency, at 80% of a 1024 canvas.
* **tile** — a macOS-style rounded square (radius 225 ≈ 22%) in the brand paper
  cream `#F5EFE8` (the light-theme `c-bg` token in
  `frontend/web/src/app/theme/index.css`), with the mark at 68%.

| File | Variant | Used for |
| --- | --- | --- |
| `mnemify-logo-source.png` | — | Untouched original. The only input; keep it. |
| `mnemify-mark-1024.png` | mark | Transparent 1024 master: docs, slides, dark backgrounds. |
| `mnemify-1024.png` | tile | 1024 app-icon master / store art. |
| `mnemify.icns` | tile | macOS app bundle icon (16–512 pt incl. @2x). |
| `mnemify.ico` | mark | Windows app/installer icon (16, 24, 32, 48, 64, 128, 256). |
| `../../frontend/web/public/favicon-32.png` | mark | Browser favicon. |
| `../../frontend/web/public/favicon-16.png` | mark | Browser favicon. |
| `../../frontend/web/public/apple-touch-icon.png` | tile | iOS home-screen icon (180×180, opaque square — iOS rounds it itself). |

The mark (not the tile) is used at favicon/ICO sizes because at 16 px it renders
the M about 20% larger and it still holds against both light and dark chrome.
Every file is committed, so install/setup scripts never need image tooling.
Regenerate only when the source logo changes: key the M out of
`mnemify-logo-source.png` to transparency, place it at 80% of a 1024 canvas
for the mark and at 68% on a rounded `#F5EFE8` tile for the tile, then export
the sizes above (`iconutil -c icns` for the `.icns`, Pillow `format="ICO"` for
the `.ico`).
