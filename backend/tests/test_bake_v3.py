"""Regression tests for the v3 hex bake (``src/terrain/_bake_v3.py``).

Background: the warped-Voronoi step used to warp hex positions but not the
region centroids it measured against. Locally the warp is a near-constant
displacement of ~warp_amp, so any region whose radius was smaller than that
lost every hex to the outer cutoff, and the frontend hid it. On a real corpus
8 of 23 top-level regions (12% of chunks) vanished this way. The rescue pass
(``expand_squeezed_leaves``) could not help because it only grows from hexes a
leaf already owns. These tests pin the invariants the fixes restore.
"""
from __future__ import annotations

import math

import numpy as np

import src.terrain._bake_v3 as bake
from src.terrain.render_v3 import bake_v3


def _region(idx_name: str, centroid, radius, *, n_tags=1, level=0, parent_idx=-1,
            note_count=1) -> bake.Region:
    return bake.Region(
        id=idx_name, name=idx_name, level=level, parent_idx=parent_idx,
        is_leaf=True, color="#888", accent=None, tag_count=n_tags,
        avg_elevation=10.0, centroid=centroid, radius=radius,
        note_count=note_count,
        own_tags=[{"id": f"tag.{idx_name}.{k}", "elevation": 10.0} for k in range(n_tags)],
    )


def _grid(extent: float):
    return bake.generate_hex_grid(extent, bake.HEX_APOTHEM)


# ---------------------------------------------------------------------------
# voronoi_assign — a lone small region must keep territory under a big warp
# ---------------------------------------------------------------------------

def test_voronoi_assign_small_region_survives_large_warp():
    # The hex grid is a parallelogram, so keep the sweep well inside it.
    qs, rs, xs, zs = _grid(48.0)
    radius = bake.LEVEL_PARAMS[0]["radius_k"]  # 1-tag top-level radius (4.5)
    warp = bake.LEVEL_PARAMS[0]["warp_amp"]     # 14 — ~3× the radius
    # Sweep the centre across the warp field: pre-fix, many positions lost
    # every hex (the failure depended on where the region happened to land).
    # The differential warp still stretches/squeezes a disc with the local
    # field gradient, so the hex count varies (a 441-position sweep gave
    # min 7 / median 62 against a nominal ~97); the invariant is that the
    # region always renders with land for its tags and stays where it was laid out.
    counts, drifts = [], []
    for cx in np.arange(-24.0, 25.0, 6.0):
        for cz in np.arange(-24.0, 25.0, 6.0):
            region = _region("r", (cx, cz), radius)
            owners = bake.voronoi_assign(
                xs, zs, [0], [region], warp_amp=warp,
                reach_cap=bake.LEVEL_PARAMS[0]["reach_cap"], apply_outer_cutoff=True,
            )
            owned = np.where(owners == 0)[0]
            assert len(owned) >= len(region.own_tags), (cx, cz, len(owned))
            counts.append(len(owned))
            drifts.append(math.hypot(xs[owned].mean() - cx, zs[owned].mean() - cz))
    assert min(counts) > 0
    assert np.median(counts) >= bake.HEXES_PER_TAG
    # Territory stays centred on the region, not displaced by the warp
    # (pre-fix the shared displacement was ~warp_amp ≈ 14).
    assert float(np.mean(drifts)) < 1.5, np.mean(drifts)


def test_voronoi_assign_is_invariant_to_a_constant_displacement(monkeypatch):
    """With a spatially constant warp, warped and unwarped assignment agree."""
    qs, rs, xs, zs = _grid(20.0)
    regions = [_region("a", (-6.0, 0.0), 4.5), _region("b", (6.0, 0.0), 4.5)]
    baseline = bake.voronoi_assign(xs, zs, [0, 1], regions, warp_amp=0.0,
                                   reach_cap=1.35, apply_outer_cutoff=True)
    monkeypatch.setattr(bake, "apply_warp", lambda x, z, amp: (x + amp, z - amp))
    shifted = bake.voronoi_assign(xs, zs, [0, 1], regions, warp_amp=14.0,
                                  reach_cap=1.35, apply_outer_cutoff=True)
    assert np.array_equal(baseline, shifted)


# ---------------------------------------------------------------------------
# expand_squeezed_leaves — zero-hex leaves get a seed, with rules
# ---------------------------------------------------------------------------

def test_expand_squeezed_leaves_seeds_zero_hex_leaves():
    qs, rs, xs, zs = _grid(12.0)
    big = _region("big", (0.0, 0.0), 6.0, n_tags=1, note_count=50)
    ghost_a = _region("ghost_a", (0.0, 0.0), 4.5, n_tags=1, note_count=5)   # centre inside big
    ghost_b = _region("ghost_b", (0.0, 0.0), 4.5, n_tags=1, note_count=3)   # same centre → conflict
    regions = [big, ghost_a, ghost_b]
    owners = np.full(len(xs), -1, dtype=np.int32)
    owners[(xs ** 2 + zs ** 2) <= 6.0 ** 2] = 0   # big owns a disc; ghosts own nothing

    out, n = bake.expand_squeezed_leaves(qs, rs, xs, zs, owners, regions)

    a_hexes = np.where(out == 1)[0]
    b_hexes = np.where(out == 2)[0]
    assert len(a_hexes) >= 1 and len(b_hexes) >= 1
    assert n >= 2
    # Distinct seeds: the two zero-hex leaves never claim the same hex.
    assert set(a_hexes.tolist()).isdisjoint(b_hexes.tolist())
    # Seeds come from the non-squeezed neighbour (big), nearest to the centre.
    for hex_set in (a_hexes, b_hexes):
        d = np.hypot(xs[hex_set], zs[hex_set])
        assert d.min() < 2.0
    # Only the two seeds (and BFS-owed hexes, none here) were taken from `big`.
    assert (out == 0).sum() == (owners == 0).sum() - len(a_hexes) - len(b_hexes)


def test_expand_squeezed_leaves_never_steals_from_another_squeezed_leaf():
    qs, rs, xs, zs = _grid(10.0)
    # `small` owns exactly one hex (needs 1 more for its 2 tags); `ghost` owns
    # none and its centroid sits ON small's only hex.
    small = _region("small", (0.0, 0.0), 2.0, n_tags=2, note_count=2)
    ghost = _region("ghost", (0.0, 0.0), 2.0, n_tags=1, note_count=9)
    regions = [small, ghost]
    owners = np.full(len(xs), -1, dtype=np.int32)
    nearest = int(np.argmin(xs ** 2 + zs ** 2))
    owners[nearest] = 0
    out, _ = bake.expand_squeezed_leaves(qs, rs, xs, zs, owners, regions)
    assert out[nearest] == 0, "seed must not be stolen from another squeezed leaf"
    assert (out == 1).sum() >= 1, "ghost still gets seeded on a neighbouring sea hex"


# ---------------------------------------------------------------------------
# balanced_subdivide — every child gets a tag-proportional share of its parent
# ---------------------------------------------------------------------------

def _parent_disc(radius: float):
    """Hexes of a parent disc centred at the origin."""
    qs, rs, xs, zs = _grid(radius + 2)
    inside = xs * xs + zs * zs <= radius * radius
    return qs[inside], rs[inside], xs[inside], zs[inside]


def test_balanced_subdivide_gives_clustered_siblings_a_fair_share():
    """Three children sit almost on top of each other, one sits apart. Plain
    warped Voronoi hands the lone child ~everything and can leave a clustered
    one with a single hex (a 30-note sub-region kept 1 of 305 on a real
    corpus). Balanced subdivision gives each 1-tag child ~a quarter."""
    qs, rs, xs, zs = _parent_disc(10.0)
    parent = _region("P", (0.0, 0.0), 10.0, n_tags=4)
    parent.is_leaf = False
    kids = [
        _region("A", (-1.0, 0.5), 2.5, level=1, parent_idx=0),
        _region("B", (-0.5, -0.5), 2.5, level=1, parent_idx=0),
        _region("C", (0.5, 0.0), 2.5, level=1, parent_idx=0),
        _region("D", (7.0, 0.0), 2.5, level=1, parent_idx=0),
    ]
    regions = [parent] + kids
    owners = bake.balanced_subdivide(xs, zs, [1, 2, 3, 4], regions, warp_amp=7.0)
    assert (owners >= 0).all()
    share = len(xs) / 4
    counts = [int((owners == i).sum()) for i in range(1, 5)]
    for c in counts:
        assert abs(c - share) <= max(2, 0.10 * share), counts


def test_balanced_subdivide_shares_are_proportional_to_tag_count():
    qs, rs, xs, zs = _parent_disc(9.0)
    parent = _region("P", (0.0, 0.0), 9.0, n_tags=3)
    parent.is_leaf = False
    big = _region("big", (-2.0, 0.0), 3.5, n_tags=2, level=1, parent_idx=0)
    small = _region("small", (2.0, 0.0), 2.5, n_tags=1, level=1, parent_idx=0)
    regions = [parent, big, small]
    owners = bake.balanced_subdivide(xs, zs, [1, 2], regions, warp_amp=7.0)
    n_big = int((owners == 1).sum())
    n_small = int((owners == 2).sum())
    assert n_big + n_small == len(xs)
    assert abs(n_big - 2 * n_small) <= max(3, 0.12 * len(xs)), (n_big, n_small)


def test_balanced_subdivide_child_outside_parent_disc_still_gets_territory():
    """Children are placed at their own semantic centre, which can fall outside
    the parent's disc; it must still receive the nearest part of the parent."""
    qs, rs, xs, zs = _parent_disc(8.0)
    parent = _region("P", (0.0, 0.0), 8.0, n_tags=2)
    parent.is_leaf = False
    inside = _region("in", (0.0, 0.0), 2.0, level=1, parent_idx=0)
    outside = _region("out", (14.0, 0.0), 2.0, level=1, parent_idx=0)
    regions = [parent, inside, outside]
    owners = bake.balanced_subdivide(xs, zs, [1, 2], regions, warp_amp=7.0)
    n_out = int((owners == 2).sum())
    assert abs(n_out - len(xs) / 2) <= max(2, 0.10 * len(xs))
    # ...and it takes the side of the parent nearest to it.
    assert xs[owners == 2].mean() > xs[owners == 1].mean()


def test_balanced_subdivide_is_deterministic():
    qs, rs, xs, zs = _parent_disc(7.0)
    parent = _region("P", (0.0, 0.0), 7.0, n_tags=3)
    parent.is_leaf = False
    kids = [_region(str(k), (k - 1.0, 0.3 * k), 2.0, level=1, parent_idx=0) for k in range(3)]
    regions = [parent] + kids
    a = bake.balanced_subdivide(xs, zs, [1, 2, 3], regions, warp_amp=7.0)
    b = bake.balanced_subdivide(xs, zs, [1, 2, 3], regions, warp_amp=7.0)
    assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Full bake on a synthetic v2 terrain — no region or tag may vanish
# ---------------------------------------------------------------------------

def _leaf(i: int, x: float, z: float, n_tags: int, level: int = 0) -> dict:
    return {
        "id": f"node_{i}", "name": f"Region {i}", "level": level,
        "center": {"x": x, "z": z}, "color": "#3F6DF3",
        "aggregateCounts": {"tags": n_tags, "notes": 3 * n_tags, "sources": 1},
        "children": [],
        "tags": [
            {"id": f"tag.node_{i}.{k}", "label": f"Tag {i}.{k}",
             "elevation": 20.0 + 5 * k, "recencyScore": 0.2}
            for k in range(n_tags)
        ],
    }


def _synthetic_terrain() -> dict:
    tree = []
    # Eight 1-tag leaves on a ring (the shape that used to vanish).
    for i in range(8):
        ang = 2 * math.pi * i / 8
        tree.append(_leaf(i, 80 * math.cos(ang), 80 * math.sin(ang), 1))
    # One large region with two children at the centre.
    big = _leaf(100, 0.0, 0.0, 0)
    big["tags"] = []
    c1 = _leaf(101, -10.0, 0.0, 5, level=1)
    c2 = _leaf(102, 10.0, 0.0, 4, level=1)
    big["children"] = [c1, c2]
    big["aggregateCounts"] = {"tags": 9, "notes": 27, "sources": 1}
    tree.append(big)
    return {
        "version": 2, "tree": tree,
        "edges": {"regionEdges": [], "tagEdges": []},
        "highlights": {},
    }


def _hex_count_by_top(rd: dict) -> dict[int, int]:
    regs = rd["regions"]

    def top(i: int) -> int:
        while regs[i]["parentIdx"] >= 0:
            i = regs[i]["parentIdx"]
        return i

    counts: dict[int, int] = {}
    hx = rd["hexes"]
    for i in range(0, len(hx), 5):
        r = hx[i + 2]
        if r >= 0:
            t = top(r)
            counts[t] = counts.get(t, 0) + 1
    return counts


def test_bake_v3_renders_every_region_and_tag():
    terrain = _synthetic_terrain()
    rd = bake_v3(terrain)
    regs = rd["regions"]
    assert len(regs) == 11  # 8 leaves + big + 2 children
    counts = _hex_count_by_top(rd)
    tops = [i for i, r in enumerate(regs) if r["level"] == 0]
    lost = [regs[i]["name"] for i in tops if counts.get(i, 0) == 0]
    assert lost == [], f"top-level regions with zero hexes: {lost}"

    def tag_ids(node):
        for t in node.get("tags", []):
            yield t["id"]
        for c in node.get("children", []):
            yield from tag_ids(c)

    expected = {tid for n in terrain["tree"] for tid in tag_ids(n)}
    assert expected <= set(rd["tagIndex"]), expected - set(rd["tagIndex"])
    # Every leaf owns at least as many hexes as it has tags (spires need land).
    leaf_hexes = {}
    hx = rd["hexes"]
    for i in range(0, len(hx), 5):
        if hx[i + 2] >= 0:
            leaf_hexes[hx[i + 2]] = leaf_hexes.get(hx[i + 2], 0) + 1
    for i, r in enumerate(regs):
        if r["isLeaf"]:
            assert leaf_hexes.get(i, 0) >= r["tagCount"], r["name"]

    # Nested subdivision is tag-proportional: the big region's children carry
    # 5 and 4 tags, so their hex counts must be close to 5:4 (neither may be
    # squeezed out by the warp the way plain nested Voronoi allowed).
    kids = {i for i, r in enumerate(regs) if r["level"] == 1}
    assert len(kids) == 2
    a, b = sorted((leaf_hexes.get(i, 0) for i in kids), reverse=True)
    assert b > 0
    assert abs(a / b - 5 / 4) < 0.25, (a, b)
