#!/usr/bin/env python3
"""Before/after coverage report for the v3 hex bake.

Runs the bake's layout + hex-assignment steps on a compiled ``terrain.json``
and prints what the map would actually show: land hexes, hexes per top-level
region, regions that would render with **zero** hexes (the frontend hides
those), tags with no spire, and how far each region's territory sits from its
layout centre. With ``--baseline`` it re-installs the pre-fix Voronoi
behaviour (hexes warped, centroids not; no zero-hex seeding) so the two runs
can be compared on the same corpus. If matplotlib is importable, ``--png PATH`` writes a top-down
ownership plot with the nominal discs.

Usage (from ``backend/``):
    python scripts/bake_compare.py                     # current code
    python scripts/bake_compare.py --baseline          # pre-fix behaviour
    python scripts/bake_compare.py --png after.png
    python scripts/bake_compare.py --baseline --png before.png
    python scripts/bake_compare.py --terrain path/to/terrain.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.terrain._bake_v3 as B  # noqa: E402


def _baseline_voronoi_assign(
    hex_xs, hex_zs, candidate_idxs, regions, warp_amp,
    reach_cap: Optional[float] = None, apply_outer_cutoff: bool = True,
):
    """Pre-fix behaviour: warp hexes only, measure against unwarped centres."""
    M = len(hex_xs)
    if M == 0 or not candidate_idxs:
        return np.full(M, -1, dtype=np.int32)
    wxs, wzs = B.apply_warp(hex_xs, hex_zs, warp_amp)
    cxs = np.array([regions[i].centroid[0] for i in candidate_idxs])
    czs = np.array([regions[i].centroid[1] for i in candidate_idxs])
    rads = np.array([regions[i].radius for i in candidate_idxs])
    dx = wxs[:, None] - cxs[None, :]
    dz = wzs[:, None] - czs[None, :]
    warped_d2 = dx * dx + dz * dz
    if reach_cap is not None:
        ux = hex_xs[:, None] - cxs[None, :]
        uz = hex_zs[:, None] - czs[None, :]
        unwarped_d2 = ux * ux + uz * uz
        warped_d2 = np.where(unwarped_d2 <= (rads * reach_cap)[None, :] ** 2, warped_d2, np.inf)
    best_local = np.argmin(warped_d2, axis=1)
    best_d2 = warped_d2[np.arange(M), best_local]
    out = np.array(candidate_idxs, dtype=np.int32)[best_local]
    if apply_outer_cutoff:
        out = np.where(best_d2 > (rads[best_local] * B.OUTER_CUTOFF_MUL) ** 2, -1, out)
    return np.where(np.isinf(best_d2), -1, out).astype(np.int32)


def run(terrain: dict, *, baseline: bool, seed: int = B.SEED):
    if baseline:
        B.voronoi_assign = _baseline_voronoi_assign  # type: ignore[assignment]
        B.SEED_ZERO_HEX_LEAVES = False   # pre-fix rescue could not seed erased leaves
        B.BALANCED_NESTED_SUBDIVISION = False   # pre-fix: plain warped Voronoi among children
    random.seed(seed)
    np.random.seed(seed)
    regions = B.load_regions(terrain["tree"])
    B.normalize_semantic_centers(regions)
    implicit = B.derive_implicit_top_level_edges(
        regions, terrain["tree"], terrain["edges"].get("tagEdges", [])
    )
    B.assign_top_level_layout(regions, terrain["edges"]["regionEdges"], implicit, implicit_weight_mul=1.0)
    B.assign_nested_layout(regions, sibling_edges_idx=None)
    extent = B.compute_world_extent(regions)
    qs, rs, xs, zs = B.generate_hex_grid(extent, B.HEX_APOTHEM)
    layout_centres = {i: r.centroid for i, r in enumerate(regions)}
    owners = B.assign_hexes_to_leaves(xs, zs, regions)
    owners, _, _ = B.clean_islands_and_lakes(qs, rs, owners)
    owners, _ = B.expand_squeezed_leaves(qs, rs, xs, zs, owners, regions)
    return regions, xs, zs, owners, extent, layout_centres


def report(regions, xs, zs, owners, layout_centres, label: str) -> dict:
    def root(i):
        while regions[i].parent_idx >= 0:
            i = regions[i].parent_idx
        return i

    roots = np.array([root(o) if o >= 0 else -1 for o in owners])
    tops = [i for i, r in enumerate(regions) if r.level == 0]
    per = {i: int((roots == i).sum()) for i in tops}
    zero = [regions[i].name for i in tops if per[i] == 0]
    leaves_short = [
        regions[i].name for i, r in enumerate(regions)
        if r.is_leaf and (owners == i).sum() < len(r.own_tags)
    ]
    drift = []
    for i in tops:
        m = roots == i
        if m.any():
            cx, cz = layout_centres[i]
            drift.append(math.hypot(xs[m].mean() - cx, zs[m].mean() - cz))
    nested = [i for i, r in enumerate(regions) if r.is_leaf and r.level >= 1]
    nested_counts = {i: int((owners == i).sum()) for i in nested}
    tiny_nested = [regions[i].name for i in nested if nested_counts[i] <= 4]
    land = int((owners >= 0).sum())
    print(f"\n=== {label} ===")
    print(f"land hexes: {land}")
    print(f"top-level regions: {len(tops)}; with ZERO hexes: {len(zero)} {zero}")
    print(f"leaves with fewer hexes than tags (spires with no land): {len(leaves_short)} {leaves_short}")
    if drift:
        print(f"territory drift from layout centre: mean={np.mean(drift):.2f} max={np.max(drift):.2f}")
    if nested:
        print(f"sub-region leaves: {len(nested)}; with <= 4 hexes (not hoverable/drillable): {len(tiny_nested)} {tiny_nested}")
        print("hexes per sub-region leaf (parent -> child):")
        for i in sorted(nested, key=lambda k: (regions[k].parent_idx, -nested_counts[k])):
            r = regions[i]
            print(f"  {nested_counts[i]:5d}  {regions[r.parent_idx].name[:24]:24s} -> {r.name[:36]:36s} tags={r.tag_count} notes={r.note_count}")
    print("hexes per top-level region:")
    for i in sorted(tops, key=lambda k: -per[k]):
        r = regions[i]
        print(f"  {per[i]:5d}  {r.name[:40]:40s} tags={r.tag_count} notes={r.note_count}")
    return {"land": land, "zero": zero, "per": per, "roots": roots, "tops": tops,
            "tiny_nested": tiny_nested, "owners": owners}


def plot(path: str, regions, xs, zs, stats, extent: float, label: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        print(f"(matplotlib unavailable, skipping PNG: {e})")
        return
    fig, ax = plt.subplots(figsize=(9, 9))
    cmap = plt.get_cmap("tab20")
    roots, tops = stats["roots"], stats["tops"]
    colour = {i: cmap(k % 20) for k, i in enumerate(tops)}
    sea = roots < 0
    ax.scatter(xs[sea], zs[sea], s=2, c="#eeeeee")
    # Sub-regions: alternate lighter/darker shades of the top-level colour so
    # the nested subdivision is visible in the render.
    owners = stats["owners"]
    shade = {}
    for i, r in enumerate(regions):
        if r.is_leaf and r.level >= 1:
            sibs = [j for j, q in enumerate(regions) if q.parent_idx == r.parent_idx]
            shade[i] = 0.55 + 0.45 * (sibs.index(i) % 3) / 2.0
    cols = []
    for o, root_i in zip(owners[~sea], roots[~sea]):
        c = colour[root_i]
        f = shade.get(int(o), 1.0)
        cols.append((1 - f * (1 - c[0]), 1 - f * (1 - c[1]), 1 - f * (1 - c[2]), 1.0))
    ax.scatter(xs[~sea], zs[~sea], s=6, c=cols)
    for i in tops:
        r = regions[i]
        ax.plot(*r.centroid, "k+", ms=8)
        ax.add_patch(plt.Circle(r.centroid, r.radius, fill=False, ls=":", lw=0.6, color="k"))
        ax.annotate(f"{r.name[:22]} ({stats['per'][i]})", r.centroid, fontsize=6)
    ax.set_title(f"{label}\nland={stats['land']}  zero-hex regions={len(stats['zero'])}  "
                 f"sub-regions with <= 4 hexes={len(stats['tiny_nested'])}")
    ax.set_aspect("equal")
    ax.set_xlim(-extent, extent)
    ax.set_ylim(-extent, extent)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print(f"wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terrain", default=".mnemify/terrain.json")
    ap.add_argument("--baseline", action="store_true", help="reproduce pre-fix behaviour: hexes warped but centres not, and no zero-hex seeding")
    ap.add_argument("--png", default=None, help="write a top-down ownership plot here (needs matplotlib)")
    args = ap.parse_args()
    terrain = json.loads(Path(args.terrain).read_text(encoding="utf-8"))
    label = "BASELINE (pre-fix voronoi)" if args.baseline else "CURRENT CODE"
    regions, xs, zs, owners, extent, centres = run(terrain, baseline=args.baseline)
    stats = report(regions, xs, zs, owners, centres, label)
    if args.png:
        plot(args.png, regions, xs, zs, stats, extent, label)


if __name__ == "__main__":
    main()
