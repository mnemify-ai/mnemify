# Terrain Render Pipeline — How Notes Become the Hex Map

> **Purpose.** This document explains, end to end, how harvested notes are
> turned into the 3D hex "island" the frontend renders. It is the missing
> mental model for the geometry in `backend/src/terrain/_bake_v3.py`, which was
> written fast and never fully documented.
>
> Every concrete number below was verified against the persona_5 output
> (`backend/.mnemify/render-data.json`, 50 notes) on 2026-06-24. Where a
> claim is a verified measurement it is marked ✓.

---

## 1. The metaphor

The map is a **topographic island of your knowledge**, like a Catan/Civilization board:

| Map element | Means |
|---|---|
| A colored cluster of hexes (a **territory**) | A topic (region) |
| **Elevation** of a hex | How much *attention* that area demands |
| A **mountain peak** | A single tag (named sub-topic) |
| The cream **sea** between land | Empty space between topics |

Everything in the pipeline exists to produce that island from text.

---

## 2. The data side — three kinds of node

Produced by the compiler (`backend/src/terrain/pipelines/compiler.py`) into
`terrain.json`:

1. **Regions** — a *tree*. Level-0 regions are big territories; they nest into
   level-1/2/3 sub-regions. A region with children is a **container**; a region
   with no children but with tags is a **leaf**. **Only leaves get terrain.**
2. **Tags** — named labels that live *only on leaves* (e.g. "Incident
   Management"). Each tag has an `elevation` (0–100) =
   `frequency × recency × degree`, normalized to the corpus
   (`compiler.py` `raw_scores`/`elevations`). This number becomes a peak height.
3. **Notes** — source documents, attached to tags/regions for the side panels
   and chat (emitted to `mocknotes.json`).

The tree is the **skeleton**; the bake (`_bake_v3.py`) gives it a **body**.

---

## 3. The geometry pipeline

Entry point: `render_v3.bake_v3(terrain, notes)`, called by the compiler as its
final step. The five conceptual stages (code in `_bake_v3.py`):

### Step 1 — Place the territories (`assign_top_level_layout`, `assign_nested_layout`)
Each region gets a 2D **center** and a **radius**:

```
radius = radius_k × √(tag_count)        # LEVEL_PARAMS: radius_k = 4.5 / 2.5 / 1.5 by depth
```

→ **more tags ⇒ bigger disc.** Positions come from the compiler's semantic
layout (similar topics placed near each other); a relaxation pass
(`_relax_overlaps`) nudges only *overlapping* discs apart so the semantic
spread is preserved. Child radius is clamped to ≤ `0.40 × parent.radius`
(`SUB_RADIUS_CLAMP`).

### Step 2 — Lay a hex grid (`generate_hex_grid`)
Pointy-top axial coordinates `(q, r)` → world `(x, z)` with apothem `H = 0.5`
(`HEX_APOTHEM`, emitted as `hexSize`):

```
x = H · (2q + r)
z = H · √3 · r
```

### Step 3 — Assign each hex to a region: warped Voronoi (`assign_hexes_to_leaves`, `voronoi_assign`)
Each hex goes to the nearest region **center**, but distances are pushed through
a 3-octave sine **warp** (`apply_warp`, amplitude `warpAmp`) so borders are
wiggly/organic, not clean circles. Assignment recurses: top-level first (with a
`reach_cap` and an `outer_cutoff` → hexes too far become **sea = -1**), then each
parent's territory is subdivided among its children down to leaves.

The warp is **differential**: hexes *and* centroids go through `apply_warp`, so
only the change of the warp field across a region wobbles its border (the
shared displacement cancels). Nested subdivision (`balanced_subdivide`) is a
**capacity-constrained power diagram**: children compete on warped distance
minus an additive weight, and the weights are adjusted until every child owns
a share of the parent's hexes proportional to its tag count. Geometry decides
*where* a child sits; the weights decide *how much* it gets. Without this, the
warp gradient (up to ~1 unit per unit at `warp_amp` 7) squeezed siblings a few
units apart out entirely — a 30-note sub-region kept 1 hex while a 6-note
sibling kept 181 — so sub-regions could neither be hovered nor drilled into.
`BALANCED_NESTED_SUBDIVISION = False` restores the old plain-Voronoi split.

### Step 4 — Tags + heights (the core of "what is height") (`assign_tags_and_heights`, `diffuse_heights`)
- Each leaf gets a **plateau** (its base ground level):
  ```
  plateau = MAX_PLATEAU × (1 − avgElevation/100)      # MAX_PLATEAU = 10
  ```
  Counter-intuitive but deliberate: *higher* attention ⇒ *lower* plateau,
  because the **tags** then carry the height above it. ✓ (e.g. Operational
  Engineering Management: avgElevation 100 ⇒ plateau 0.00; Compliance Data
  Retention: avgElevation 4 ⇒ plateau 9.60.)
- Each tag is dropped on one hex (its **summit**) and raised to:
  ```
  height = plateau + bump,   bump = max(MIN_TAG_BUMP=3, elevation × TAG_SCALE=0.40)
  ```
- The summit **grows into a ~19-hex cluster** (`expand_tag_claims`,
  `HEXES_PER_TAG = 19`: center + 2 rings) stepping down by BFS depth, so a tag
  reads as a small mountain, not a spike.
- **Diffusion** (`diffuse_heights`, 80 iters): every non-peak, non-shore hex
  averages toward its same-region neighbors; sea counts as height 0. Peaks stay
  pinned, slopes ramp down to the shore → the smooth "Kontur" look. Heat does
  **not** conduct across top-level region borders.

### Step 5 — Pack into `render-data.json` (`build_render_data`)
Only **owned** (non-sea) hexes are emitted. `bounds` is computed from the owned
hexes' extent (not the regions), and `maxY` is the tallest hex.

---

## 4. What one hex actually is

`hexes` is a flat array of **5 numbers per tile**: `[q, r, regionIdx, height, tagIdx]`.

Decoded from persona_5 `render-data.json` ✓:

| Raw 5-tuple | regionIdx → region | height | tagIdx → tag | Reading |
|---|---|---|---|---|
| `2, -5, 8, 40.0, 3` | 8 = Operational Engineering Mgmt | **40.0** | 3 = "Engineering Operations Management" | The **summit** — tallest hex on the map |
| `0, 0, 7, 13.84, 2` | 7 = Incident Management | 13.84 | 2 = "Incident Management" | A peak in the incident territory |
| `6, -11, 8, 1.39, -1` | 8 = Operational Engineering Mgmt | 1.39 | -1 | A **filler/shore** tile — no tag, low height |

- **`regionIdx`** indexes `regions[]` and **always points to a leaf**. The tile's
  **color** is that region's color; leaves inherit their top-level ancestor's
  color (`load_regions`) — which is why an entire continent is one hue.
- **`tagIdx ≥ 0`** = a clickable tag tile (look it up in `tagIndex` / `tagLabels`);
  `-1` = plain terrain.
- **`height`** = the y-elevation the renderer extrudes the tile to. Sea is simply
  omitted.

**One hex = one tile of ground. Its region sets its color, its tag (if any)
makes it a clickable peak, and its height is the diffused attention-elevation.**

---

## 5. The full chain

```
notes
  → tags (each with elevation = frequency × recency × degree)
  → region tree (leaves carry tags)
  → discs (center from semantics, radius = radius_k × √tag_count)
  → hex grid (q,r → x,z)
  → warped-Voronoi territories (+ reach cap / outer cutoff → sea)
  → tag summits + 19-hex clusters + height diffusion
  → owned-hex 5-tuples [q, r, regionIdx, height, tagIdx]   ← what the 3D view extrudes
```

---

## 6. Worked example: why the persona_5 map looks sparse

Measured from `render-data.json` ✓: **167 owned hexes**, **10 regions**, but only
**4 of them render any terrain**:

| regionIdx | region | level | leaf? | radius | tags | hexes owned |
|---|---|---|---|---|---|---|
| 0 | Founder Reflections | 0 | leaf | 4.50 | 1 | **0** ⚠ |
| 1 | Engineering Operations | 0 | container | 10.06 | 5 | 0 (correct — container) |
| 2 | Product and Compliance Strategies | 1 | container | 4.02 | 3 | 0 (correct) |
| 3 | Product And Strategy Insights | 2 | container | 1.61 | 2 | 0 (correct) |
| 4 | Vendor Selection Strategy | 3 | leaf | 4.25 | 1 | 48 |
| 5 | Engineering Infrastructure Strategy | 3 | leaf | **0.64** | 1 | **0** ⚠ |
| 6 | Compliance Data Retention | 2 | leaf | 1.83 | 1 | 5 |
| 7 | Incident Management | 1 | leaf | 7.06 | 1 | 30 |
| 8 | Operational Engineering Management | 1 | leaf | 8.31 | 1 | **84** |
| 9 | Hiring Evaluation | 0 | leaf | 4.50 | 1 | **0** ⚠ |

Two distinct things are happening:

1. **Containers (1, 2, 3) correctly own no hexes** — only leaves get terrain.
   This is by design, not a bug.

2. **Three *leaf* regions vanish (0, 5, 9)** — they should have terrain but
   render nothing:
   - **Founder Reflections (0)** and **Hiring Evaluation (9)** are top-level
     leaves with **1 tag ⇒ radius 4.50**, but `warpAmp = 14` is ~3× their
     radius. The warp displaces their hexes farther than the `outer_cutoff`
     (`radius × 1.15`) permits, so every candidate hex is rejected into sea.
     They survive only as metadata with off-map centroids
     (`(-16.9, 18.8)` and `(20.6, 17.6)`) while `bounds.x ∈ [-7.5, 7.0]` — i.e.
     they are the "dots floating off the map."
     **Lesson: a region smaller than the warp amplitude gets annihilated.**
   - **Engineering Infrastructure Strategy (5)** is a depth-3 leaf clamped to
     **radius 0.64**; it loses the nested-Voronoi contest to its sibling
     *Vendor Selection Strategy* and can't recover a single hex.

Both failure modes share **one root cause: the clustering collapse.** 45/50
notes landed in one leaf (Operational Engineering Management → 84 hexes, half the
island), which (a) makes the map monochrome — one dominant top-level color — and
(b) starves every other region of tags, so their radii are tiny and the warp
erases them.

### Addendum (2026-09-02, later) — sub-regions squeezed out by the nested split

Fixing the top-level annihilation exposed the same weakness one level down.
The nested split was plain warped Voronoi on the children's centroids; with
the warp gradient exceeding the sibling spacing, one child took almost the
whole parent (Document Intelligence: 305 hexes → one grandchild 181, four
siblings 1–4 each). On the map this reads as "hovering never shows a
sub-region" and "drilling into a sub-region changes the panel and the camera
but the highlight stays the same" (the highlighted child *was* the parent's
territory). Nested subdivision is now tag-proportional (`balanced_subdivide`,
see Step 3): all 19 sub-region leaves on that corpus own 20–102 hexes, each a
single connected block, 0 exclaves. `scripts/bake_compare.py` prints per
sub-region counts and flags any with ≤ 4 hexes.

### Implication (updated 2026-09-02 — root cause found and fixed)

The "annihilation" was **not** fundamentally a clustering problem. The real
cause was in `voronoi_assign`: hex positions were passed through `apply_warp`
but the region centroids they were measured against were **not**. Locally
(over one region's radius) the warp field is a near-constant displacement of
about `warp_amp` (measured ≈ 12 units on a real corpus), so every disc was
shifted bodily by that amount relative to its own centre. A disc of radius
13.5 shifted by 12 still overlaps its centre; a radius-4.5 disc does not, and
the outer cutoff (`radius × 1.15`) rejected every one of its hexes into sea.
On a 23-region Confluence corpus **8 top-level regions (12% of chunks)
rendered zero hexes**, every other region kept only a fraction of the territory
it had won (Document Intelligence: 601 hexes won → 263 kept; total land 778),
and territories sat 4.4 units (max 7.8) from their labels.

**Fix (in `voronoi_assign`):** the candidate centroids are warped with the
same field, so the distance is warped-hex → warped-centre and the shared
displacement cancels. Only the *difference* of the field across a region
wiggles its border, which is what the warp was meant to do. On the same
corpus: 0 lost regions, 36/36 tags rendered, land ≈ 2100 hexes, drift 0.7.
Borders stay organic (a "cutoff on unwarped distance" variant also rescued
every region but rendered near-perfect circles).

**Second fix (in `expand_squeezed_leaves`):** the rescue pass could only grow
from hexes a leaf already owned, so it never fired for a fully erased leaf.
Zero-hex leaves are now seeded first (nearest hex to the centroid that is sea
or belongs to a non-squeezed leaf; deterministic order; never stealing from
another squeezed leaf), and growth can never push any leaf below its own tag
count. `SEED_ZERO_HEX_LEAVES` exists only so `scripts/bake_compare.py
--baseline` can reproduce the old picture.

**Observability:** the compiler now logs render coverage (regions and tags
rendered vs compiled, land hexes, hexes per region) on the compile stream and
stores it under `counts.render` in `terrain_runs`; a warning is emitted if any
region or tag is dropped. `tests/test_bake_v3.py` pins the invariants.

The clustering point above still stands on its own merits (one giant region
plus scraps makes a monochrome map), but it is no longer what decides whether
a small region is *visible*. Region **area** is still `radius_k × √tag_count`,
i.e. driven by tag count, not by how many notes a region holds — a 2-note
region can out-size a 17-note one. That is a product decision, tracked
separately.

---

## 7. Key constants (cheat sheet, `_bake_v3.py`)

| Constant | Value | Role |
|---|---|---|
| `HEX_APOTHEM` | 0.5 | hex size; smaller = denser grid |
| `LEVEL_PARAMS[].radius_k` | 4.5 / 2.5 / 1.5 | region radius per √(tag_count), by depth |
| `LEVEL_PARAMS[].warp_amp` | 14 / 7 / 3.5 | Voronoi border wiggle (and the annihilation risk above) |
| `SUB_RADIUS_CLAMP` | 0.40 | child radius ≤ 0.40 × parent |
| `MAX_PLATEAU` | 10 | base ground ceiling; `plateau = 10·(1−avgElev/100)` |
| `TAG_SCALE` / `MIN_TAG_BUMP` | 0.40 / 3 | peak height above plateau = `max(3, elev·0.40)` |
| `HEXES_PER_TAG` | 19 | center + 2 rings per tag cluster |
| `DIFFUSE_ITERS` / `DIFFUSE_ALPHA` | 80 / 0.15 | height smoothing strength |
| `SEA_THRESHOLD` | 1.0 | filler hexes below this revert to sea after diffusion |

---

## 8. Render-data field reference (`render-data.json`)

| Field | Meaning |
|---|---|
| `bounds` | extent of **owned hexes** in world coords; `maxY` = tallest hex |
| `palette.bg` / `palette.ramp` | sea color / low→high height color ramp |
| `hexSize` | `HEX_APOTHEM` (0.5) |
| `regions[]` | flat DFS pre-order of the tree (parents before children); `parentIdx = -1` for top-level |
| `hexes[]` | flat `[q, r, regionIdx, height, tagIdx]` × N, owned tiles only |
| `tagIndex` / `tagLabels` | parallel arrays: stable tag id ↔ human label, indexed by `tagIdx` |
| `tagRecency` / `tagAttentionScore` / `tagAttentionLevel` | per-tag signals, parallel to `tagIndex` |
| `tagRegionWeights` | per-tag many-to-many region membership (home + related), as `regionIdx` |
| `arcs` | cross-region tag co-occurrence links (data only; 3D arc rendering removed) |
| `highlights` | god / bridge / trending tag ids |
| `shaderParams` | `warpAmp`, `reachCapMultiplier` passed to the frontend shader |
