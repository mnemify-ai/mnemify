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
Regenerate only when the source logo changes — from this directory:

```sh
mkdir -p mnemify.iconset && uv run --with pillow --with numpy python3 - <<'PY'
import numpy as np
from PIL import Image, ImageDraw

TILE_BG, RADIUS, TOL, RAMP = (245, 239, 232, 255), 225, 12, 40.0

# Key out the flat grey: flood fill from the four corners so only the contiguous
# background goes, then ramp alpha by distance from that grey and un-premultiply
# so anti-aliased edges keep the logo's colour instead of a grey fringe.
src = Image.open("mnemify-logo-source.png").convert("RGB")
W, H = src.size
BG = np.array(src.getpixel((0, 0)), dtype=np.float32)
work = src.copy()
for xy in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
    ImageDraw.floodfill(work, xy, (0, 255, 0), thresh=TOL)
a = np.asarray(work)
bg_region = (a[..., 0] == 0) & (a[..., 1] == 255) & (a[..., 2] == 0)
rgb = np.asarray(src, dtype=np.float32)
alpha = np.clip(np.abs(rgb - BG).max(axis=2) / RAMP, 0.0, 1.0)
alpha[bg_region] = 0.0
af = alpha[..., None]
fg = np.clip(np.where(af > 0.004, (rgb - (1.0 - af) * BG) / np.maximum(af, 0.004), rgb), 0, 255)
keyed = Image.fromarray(np.concatenate([fg, af * 255.0], axis=2).astype(np.uint8), "RGBA")
keyed = keyed.crop(keyed.getbbox())

def compose(canvas_px, frac, bg=None, radius=None):
    w, h = keyed.size
    s = (canvas_px * frac) / max(w, h)
    m = keyed.resize((round(w * s), round(h * s)), Image.LANCZOS)
    if bg is None:
        base = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    elif radius is None:
        base = Image.new("RGBA", (canvas_px, canvas_px), bg)
    else:
        SS = 4  # supersample so the corner arc stays clean
        t = Image.new("RGBA", (canvas_px * SS,) * 2, (0, 0, 0, 0))
        ImageDraw.Draw(t).rounded_rectangle([0, 0, canvas_px * SS - 1, canvas_px * SS - 1],
                                            radius=radius * SS, fill=bg)
        base = t.resize((canvas_px, canvas_px), Image.LANCZOS)
    base.alpha_composite(m, ((canvas_px - m.width) // 2, (canvas_px - m.height) // 2))
    return base

mark = compose(1024, 0.80)
tile = compose(1024, 0.68, bg=TILE_BG, radius=RADIUS)
mark.save("mnemify-mark-1024.png")
tile.save("mnemify-1024.png")

for name, s in [("icon_16x16.png",16),("icon_16x16@2x.png",32),("icon_32x32.png",32),
                ("icon_32x32@2x.png",64),("icon_128x128.png",128),("icon_128x128@2x.png",256),
                ("icon_256x256.png",256),("icon_256x256@2x.png",512),("icon_512x512.png",512),
                ("icon_512x512@2x.png",1024)]:
    (tile if s == 1024 else tile.resize((s, s), Image.LANCZOS)).save("mnemify.iconset/" + name)

mark.save("mnemify.ico", format="ICO",
          sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

P = "../../frontend/web/public/"
mark.resize((32, 32), Image.LANCZOS).save(P + "favicon-32.png")
mark.resize((16, 16), Image.LANCZOS).save(P + "favicon-16.png")
compose(180, 0.68, bg=TILE_BG).convert("RGB").save(P + "apple-touch-icon.png")
PY

iconutil -c icns -o mnemify.icns mnemify.iconset && rm -rf mnemify.iconset
```
