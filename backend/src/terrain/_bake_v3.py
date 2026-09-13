"""v2 KnowledgeMap (`terrain.json`) → v3 render-data (hex model).

Pure algorithm core, vendored from the original `bake_render_data_v3.py` bake
script (the CLI driver and its debug-PNG renderers were dropped). The public
entry point lives in `render_v3.py` — `bake_v3(terrain, notes)` — which the
compiler calls to produce `.mnemify/render-data.json`. The pipeline:

    1. top-level region centroids + radii + dynamic world bounds (force-directed)
    2. recursive nested layout (sub + sub-sub regions)
    3. hex grid + warped-Voronoi leaf assignment
    4. tag placement + plateau heights + diffusion → render-data dict

Section markers below (§N) refer to the v3 render-data design note.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 7
HEX_APOTHEM = 0.5       # per §4 — distance from hex center to flat edge midpoint
                         # (smaller = denser, Kontur-style refined hex visual)
TOP_LEVEL_CENTER_MUL = 6.0   # gravity strong enough to cluster the (smaller-than-original)
                              # top-level regions tightly around the origin
OUTER_CUTOFF_MUL = 1.15      # silhouette extends 15% past nominal radius — without this,
                              # regions with radius ~70 (Products) can never cover the origin
                              # because hex packing forces centroids ≥ ~80 apart

# Rescue pass: seed leaves that own no hexes before BFS growth (see
# `expand_squeezed_leaves`). Only `scripts/bake_compare.py --baseline` turns
# this off, to reproduce the pre-fix picture on a real corpus.
SEED_ZERO_HEX_LEAVES = True

# Nested subdivision (a parent's territory split among its children) uses a
# capacity-constrained power diagram so every child gets a share of its
# parent's hexes proportional to its tag count. Plain (warped) Voronoi on the
# children's centroids handed one child almost everything whenever the warp
# gradient exceeded the sibling spacing: on a real corpus a 30-note sub-region
# kept 1 hex while a 6-note sibling kept 181, so the UI could neither hover nor
# drill into most sub-regions. False reproduces the old behaviour (for
# ``scripts/bake_compare.py --baseline``).
BALANCED_NESTED_SUBDIVISION = True
NESTED_BALANCE_ITERS = 300    # weight-adjustment iterations (converges in ~30-80)
NESTED_BALANCE_TOL = 0.05     # done when every child is within 5% (≥ 1 hex) of its share

# Layout tuning per §5 of the frontend technical plan. radius_k coefficients
# halved from {16, 8, 4} so each region's territory shrinks ~75% — combined
# with halved apothem (so each region has ~4× more hexes per area), the
# tag/filler ratio drops from ~1:12 to ~1:5.
LEVEL_PARAMS = [
    # Depth-indexed defaults. Deeper levels reuse the final entry.
    # Radii halved again so each region's nominal Voronoi territory tightly
    # hugs its tag clusters with little wasteland to threshold out.
    {"radius_k": 4.5, "warp_amp": 14.0, "reach_cap": 1.35},
    {"radius_k": 2.5, "warp_amp":  7.0, "reach_cap": 1.30},
    {"radius_k": 1.5, "warp_amp":  3.5, "reach_cap": 1.25},
]

# Heat-transfer height model (§7):
# • Tag hex clusters are pinned heat sources at the peak/cone heights.
# • Sea hexes are pinned cold sinks at 0 and act as 0-height neighbours during
#   diffusion, so edges naturally taper down (no cliffs).
# • Filler hexes start at 0 and diffuse to equilibrium — warm near tags, cold
#   near sea, near-0 in "wasteland" between clusters.
# • After diffusion, fillers below SEA_THRESHOLD revert to sea: regions
#   organically shrink to hug their tag clusters, removing wasteland fillers.
DIFFUSE_ITERS = 80       # more iterations needed for heat to reach equilibrium
DIFFUSE_ALPHA = 0.15     # stronger neighbour pull per iteration
SEA_THRESHOLD = 1.0      # filler heights below this revert to sea after diffusion
SUB_RADIUS_CLAMP = 0.40   # child radius ≤ 0.40 × parent.radius (per §5.6)
WORLD_PADDING = 1.15      # world_extent = 1.15 × max(|centroid| + radius)

# ── Semantic region layout (consume the compiler's MDS positions) ──────────
# The compiler already lays regions out semantically (layout.semantic_positions
# → every TreeNode.center). The bake consumes those `center` coords directly
# instead of re-placing regions randomly, then a light overlap-only relaxation
# clears catastrophic disc overlaps WITHOUT spreading the semantic layout.
# The compiler's layout.semantic_positions scales top-level regions to a
# radius-120 disc, which is HUGE next to bake region radii (~5-16) — left raw
# it scatters tiny islands across a vast empty desk. normalize_semantic_centers
# rescales every center uniformly so the top-level discs pack to LAYOUT_FILL of
# the map area, preserving relative (semantic) distances. V2_POS_SCALE is then a
# manual fine-tune ON TOP of that auto-normalization.
LAYOUT_FILL = 0.50           # target fraction of the map disc covered by the
                             # top-level region discs. Higher = tighter / less
                             # empty space; lower = airier. THE main density dial.
V2_POS_SCALE = 1.0           # manual fine-tune multiplier applied after auto-
                             # normalization (1.0 = pure auto; <1 tightens more).
RELAX_OVERLAP_FRACTION = 0.15  # max fraction two discs may overlap before the
                               # relaxation pass nudges them apart.
RELAX_ITERS = 80              # overlap-relaxation iterations (only overlapping
                              # pairs move, so semantic positions are preserved).
# 0.35 was tuned while the pre-2026-09-02 bake erased or shrank most regions
# (778 land hexes); with true footprints rendered (~2100) the same scale read
# as islands scattered across an empty desk. 0.50 tightens the bounding box by
# ~17% per axis on the reference corpus with no region or sub-region lost
# (renders: scripts/bake_compare.py --png).

# Force-directed parameters (per §5.1, also matches mockup_layouts.py)
FD_ITERS = 220
FD_DT = 0.04
FD_DAMP = 0.82
FD_REPULSE = 3500.0
FD_SPRING_K = 0.45
FD_REST = 165.0                 # baseline spring rest length
FD_CENTER_K = 0.004
FD_MAX_SPEED = 6.0
# Connected regions (those joined by a regionEdge) want to share a wiggly
# Voronoi border, which requires their nominal discs to OVERLAP slightly so
# the warped-Voronoi step has a working zone to bisect. We let the smaller
# disc nest 25% of its radius inside the larger one. Inverse-square repulsion
# prevents any pair from collapsing further.
FD_OVERLAP_FRACTION = 0.25      # connected pairs: rest length = sum_radii - 0.25·min_radius


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """One node in the flat regions[] array. Mirrors §9 schema."""
    id: str
    name: str
    level: int
    parent_idx: int                  # -1 for top-level
    is_leaf: bool                    # True iff has tags (no children)
    color: str
    accent: Optional[str]
    tag_count: int                   # total in subtree (matches aggregateCounts.tags)
    avg_elevation: float
    # semantic layout position from the v2 tree (compiler MDS), absolute coords:
    v2_center: tuple[float, float] = (0.0, 0.0)
    # aggregate counts carried through for the frontend region panel:
    note_count: int = 0
    source_count: int = 0
    attention_score: float = 0.0
    attention_level: str = "none"
    # populated by layout step:
    centroid: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    base_plateau_height: float = 0.0  # filled in step 5
    # original-data refs (kept for later steps, not emitted to render-data):
    children_ids: list[str] = field(default_factory=list)
    own_tags: list[dict] = field(default_factory=list)  # leaf only


def load_regions(tree: list[dict]) -> list[Region]:
    """DFS pre-order flatten of mockresults tree. Returns regions in the
    order required by the v3 schema (parents always appear before children).
    """
    flat: list[Region] = []

    def visit(node: dict, parent_idx: int):
        children = node.get("children", [])
        tags = node.get("tags", [])
        is_leaf = len(tags) > 0
        if is_leaf and children:
            raise ValueError(f"node {node['id']} has both children and tags")
        agg = node.get("aggregateCounts", {})
        avg_elev = (
            sum(t["elevation"] for t in tags) / len(tags) if tags
            else node.get("elevation", 0)
        )
        # Semantic position computed by the compiler (layout.semantic_positions).
        # Absolute world coords; default to origin for old terrain lacking it.
        center = node.get("center") or {}
        v2_center = (float(center.get("x", 0.0)), float(center.get("z", 0.0)))
        r = Region(
            id=node["id"],
            name=node["name"],
            level=node["level"],
            parent_idx=parent_idx,
            is_leaf=is_leaf,
            color=node.get("color") or (flat[parent_idx].color if parent_idx >= 0 else "#888"),
            accent=node.get("accent"),
            tag_count=agg.get("tags", len(tags)),
            avg_elevation=float(avg_elev),
            v2_center=v2_center,
            note_count=int(agg.get("notes", 0)),
            source_count=int(agg.get("sources", 0)),
            attention_score=float(node.get("attentionScore") or 0.0),
            attention_level=str(node.get("attentionLevel") or "none"),
            children_ids=[c["id"] for c in children],
            own_tags=list(tags),
        )
        flat.append(r)
        my_idx = len(flat) - 1
        for c in children:
            visit(c, my_idx)

    for top in tree:
        visit(top, -1)
    return flat


# ---------------------------------------------------------------------------
# Layout — force-directed + radius assignment (§5.1, §5.2)
# ---------------------------------------------------------------------------

def force_directed_layout(
    masses: np.ndarray,
    edges: list[tuple[int, int, float]],
    radii: Optional[np.ndarray] = None,
    seed_radius: float = 80.0,
    iters: int = FD_ITERS,
    rng_seed: int = SEED,
    bounds: Optional[tuple[float, float]] = None,
    repulse_mul: float = 1.0,
    center_mul: float = 1.0,
    angular_jitter: float = 0.0,
    rest_floor: float = FD_REST,
) -> np.ndarray:
    """Returns positions array shape (N, 2). Algorithm per §5.1.

    `masses[i]` should already be √(tagCount). `edges` is a list of
    (i, j, weight) tuples — both endpoints must be valid indices into the
    same population. `radii[i]` (optional but strongly recommended) makes
    the simulation radius-aware: spring rest lengths adapt to disc sizes
    and an additional hard-separation force prevents disc overlap.
    `bounds` is optional (max_abs_x, max_abs_z) used to clip after each step.
    """
    rng = np.random.default_rng(rng_seed)
    N = len(masses)
    if N == 0:
        return np.zeros((0, 2))
    if radii is None:
        radii = np.zeros(N)
    # seed positions in a ring sized to the disc radii (avoids starting deeply
    # overlapped, which would explode the separation force on iteration 1).
    # `angular_jitter` rotates the ring per call so different parents don't all
    # produce the same "8 o'clock big sibling" layout.
    seed_r = max(seed_radius, 1.4 * float(radii.sum() / max(N, 1)) + 40.0)
    base_angle = 0.3 + (rng.uniform(0.0, 2 * math.pi) if angular_jitter > 0 else 0.0)
    pos = np.array([
        [seed_r * math.cos(2 * math.pi * i / N + base_angle),
         seed_r * math.sin(2 * math.pi * i / N + base_angle)]
        for i in range(N)
    ], dtype=np.float64)
    pos += rng.uniform(-angular_jitter * seed_r, angular_jitter * seed_r, size=pos.shape) \
           if angular_jitter > 0 else rng.uniform(-2.0, 2.0, size=pos.shape)
    velocities = np.zeros((N, 2))

    for _ in range(iters):
        forces = np.zeros((N, 2))
        diff = pos[:, None, :] - pos[None, :, :]                 # (N,N,2)
        r2 = np.maximum((diff ** 2).sum(axis=-1), 1.0)           # (N,N)
        r = np.sqrt(r2)
        # inverse-square repulsion (overall spacing — keeps unconnected
        # regions from collapsing onto each other). Multiplier lets sub-level
        # callers scale this down so the dynamics stay self-similar at small
        # parent radii (otherwise repulsion overwhelms gravity at small r).
        m_ij = masses[:, None] * masses[None, :]                 # (N,N)
        scale = (FD_REPULSE * repulse_mul) * m_ij / (r2 * r)
        np.fill_diagonal(scale, 0.0)
        forces += (diff * scale[..., None]).sum(axis=1)
        # spring attraction along edges. Rest length adapts to disc sizes
        # so connected regions settle with a controlled overlap of their
        # nominal radii — exactly what the warped Voronoi step needs to
        # draw wiggly shared borders. Outer term lets unconnected pairs
        # reach a stable distance via repulsion only.
        for a, b, w in edges:
            d = pos[a] - pos[b]
            rab = max(math.hypot(d[0], d[1]), 1.0)
            r_small = min(radii[a], radii[b])
            rest = max(rest_floor, radii[a] + radii[b] - FD_OVERLAP_FRACTION * r_small)
            f = -FD_SPRING_K * w * (rab - rest)
            forces[a] += d / rab * f
            forces[b] -= d / rab * f
        # gentle gravity toward origin (multiplier lets sub-level callers
        # boost this so children don't pin themselves on the parent boundary)
        forces -= pos * ((FD_CENTER_K * center_mul) * masses[:, None])

        velocities = velocities * FD_DAMP + forces * FD_DT
        speed = np.linalg.norm(velocities, axis=1, keepdims=True)
        velocities = np.where(
            speed > FD_MAX_SPEED,
            velocities / np.maximum(speed, 1e-6) * FD_MAX_SPEED,
            velocities,
        )
        pos += velocities * FD_DT
        if bounds is not None:
            pos[:, 0] = np.clip(pos[:, 0], -bounds[0], bounds[0])
            pos[:, 1] = np.clip(pos[:, 1], -bounds[1], bounds[1])

    return pos


def _relax_overlaps(
    pos: list[list[float]],
    radii: list[float],
    fixed: list[tuple[float, float, float]] = (),
    iters: int = RELAX_ITERS,
    overlap_frac: float = RELAX_OVERLAP_FRACTION,
) -> None:
    """Nudge ONLY overlapping discs apart, in place.

    Unlike a force-directed sim (which repels every pair and spreads the whole
    set), this touches a pair only when it overlaps more than ``overlap_frac``
    of its combined radii — so semantically-placed, non-overlapping islands
    keep their positions. ``fixed`` are immovable peers (x, z, radius), e.g.
    already-placed regions from other parents.
    """
    n = len(pos)
    if n == 0:
        return
    for _ in range(iters):
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dz = pos[i][1] - pos[j][1]
                dist = math.hypot(dx, dz)
                allowed = (radii[i] + radii[j]) * (1.0 - overlap_frac)
                if dist >= allowed:
                    continue
                if dist <= 1e-6:
                    # coincident — separate deterministically along x
                    pos[i][0] += allowed * 0.5
                    pos[j][0] -= allowed * 0.5
                    continue
                push = (allowed - dist) * 0.5
                ux, uz = dx / dist, dz / dist
                pos[i][0] += ux * push
                pos[i][1] += uz * push
                pos[j][0] -= ux * push
                pos[j][1] -= uz * push
        for i in range(n):
            for fx, fz, fr in fixed:
                dx = pos[i][0] - fx
                dz = pos[i][1] - fz
                dist = math.hypot(dx, dz)
                allowed = (radii[i] + fr) * (1.0 - overlap_frac)
                if dist >= allowed:
                    continue
                if dist <= 1e-6:
                    pos[i][0] += allowed
                    continue
                ux, uz = dx / dist, dz / dist
                pos[i][0] += ux * (allowed - dist)
                pos[i][1] += uz * (allowed - dist)


def normalize_semantic_centers(regions: list[Region]) -> float:
    """Uniformly rescale every v2 center so top-level regions pack tightly.

    The compiler lays regions out on a radius-120 disc (great for relative
    similarity, wrong absolute scale for the hex world). We compute one global
    scale that maps the top-level spread down to a disc sized for the regions'
    actual radii (target area = Σ top-disc-areas / LAYOUT_FILL), then apply it
    to ALL centers in place — relative (semantic) distances are preserved, so
    similar regions stay adjacent; they just stop being scattered across a void.
    Returns the applied scale (1.0 when there's nothing to normalize).
    """
    tops = [r for r in regions if r.level == 0]
    if len(tops) < 2:
        return 1.0
    cx = sum(r.v2_center[0] for r in tops) / len(tops)
    cz = sum(r.v2_center[1] for r in tops) / len(tops)
    cur_extent = max(
        math.hypot(r.v2_center[0] - cx, r.v2_center[1] - cz) for r in tops
    )
    if cur_extent < 1e-6:
        return 1.0
    top_radii = [
        LEVEL_PARAMS[0]["radius_k"] * math.sqrt(max(r.tag_count, 1)) for r in tops
    ]
    target_extent = math.sqrt(
        sum(rr * rr for rr in top_radii) / max(LAYOUT_FILL, 1e-3)
    )
    scale = (target_extent / cur_extent) * V2_POS_SCALE
    for r in regions:
        r.v2_center = (r.v2_center[0] * scale, r.v2_center[1] * scale)
    return scale


def compute_world_extent(regions: list[Region]) -> float:
    """Half-extent of the world covering EVERY region disc (all levels).

    Must be called AFTER nested layout — children can sit beyond the top-level
    discs, so a top-level-only extent would clip the grid and crop islands.
    """
    if not regions:
        return 1.0
    return float(WORLD_PADDING * max(
        math.hypot(*r.centroid) + r.radius for r in regions
    ))


def assign_top_level_layout(
    regions: list[Region],
    region_edges: list[dict],
    implicit_edges: Optional[list[dict]] = None,
    implicit_weight_mul: float = 0.6,
) -> float:
    """Mutates regions[] in place: sets centroid + radius for root nodes.

    Top-level regions are placed at their compiler-computed semantic centers
    (``v2_center`` × ``V2_POS_SCALE``); a light overlap relaxation then clears
    any disc collisions without disturbing the semantic layout. ``region_edges``
    / ``implicit_edges`` are no longer used for placement (the MDS centers
    already encode inter-region similarity) — kept for signature compatibility.

    Returns a provisional world_extent; the caller should recompute it with
    ``compute_world_extent`` after nested layout (children can exceed roots).
    """
    del region_edges, implicit_edges, implicit_weight_mul  # superseded by v2_center

    top_idxs = [i for i, r in enumerate(regions) if r.level == 0]
    radii = [
        LEVEL_PARAMS[0]["radius_k"] * math.sqrt(regions[i].tag_count)
        for i in top_idxs
    ]
    # v2 centers were already globally scaled by normalize_semantic_centers.
    pos = [
        [regions[i].v2_center[0], regions[i].v2_center[1]]
        for i in top_idxs
    ]
    _relax_overlaps(pos, radii)

    for local_i, global_i in enumerate(top_idxs):
        r = regions[global_i]
        r.centroid = (round(pos[local_i][0], 3), round(pos[local_i][1], 3))
        r.radius = float(radii[local_i])

    return compute_world_extent([regions[i] for i in top_idxs])


def derive_implicit_top_level_edges(
    regions: list[Region],
    tree: list[dict],
    tag_edges: list[dict],
) -> list[dict]:
    """Aggregate cross-region tagEdges into implied top-level region attractions.

    Each cross-region tagEdge represents a semantic link between tags in two
    different top-level regions. Summing these per (rootA, rootB) pair gives
    a 'tag-magnet' attraction strength: regions whose tags talk to each
    other a lot get pulled closer in the force-directed layout.

    Returns regionEdge-shaped dicts {from, to, weight} for use alongside
    explicit regionEdges. Weight normalised to [0, 1].
    """
    tag_to_leaf: dict[str, str] = {}
    parent_of: dict[str, Optional[str]] = {}

    def walk(node: dict, par: Optional[str]):
        parent_of[node["id"]] = par
        for t in node.get("tags", []):
            tag_to_leaf[t["id"]] = node["id"]
        for c in node.get("children", []):
            walk(c, node["id"])
    for r in tree:
        walk(r, None)

    def root_id(rid: str) -> str:
        cur: Optional[str] = rid
        while parent_of.get(cur) is not None:
            cur = parent_of[cur]
        return cur

    pair_weights: dict[tuple[str, str], float] = {}
    for e in tag_edges:
        if not e.get("crossRegion"):
            continue
        la = tag_to_leaf.get(e["from"])
        lb = tag_to_leaf.get(e["to"])
        if not la or not lb:
            continue
        ra, rb = root_id(la), root_id(lb)
        if ra == rb:
            continue
        key = tuple(sorted([ra, rb]))
        pair_weights[key] = pair_weights.get(key, 0.0) + float(e["weight"])

    if not pair_weights:
        return []
    max_w = max(pair_weights.values())
    return [
        {"from": a, "to": b, "weight": min(1.0, w / max_w)}
        for (a, b), w in pair_weights.items()
    ]


def derive_sibling_edges_index(
    regions: list[Region],
    tree: list[dict],
    tag_edges: list[dict],
) -> dict[int, list[tuple[int, int, float]]]:
    """Synthesize FD edges between sibling child regions from tagEdges.

    For each tagEdge (tag_a → tag_b), find the direct children of their
    lowest-common-ancestor that contain each. Sum weights into a sparse
    parent → [(child_idx, child_idx, weight)] index. This gives every
    nested level real graph structure → asymmetric layouts that vary by
    parent rather than collapsing to symmetric polygons.
    """
    # Build helpers from the tree.
    tag_to_leaf_id: dict[str, str] = {}
    parent_of: dict[str, Optional[str]] = {}

    def walk(node: dict, parent_id: Optional[str]):
        parent_of[node["id"]] = parent_id
        for t in node.get("tags", []):
            tag_to_leaf_id[t["id"]] = node["id"]
        for c in node.get("children", []):
            walk(c, node["id"])
    for r in tree:
        walk(r, None)

    region_id_to_idx = {r.id: i for i, r in enumerate(regions)}

    def chain_to_root(rid: str) -> list[str]:
        out = []
        x: Optional[str] = rid
        while x is not None:
            out.append(x)
            x = parent_of[x]
        return out

    def child_under(node_id: str, ancestor_id: str) -> Optional[str]:
        x = node_id
        while parent_of.get(x) != ancestor_id:
            nxt = parent_of.get(x)
            if nxt is None:
                return None
            x = nxt
        return x

    # parent_global_idx → {(a_global_idx, b_global_idx): weight}
    accum: dict[int, dict[tuple[int, int], float]] = {}
    for e in tag_edges:
        la = tag_to_leaf_id.get(e["from"])
        lb = tag_to_leaf_id.get(e["to"])
        if not la or not lb or la == lb:
            continue
        chain_a = chain_to_root(la)
        chain_b_set = set(chain_to_root(lb))
        lca = next((a for a in chain_a if a in chain_b_set), None)
        if lca is None:
            continue
        ca = child_under(la, lca)
        cb = child_under(lb, lca)
        if not ca or not cb or ca == cb:
            continue
        pi = region_id_to_idx[lca]
        ai = region_id_to_idx[ca]
        bi = region_id_to_idx[cb]
        key = (min(ai, bi), max(ai, bi))
        accum.setdefault(pi, {})[key] = accum.setdefault(pi, {}).get(key, 0.0) + float(e["weight"])

    # Convert to per-parent lists with weights normalized to [0, 1].
    out: dict[int, list[tuple[int, int, float]]] = {}
    for parent_idx, pair_map in accum.items():
        max_w = max(pair_map.values()) if pair_map else 1.0
        out[parent_idx] = [
            (a, b, w / max_w) for (a, b), w in pair_map.items()
        ]
    return out


def assign_nested_layout(
    regions: list[Region],
    sibling_edges_idx: Optional[dict[int, list[tuple[int, int, float]]]] = None,
) -> None:
    """Recursively lay out children inside each non-leaf region (§5.6).

    Mutates regions[] in place: sets centroid + radius for every region with
    level ≥ 1. Containment: each child's disc is constrained to fit inside
    its parent's disc (in parent-local coordinates).
    """
    # Build parent → children index for fast traversal.
    children_of: dict[int, list[int]] = {}
    for i, r in enumerate(regions):
        if r.parent_idx >= 0:
            children_of.setdefault(r.parent_idx, []).append(i)

    # Walk parents in depth order so each
    # parent has its centroid+radius set before its children are placed.
    by_level: dict[int, list[int]] = {}
    for i, r in enumerate(regions):
        by_level.setdefault(r.level, []).append(i)

    # Track regions placed at each child level so far. When laying out a new
    # parent's children, we pass already-placed peers (same level, different
    # parent) so the placement avoids cross-parent collisions.
    placed_at_level: dict[int, list[int]] = {}

    for level in sorted(by_level.keys()):
        for parent_global_i in by_level[level]:
            child_idxs = children_of.get(parent_global_i, [])
            if not child_idxs:
                continue
            child_level = regions[parent_global_i].level + 1
            cross_peers = list(placed_at_level.get(child_level, []))
            sibling_edges = (sibling_edges_idx or {}).get(parent_global_i, [])
            _layout_children(
                regions, parent_global_i, child_idxs,
                sibling_edges, cross_parent_peers=cross_peers,
            )
            placed_at_level.setdefault(child_level, []).extend(child_idxs)


def _layout_children(
    regions: list[Region],
    parent_global_i: int,
    child_idxs: list[int],
    sibling_edges_global: list[tuple[int, int, float]],   # unused (random layout)
    cross_parent_peers: Optional[list[int]] = None,
) -> None:
    """Place children at their compiler-computed semantic positions.

    Each child sits at its v2 ``center`` (the MDS layout from
    ``layout.semantic_positions``, absolute world coords) scaled by
    ``V2_POS_SCALE``, so semantically-similar sub-regions cluster together
    rather than being scattered round-robin. A light overlap relaxation then
    nudges only the discs that actually collide — same-parent siblings and
    already-placed peers from other parents — preserving the semantic spread.
    ``sibling_edges_global`` is unused.
    """
    parent = regions[parent_global_i]
    child_level = parent.level + 1
    if child_level >= len(LEVEL_PARAMS):
        child_level = len(LEVEL_PARAMS) - 1
    params = LEVEL_PARAMS[child_level]

    raw_radii = [
        params["radius_k"] * math.sqrt(regions[i].tag_count) for i in child_idxs
    ]
    # Clamp child radius so disc fits inside parent (§5.6).
    radii = [min(r, parent.radius * SUB_RADIUS_CLAMP) for r in raw_radii]

    # Place each child at its semantic position (absolute world coords, already
    # globally scaled by normalize_semantic_centers). Similar sub-regions land
    # near each other because that's exactly what the compiler's MDS encoded.
    pos = [
        [regions[i].v2_center[0], regions[i].v2_center[1]]
        for i in child_idxs
    ]
    # Relax ONLY catastrophic overlaps — same-parent siblings plus already-
    # placed peers from other parents (treated as immovable obstacles).
    fixed = [
        (regions[p].centroid[0], regions[p].centroid[1], regions[p].radius)
        for p in (cross_parent_peers or [])
    ]
    _relax_overlaps(pos, radii, fixed=fixed)

    for k, gi in enumerate(child_idxs):
        regions[gi].centroid = (round(pos[k][0], 3), round(pos[k][1], 3))
        regions[gi].radius = float(radii[k])


# ---------------------------------------------------------------------------
# Step 4 · Hex grid generation + warped Voronoi assignment
# ---------------------------------------------------------------------------

def generate_hex_grid(world_extent: float, hex_apothem: float
                      ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pointy-top hex grid covering [-world_extent, world_extent]² in world coords.

    Pointy-top axial coords (q, r) — x runs left-right (long diagonal), z runs
    top-bottom (vertical). With apothem H:
      x = H * (2q + r)
      z = H * √3 * r
    Returns (qs, rs, xs, zs) as numpy arrays (one entry per hex inside bounds).
    """
    H = hex_apothem
    horiz_step = 2 * H              # spacing between centers in same row
    vert_step = math.sqrt(3) * H    # row-to-row spacing
    q_max = int(math.ceil(world_extent / horiz_step)) + 2
    r_max = int(math.ceil(world_extent / vert_step)) + 2

    qs, rs, xs, zs = [], [], [], []
    for r in range(-r_max, r_max + 1):
        for q in range(-q_max, q_max + 1):
            x = H * (2 * q + r)
            z = math.sqrt(3) * H * r
            if abs(x) <= world_extent and abs(z) <= world_extent:
                qs.append(q)
                rs.append(r)
                xs.append(x)
                zs.append(z)
    return (np.array(qs, dtype=np.int32),
            np.array(rs, dtype=np.int32),
            np.array(xs, dtype=np.float64),
            np.array(zs, dtype=np.float64))


HEX_NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


def build_neighbour_index(qs: np.ndarray, rs: np.ndarray) -> np.ndarray:
    """For every hex, return its 6 axial neighbours' indices as an (N, 6) int
    array. Missing neighbours are -1. Used by cleanup, expansion, and diffusion
    so we don't rebuild this lookup three times."""
    coord_to_idx = {(int(qs[i]), int(rs[i])): i for i in range(len(qs))}
    out = np.full((len(qs), 6), -1, dtype=np.int32)
    for i in range(len(qs)):
        q, r = int(qs[i]), int(rs[i])
        for k, (dq, dr) in enumerate(HEX_NEIGHBOR_OFFSETS):
            nb = coord_to_idx.get((q + dq, r + dr))
            if nb is not None:
                out[i, k] = nb
    return out


def root_of(idx: int, regions: list[Region]) -> int:
    """Walk up parentIdx to the level-0 ancestor. Returns its index in regions[]."""
    while regions[idx].parent_idx >= 0:
        idx = regions[idx].parent_idx
    return idx


def apply_warp(xs: np.ndarray, zs: np.ndarray, amp: float
               ) -> tuple[np.ndarray, np.ndarray]:
    """3-octave sin/cos position warp per §5.3. Returns warped (x, z)."""
    wx = amp * (
        np.sin(0.045 * xs) * np.cos(0.038 * zs)
        + 0.55 * np.sin(0.11 * xs + 1.0) * np.sin(0.09 * zs + 0.5)
        + 0.30 * np.cos(0.18 * xs) * np.sin(0.21 * zs)
    )
    wz = amp * (
        np.cos(0.052 * xs + 0.7) * np.sin(0.041 * zs)
        + 0.55 * np.cos(0.115 * zs) * np.sin(0.097 * xs + 1.2)
        + 0.30 * np.cos(0.16 * zs) * np.sin(0.20 * xs)
    )
    return xs + wx, zs + wz


def voronoi_assign(
    hex_xs: np.ndarray,
    hex_zs: np.ndarray,
    candidate_idxs: list[int],
    regions: list[Region],
    warp_amp: float,
    reach_cap: Optional[float] = None,
    apply_outer_cutoff: bool = True,
) -> np.ndarray:
    """Vectorized warped Voronoi: assign each hex to one of `candidate_idxs`.

    The warp is *differential*: both the hex positions AND the candidate
    centroids pass through `apply_warp`, so distances are measured between a
    warped hex and its region's warped centre. Only the *difference* of the
    warp field across a region wiggles its borders; the (locally near-constant,
    ~warp_amp-sized) shared displacement cancels. Warping hexes alone shifted
    every disc bodily by that displacement and erased any region whose radius
    was smaller than it (8/23 regions on a real corpus rendered zero hexes).

    `reach_cap`: if given, a region can only claim a hex within
        reach_cap * region.radius (UNWARPED distance).
    `apply_outer_cutoff`: if True, hex becomes -1 (sea) when the warped
        hex-to-warped-centre distance exceeds region.radius × OUTER_CUTOFF_MUL.
    Returns array of GLOBAL region indices (-1 = no claim / sea).
    """
    M = len(hex_xs)
    if M == 0 or not candidate_idxs:
        return np.full(M, -1, dtype=np.int32)

    wxs, wzs = apply_warp(hex_xs, hex_zs, warp_amp)
    cxs = np.array([regions[i].centroid[0] for i in candidate_idxs])
    czs = np.array([regions[i].centroid[1] for i in candidate_idxs])
    rads = np.array([regions[i].radius for i in candidate_idxs])
    # Warp the centres with the same field so the displacement shared by a
    # region and its own hexes cancels (see docstring).
    wcxs, wczs = apply_warp(cxs, czs, warp_amp)

    # warped d² shape (M, K)
    dx = wxs[:, None] - wcxs[None, :]
    dz = wzs[:, None] - wczs[None, :]
    warped_d2 = dx * dx + dz * dz

    if reach_cap is not None:
        ux = hex_xs[:, None] - cxs[None, :]
        uz = hex_zs[:, None] - czs[None, :]
        unwarped_d2 = ux * ux + uz * uz
        reach_d2 = (rads * reach_cap) ** 2
        warped_d2 = np.where(unwarped_d2 <= reach_d2[None, :], warped_d2, np.inf)

    best_local = np.argmin(warped_d2, axis=1)
    best_d2 = warped_d2[np.arange(M), best_local]
    global_idxs = np.array(candidate_idxs, dtype=np.int32)[best_local]

    if apply_outer_cutoff:
        owner_rad = rads[best_local] * OUTER_CUTOFF_MUL
        outside = best_d2 > owner_rad ** 2
        global_idxs = np.where(outside, -1, global_idxs)

    no_claim = np.isinf(best_d2)
    global_idxs = np.where(no_claim, -1, global_idxs)
    return global_idxs.astype(np.int32)


def balanced_subdivide(
    hex_xs: np.ndarray,
    hex_zs: np.ndarray,
    candidate_idxs: list[int],
    regions: list[Region],
    warp_amp: float,
) -> np.ndarray:
    """Split a parent's hexes among `candidate_idxs` (its children) so each
    child's hex count is proportional to its tag count.

    Capacity-constrained power diagram: a hex goes to the child minimising
    ``warped_d2 - w_child``; the additive weights start at 0 (plain warped
    Voronoi, same differential warp as :func:`voronoi_assign`) and are nudged
    up for children below their target share and down for children above it,
    with an adaptive step, until every child is within ``NESTED_BALANCE_TOL``
    (at least 1 hex) of its target or ``NESTED_BALANCE_ITERS`` runs out; the
    best assignment seen is returned. Geometry still decides *where* a child
    sits (nearest part of the parent's territory, wobbled by the warp) — the
    weights only decide *how much* it gets. Deterministic.

    Returns an array of GLOBAL region indices, one per hex (never -1: the
    parent's territory is fully subdivided).
    """
    M = len(hex_xs)
    K = len(candidate_idxs)
    if M == 0 or K == 0:
        return np.full(M, -1, dtype=np.int32)
    cands = np.array(candidate_idxs, dtype=np.int32)
    if K == 1:
        return np.full(M, cands[0], dtype=np.int32)

    wxs, wzs = apply_warp(hex_xs, hex_zs, warp_amp)
    cxs = np.array([regions[i].centroid[0] for i in candidate_idxs])
    czs = np.array([regions[i].centroid[1] for i in candidate_idxs])
    wcxs, wczs = apply_warp(cxs, czs, warp_amp)
    dx = wxs[:, None] - wcxs[None, :]
    dz = wzs[:, None] - wczs[None, :]
    d2 = dx * dx + dz * dz

    shares = np.array([max(regions[i].tag_count, 1) for i in candidate_idxs], dtype=float)
    target = shares / shares.sum() * M
    tol = np.maximum(1.0, NESTED_BALANCE_TOL * target)

    # One hex of area in d² units: raising w_i by Δ pushes i's border out by
    # ~Δ/(2·dist), so Δ ≈ err·hex_area is a border shift of about the right
    # order; the adaptive `lr` absorbs the rest.
    hex_area = 2.0 * math.sqrt(3.0) * HEX_APOTHEM ** 2
    w = np.zeros(K)
    lr = 1.0
    best_assign = np.argmin(d2, axis=1)
    best_err = float("inf")
    for _ in range(NESTED_BALANCE_ITERS):
        assign = np.argmin(d2 - w[None, :], axis=1)
        counts = np.bincount(assign, minlength=K).astype(float)
        err = target - counts
        total = float(np.abs(err).sum())
        if total < best_err:
            best_err = total
            best_assign = assign
        elif total > best_err:
            lr *= 0.7            # overshooting — damp the step
        if np.all(np.abs(err) <= tol):
            break
        w += lr * err * hex_area
    return cands[best_assign]


def expand_squeezed_leaves(
    qs: np.ndarray, rs: np.ndarray, xs: np.ndarray, zs: np.ndarray,
    owners: np.ndarray, regions: list[Region],
    max_iters: int = 12,
) -> tuple[np.ndarray, int]:
    """Ensure every leaf owns at least as many hexes as it has tags.

    A leaf can end up with fewer hexes than tags when a larger neighbour
    leaf wins the warped-Voronoi contest near a small leaf. Without enough
    hexes, some tags would have no spire to land on. Fix: each squeezed
    leaf BFS-grows by stealing the nearest non-squeezed-neighbour hex
    (preferring same top-level region's leaves to keep colour blocks
    coherent), one hex per iteration, until the deficit is closed.

    Leaves that own *zero* hexes are seeded first: BFS growth can only expand
    from an owned hex, so without a seed a fully erased leaf would be skipped
    by the very pass meant to rescue it. Seeding rules (deterministic):
      • zero-hex leaves are processed by note_count desc, then index;
      • the seed is the grid hex nearest the leaf's centroid that is sea or
        owned by a non-squeezed leaf — never one owned by another leaf in
        `needs`, and never one already seeded in this pass;
      • growth then proceeds contiguously from the seed via the BFS below.
    Seeds are counted in the returned `n_stolen`.
    """
    NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]
    coord_to_idx = {(int(qs[i]), int(rs[i])): i for i in range(len(qs))}
    owners = owners.copy()
    n_stolen = 0

    # Build needs map: leaf_idx → hexes still owed
    needs: dict[int, int] = {}
    for leaf_i, leaf in enumerate(regions):
        if not leaf.is_leaf:
            continue
        n_tags = len(leaf.own_tags)
        n_owned = int(np.sum(owners == leaf_i))
        if n_owned < n_tags:
            needs[leaf_i] = n_tags - n_owned

    if not needs:
        return owners, 0

    # Running ownership counts + the floor each leaf must keep (its tag count),
    # so neither seeding nor growth can hollow out a neighbour — in particular
    # a leaf that was just seeded and therefore no longer appears in `needs`.
    owned_count: dict[int, int] = {}
    for o in owners:
        if o >= 0:
            owned_count[int(o)] = owned_count.get(int(o), 0) + 1
    min_keep = {
        i: len(r.own_tags) for i, r in enumerate(regions) if r.is_leaf
    }

    def can_take_from(owner: int) -> bool:
        if owner < 0:
            return True                      # sea
        if owner in needs and needs[owner] > 0:
            return False                     # another squeezed leaf
        return owned_count.get(owner, 0) - 1 >= min_keep.get(owner, 0)

    # Seed zero-hex leaves (see docstring).
    zero_hex = [i for i in needs if owned_count.get(i, 0) == 0] if SEED_ZERO_HEX_LEAVES else []
    if zero_hex:
        zero_hex.sort(key=lambda i: (-regions[i].note_count, i))
        claimed: set[int] = set()
        for leaf_i in zero_hex:
            cx, cz = regions[leaf_i].centroid
            d2 = (xs - cx) ** 2 + (zs - cz) ** 2
            for hex_i in np.argsort(d2, kind="stable"):
                hex_i = int(hex_i)
                if hex_i in claimed:
                    continue
                cur = int(owners[hex_i])
                if not can_take_from(cur):
                    continue
                if cur >= 0:
                    owned_count[cur] -= 1
                owned_count[leaf_i] = owned_count.get(leaf_i, 0) + 1
                owners[hex_i] = leaf_i
                claimed.add(hex_i)
                needs[leaf_i] -= 1
                n_stolen += 1
                break
        for leaf_i in zero_hex:
            if needs.get(leaf_i, 0) <= 0:
                needs.pop(leaf_i, None)

    for _ in range(max_iters):
        if not needs:
            break
        for leaf_i in list(needs.keys()):
            if needs[leaf_i] <= 0:
                del needs[leaf_i]
                continue
            leaf = regions[leaf_i]
            cx, cz = leaf.centroid
            owned = np.where(owners == leaf_i)[0]
            best_nb = -1
            best_dist = float("inf")
            for hex_i in owned:
                q, r = int(qs[hex_i]), int(rs[hex_i])
                for dq, dr in NEIGHBOR_OFFSETS:
                    nb = coord_to_idx.get((q + dq, r + dr))
                    if nb is None:
                        continue
                    nb_owner = int(owners[nb])
                    if nb_owner == leaf_i:
                        continue
                    if nb_owner < 0:
                        continue   # don't extend silhouette into sea
                    if not can_take_from(nb_owner):
                        continue   # squeezed neighbour, or it would drop below its tag count
                    d = (float(xs[nb]) - cx) ** 2 + (float(zs[nb]) - cz) ** 2
                    if d < best_dist:
                        best_dist = d
                        best_nb = nb
            if best_nb >= 0:
                owned_count[int(owners[best_nb])] -= 1
                owned_count[leaf_i] = owned_count.get(leaf_i, 0) + 1
                owners[best_nb] = leaf_i
                needs[leaf_i] -= 1
                n_stolen += 1
                if needs[leaf_i] <= 0:
                    del needs[leaf_i]
            else:
                # No candidate: leaf is fully landlocked by sea or other
                # squeezed leaves. Give up on this one — tags will be capped.
                del needs[leaf_i]
    return owners, n_stolen


def recompute_leaf_centroids_from_voronoi(
    xs: np.ndarray, zs: np.ndarray,
    owners: np.ndarray, regions: list[Region],
) -> int:
    """Snap each leaf's centroid + radius to its actual rendered territory.

    The Step 3 layout placed centroids inside parent discs, but Voronoi can
    reassign the hex at that position to a different region (parent-overlap
    + warp). After Voronoi, a leaf's *true* centroid is the mean of the
    hexes it actually owns; its effective radius is the spread of those
    hexes. Updating both ensures Step 5 tag placement always lands inside
    the visible region.
    Returns count of leaves whose centroid moved.
    """
    moved = 0
    for i, r in enumerate(regions):
        if not r.is_leaf:
            continue
        mask = owners == i
        if not np.any(mask):
            continue        # leaf with no territory (defensive — shouldn't happen)
        ox = xs[mask]
        oz = zs[mask]
        new_cx = float(ox.mean())
        new_cz = float(oz.mean())
        d2 = (ox - new_cx) ** 2 + (oz - new_cz) ** 2
        new_radius = float(math.sqrt(d2.max()))
        old_cx, old_cz = r.centroid
        if (new_cx - old_cx) ** 2 + (new_cz - old_cz) ** 2 > 1e-4:
            moved += 1
        r.centroid = (new_cx, new_cz)
        r.radius = new_radius
    return moved


def clean_islands_and_lakes(
    qs: np.ndarray, rs: np.ndarray, owners: np.ndarray,
    max_exclave_size: int = 80,
    max_lake_size: int = 80,
) -> tuple[np.ndarray, int, int]:
    """Connected-components cleanup pass. Handles three artifacts in one go:

    1. **Breakaway islands** — a region's owned hexes split into multiple
       disconnected components (warp shoved some across a Voronoi border).
       Anything but the *largest* component for each region (under
       `max_exclave_size`) gets reassigned to the dominant neighbouring
       region (or sea if it has no land neighbours).
    2. **Interior lakes** — small clusters of sea hexes surrounded by land
       (under `max_lake_size`) get filled by the dominant neighbouring
       region. The big outer ocean (the central waterway, the surrounding
       cream sea) is left alone because it's larger than `max_lake_size`.
    3. **Solo island hexes** — special case of (1), single hex stranded
       far from its main body — same logic, just N=1.

    Returns: (cleaned owners, # exclave hexes reassigned, # lake hexes filled).
    """
    NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]
    coord_to_idx = {(int(qs[i]), int(rs[i])): i for i in range(len(qs))}
    owners = owners.copy()
    N = len(qs)

    def neighbors_of(i: int) -> list[int]:
        q, r = int(qs[i]), int(rs[i])
        out = []
        for dq, dr in NEIGHBOR_OFFSETS:
            nb = coord_to_idx.get((q + dq, r + dr))
            if nb is not None:
                out.append(nb)
        return out

    def find_components() -> list[tuple[int, list[int]]]:
        """Group hexes into (owner, [indices]) connected components."""
        visited = [False] * N
        comps: list[tuple[int, list[int]]] = []
        for start in range(N):
            if visited[start]:
                continue
            owner = int(owners[start])
            stack = [start]
            comp: list[int] = []
            while stack:
                cur = stack.pop()
                if visited[cur]:
                    continue
                if int(owners[cur]) != owner:
                    continue
                visited[cur] = True
                comp.append(cur)
                for nb in neighbors_of(cur):
                    if not visited[nb] and int(owners[nb]) == owner:
                        stack.append(nb)
            if comp:
                comps.append((owner, comp))
        return comps

    n_exclaves = 0
    n_lakes = 0

    # Iterate until stable — reassignments can create new merges that then
    # need re-evaluating (rare, but cheap to handle).
    for _ in range(4):
        comps = find_components()

        # Pass A: per-region exclaves (everything but the largest component)
        by_owner: dict[int, list[list[int]]] = {}
        for owner, comp in comps:
            by_owner.setdefault(owner, []).append(comp)

        changed = False
        for owner, owner_comps in by_owner.items():
            if owner < 0 or len(owner_comps) <= 1:
                continue
            owner_comps.sort(key=len, reverse=True)
            for exclave in owner_comps[1:]:
                if len(exclave) > max_exclave_size:
                    continue
                ext_counts: dict[int, int] = {}
                for h in exclave:
                    for nb in neighbors_of(h):
                        nbo = int(owners[nb])
                        if nbo == owner:
                            continue
                        ext_counts[nbo] = ext_counts.get(nbo, 0) + 1
                if not ext_counts:
                    continue
                new_owner = max(ext_counts.items(), key=lambda kv: kv[1])[0]
                for h in exclave:
                    owners[h] = new_owner
                n_exclaves += len(exclave)
                changed = True

        # Pass B: small sea components (interior lakes)
        for sea_comp in by_owner.get(-1, []):
            if len(sea_comp) > max_lake_size:
                continue
            ext_counts = {}
            for h in sea_comp:
                for nb in neighbors_of(h):
                    nbo = int(owners[nb])
                    if nbo < 0:
                        continue
                    ext_counts[nbo] = ext_counts.get(nbo, 0) + 1
            if not ext_counts:
                continue
            new_owner = max(ext_counts.items(), key=lambda kv: kv[1])[0]
            for h in sea_comp:
                owners[h] = new_owner
            n_lakes += len(sea_comp)
            changed = True

        if not changed:
            break

    return owners, n_exclaves, n_lakes


def assign_hexes_to_leaves(
    hex_xs: np.ndarray,
    hex_zs: np.ndarray,
    regions: list[Region],
) -> np.ndarray:
    """Recursive warped Voronoi: each hex → deepest leaf region (or -1 sea).

    1. Top-level Voronoi: hex picks among level-0 regions (with reach cap +
       outer cutoff). Hexes outside every top-level cutoff become sea.
       2. For each root region's owned hexes, subdivide by its children
       (no reach cap, no outer cutoff — full subdivision of parent territory;
       shares proportional to tag count via `balanced_subdivide`).
       3. Continue subdividing owned hexes for each deeper child level.
    Iterates until no parent has further children → owners are leaves.
    """
    children_of: dict[int, list[int]] = {}
    for i, r in enumerate(regions):
        if r.parent_idx >= 0:
            children_of.setdefault(r.parent_idx, []).append(i)

    by_level: dict[int, list[int]] = {}
    for i, r in enumerate(regions):
        by_level.setdefault(r.level, []).append(i)

    # Step 1: root assignment with cutoff & sea
    top_idxs = by_level.get(0, [])
    owners = voronoi_assign(
        hex_xs, hex_zs, top_idxs, regions,
        warp_amp=LEVEL_PARAMS[0]["warp_amp"],
        reach_cap=LEVEL_PARAMS[0]["reach_cap"],
        apply_outer_cutoff=True,
    )

    # Steps 2..N: recurse — for each parent at this level, subdivide its hexes
    # among its children. Each child level uses its own warp amplitude.
    for parent_level in sorted(by_level.keys()):
        child_level = parent_level + 1
        if child_level >= len(LEVEL_PARAMS):
            child_warp = LEVEL_PARAMS[-1]["warp_amp"]
        else:
            child_warp = LEVEL_PARAMS[child_level]["warp_amp"]
        for parent_idx in by_level[parent_level]:
            children = children_of.get(parent_idx, [])
            if not children:
                continue        # parent is itself a leaf — keep its hexes as-is
            in_territory = owners == parent_idx
            if not np.any(in_territory):
                continue
            if BALANCED_NESTED_SUBDIVISION:
                # Each child gets a tag-proportional share of the parent's hexes.
                sub_owners = balanced_subdivide(
                    hex_xs[in_territory], hex_zs[in_territory], children, regions,
                    warp_amp=child_warp,
                )
            else:
                sub_owners = voronoi_assign(
                    hex_xs[in_territory], hex_zs[in_territory], children, regions,
                    warp_amp=child_warp,
                    reach_cap=None,             # no reach cap inside parent territory
                    apply_outer_cutoff=False,   # full subdivision
                )
            owners[in_territory] = sub_owners
    return owners


# ---------------------------------------------------------------------------
# Step 5 · Tag placement, heights, render-data.json emit
# ---------------------------------------------------------------------------

MAX_PLATEAU = 10.0      # §7 — per-leaf plateau ceiling (world units)
MIN_TAG_BUMP = 3.0      # §4 — every tag spire rises at least this much above plateau
TAG_SCALE = 0.40        # §4 — tag.elevation × scale = bump above plateau (capped to ≥ MIN_TAG_BUMP).
                         # Damped from 0.7 to compress dynamic range to ~5:1 — diffusion
                         # then produces visibly merged ridges instead of looking like
                         # isolated tall columns over flat plateau.
HEXES_PER_TAG = 19      # tag claims a community cluster: 1 centre + ring 1 (6) + ring 2 (12)
                         # so each tag reads as a small mountain rather than a single column.
                         # All hexes in a tag's cluster share its tagIdx (any is clickable).
# BFS-depth-indexed height fractions for the cluster cone shape. The centre
# (depth 0) keeps the full bump; outer rings step down so the cluster has a
# clear summit + concentric base layers.
CLUSTER_DEPTH_FRACTION = {0: 1.00, 1: 0.65, 2: 0.35, 3: 0.20}

# Shore taper. Owned hexes within EDGE_FADE_DEPTH of any sea hex get pinned
# at a faded fraction of their leaf's plateau, so the silhouette tapers
# down instead of dropping like a cliff. Tag hexes are NOT faded (their
# peaks stay crisp); only filler hexes get pulled down at the shore.
EDGE_FADE_DEPTH = 3
EDGE_FADE_BY_DEPTH = {1: 0.20, 2: 0.55, 3: 0.85}
PALETTE_RAMP = ["#F2EBE0", "#E8DCE0", "#D8B0C8", "#B0407E"]
PALETTE_BG = "#F5EFE8"


def assign_tags_and_heights(
    qs: np.ndarray, rs: np.ndarray,
    xs: np.ndarray, zs: np.ndarray,
    owners: np.ndarray,
    regions: list[Region],
) -> tuple[np.ndarray, np.ndarray, list[str], dict[str, int]]:
    """Place tags into owned hexes by depth-from-centroid (§6) and set the
    INITIAL height for every owned hex. Tag hexes start at plateau + peak;
    filler hexes start at plateau (no noise). The smooth Kontur-style
    mountain look comes from `diffuse_heights` running afterwards — fillers
    iteratively absorb their neighbours' heights so peaks blend outward.

    Tag identity is stable: `tag_idx_per_hex[hex] >= 0` is the click target.
    Returns (tag_idx_per_hex, height_per_hex, tag_id_index, tag_id_to_global_idx,
             tag_recency_index).
    """
    rng = np.random.default_rng(SEED + 1234)
    N = len(qs)
    tag_idx_per_hex = np.full(N, -1, dtype=np.int32)
    height_per_hex = np.zeros(N, dtype=np.float64)
    tag_id_index: list[str] = []
    tag_id_to_global: dict[str, int] = {}
    tag_recency_index: list[float] = []     # parallel to tag_id_index

    for region_i, region in enumerate(regions):
        if not region.is_leaf:
            continue
        # §7 — per-leaf plateau
        plateau = MAX_PLATEAU * (1.0 - region.avg_elevation / 100.0)
        region.base_plateau_height = float(plateau)

        owned_indices = np.where(owners == region_i)[0]
        if len(owned_indices) == 0:
            continue
        # Heat-transfer model: fillers start at 0, diffuse warmth from tags.
        # (Tag-cluster heights below overwrite a subset of these.)
        # height_per_hex[owned_indices] stays at 0 from initialisation.

        ox = xs[owned_indices]
        oz = zs[owned_indices]
        cx, cz = region.centroid
        d = np.sqrt((ox - cx) ** 2 + (oz - cz) ** 2)
        depth = d / max(region.radius, 1e-6)

        # Sort tags by elevation descending (god tags first → claim deepest hexes)
        tags_sorted = sorted(region.own_tags, key=lambda t: -t["elevation"])
        claimed = np.zeros(len(owned_indices), dtype=bool)

        for tag in tags_sorted:
            elev = float(tag["elevation"])
            elev_norm = elev / 100.0
            target_depth = 0.78 - 0.58 * elev_norm + float(rng.uniform(-0.06, 0.06))
            target_depth = max(0.05, min(0.78, target_depth))
            scores = np.where(claimed, np.inf, np.abs(depth - target_depth))
            best_local = int(np.argmin(scores))
            if not np.isfinite(scores[best_local]):
                # Defensive: more tags than owned hexes (shouldn't happen for our data)
                continue
            claimed[best_local] = True
            best_hex = int(owned_indices[best_local])
            global_idx = len(tag_id_index)
            tag_id_index.append(tag["id"])
            tag_recency_index.append(float(tag.get("recencyScore", 0.0)))
            tag_id_to_global[tag["id"]] = global_idx
            tag_idx_per_hex[best_hex] = global_idx
            bump = max(MIN_TAG_BUMP, elev * TAG_SCALE)
            height_per_hex[best_hex] = plateau + bump

    # After centre-hex assignment, grow each tag into a small cluster so it
    # reads as a town/community peak instead of a single column. Ring hexes
    # are pinned at a fraction of the centre's bump so the centre stays a
    # clear summit (not a flat mesa).
    expand_tag_claims(qs, rs, owners, tag_idx_per_hex, height_per_hex, regions)
    return tag_idx_per_hex, height_per_hex, tag_id_index, tag_id_to_global, tag_recency_index


def expand_tag_claims(
    qs: np.ndarray, rs: np.ndarray,
    owners: np.ndarray,
    tag_idx_per_hex: np.ndarray,
    height_per_hex: np.ndarray,
    regions: list[Region],
    hexes_per_tag: int = HEXES_PER_TAG,
    depth_fraction: dict[int, float] = None,
) -> int:
    """Each tag's centre hex BFS-grows to claim up to (hexes_per_tag - 1)
    nearest unclaimed sibling hexes (same leaf). Heights step down by BFS
    depth via `depth_fraction`: depth 0 (centre) keeps full peak,
    depth 1 (ring of 6) gets ~0.65×bump, depth 2 (ring of 12) gets
    ~0.35×bump. Result: each tag is a small concentric mountain with a
    clear summit and rounded base instead of a flat-topped mesa.

    Returns total non-centre hexes added across all tag clusters.
    """
    if hexes_per_tag <= 1:
        return 0
    if depth_fraction is None:
        depth_fraction = CLUSTER_DEPTH_FRACTION
    deepest = max(depth_fraction.keys())
    fallback_frac = depth_fraction[deepest]

    nb_idx = build_neighbour_index(qs, rs)
    centres = [int(i) for i in np.where(tag_idx_per_hex >= 0)[0]]
    n_added = 0
    from collections import deque
    for centre in centres:
        tag_id = int(tag_idx_per_hex[centre])
        owner = int(owners[centre])
        plateau = float(regions[owner].base_plateau_height)
        peak = float(height_per_hex[centre])
        bump = peak - plateau
        # BFS with depth tracking. claimed: list of (hex, depth) pairs.
        claimed: list[tuple[int, int]] = [(centre, 0)]
        visited = {centre}
        queue = deque([(centre, 0)])
        while len(claimed) < hexes_per_tag and queue:
            h, d = queue.popleft()
            for k in range(6):
                nb = int(nb_idx[h, k])
                if nb < 0 or nb in visited:
                    continue
                visited.add(nb)
                if int(owners[nb]) != owner:
                    continue
                if int(tag_idx_per_hex[nb]) >= 0:
                    continue            # already claimed by another tag
                claimed.append((nb, d + 1))
                queue.append((nb, d + 1))
                if len(claimed) >= hexes_per_tag:
                    break
        for h, d in claimed[1:]:        # skip centre
            tag_idx_per_hex[h] = tag_id
            frac = depth_fraction.get(d, fallback_frac)
            height_per_hex[h] = plateau + frac * bump
            n_added += 1
    return n_added


def pin_shore_hexes(
    qs: np.ndarray, rs: np.ndarray,
    owners: np.ndarray,
    regions: list[Region],
    height_per_hex: np.ndarray,
    tag_idx_per_hex: np.ndarray,
    fade_depth: int = EDGE_FADE_DEPTH,
    fade_by_depth: dict[int, float] = None,
) -> np.ndarray:
    """BFS distance-to-sea per owned hex. Hexes within `fade_depth` of any
    sea hex (and not already a tag) get pinned at a faded fraction of
    their leaf's plateau, creating a shore ramp instead of a vertical
    cliff at the silhouette edge. Mutates `height_per_hex` in place.
    Returns a boolean mask of which hexes are now shore-pinned.
    """
    if fade_by_depth is None:
        fade_by_depth = EDGE_FADE_BY_DEPTH
    nb_idx = build_neighbour_index(qs, rs)
    N = len(qs)
    is_owned = owners >= 0
    is_sea = ~is_owned
    is_tag = tag_idx_per_hex >= 0
    dist = np.full(N, -1, dtype=np.int32)

    from collections import deque
    queue: deque[int] = deque()
    for i in range(N):
        if is_sea[i]:
            dist[i] = 0
            queue.append(i)
    while queue:
        h = queue.popleft()
        d = dist[h]
        if d >= fade_depth:
            continue
        for k in range(6):
            nb = int(nb_idx[h, k])
            if nb < 0 or dist[nb] != -1:
                continue
            dist[nb] = d + 1
            queue.append(nb)

    pin_mask = np.zeros(N, dtype=bool)
    for i in range(N):
        if not is_owned[i] or is_tag[i]:
            continue
        d = int(dist[i])
        if d <= 0 or d > fade_depth:
            continue
        plateau = float(regions[int(owners[i])].base_plateau_height)
        height_per_hex[i] = plateau * fade_by_depth.get(d, 1.0)
        pin_mask[i] = True
    return pin_mask


def diffuse_heights(
    qs: np.ndarray, rs: np.ndarray,
    owners: np.ndarray,
    height_per_hex: np.ndarray,
    tag_idx_per_hex: np.ndarray,
    regions: list[Region],
    n_iters: int = DIFFUSE_ITERS,
    alpha: float = DIFFUSE_ALPHA,
    extra_pin_mask: np.ndarray = None,
) -> np.ndarray:
    """Iterative Laplacian smoothing of the height field (§7).

    Each iteration: every non-pinned owned hex's new height =
        alpha * old_height + (1-alpha) * mean(neighbour_heights)
    where neighbours are the 6 axial neighbours that are also owned and
    belong to the SAME top-level region (no cross-region bleed) and not sea.

    Tag hexes are pinned (height fixed) so peaks don't shrink. Sea hexes
    are unaffected. Result: tag positions remain local maxima while their
    neighbours rise toward them, decaying outward — Kontur-style smooth
    mountain ranges instead of isolated columns.
    """
    N = len(qs)
    nb_idx = build_neighbour_index(qs, rs)        # (N, 6) int, -1 sentinel
    is_pinned = tag_idx_per_hex >= 0              # tag hex → keep fixed
    if extra_pin_mask is not None:
        is_pinned = is_pinned | extra_pin_mask     # also pin shore hexes
    is_owned = owners >= 0
    # Same-top-level mask: per hex, a 6-bool mask of neighbours that share root
    root_idx_of = np.full(N, -1, dtype=np.int32)
    for i in range(N):
        if is_owned[i]:
            root_idx_of[i] = root_of(int(owners[i]), regions)

    # Pre-build, for each hex i, the LIST of its valid neighbour indices.
    # Sea hexes ARE included as 0-height neighbours (cold sinks) — that's
    # how the silhouette tapers naturally to 0 at the edge. Cross-region
    # OWNED neighbours are excluded (no Products↔AEC heat bleed).
    valid_nb = np.full((N, 6), -1, dtype=np.int32)
    for i in range(N):
        if not is_owned[i]:
            continue
        my_root = root_idx_of[i]
        write_k = 0
        for k in range(6):
            nb = int(nb_idx[i, k])
            if nb < 0:
                continue
            if is_owned[nb] and root_idx_of[nb] != my_root:
                continue   # different top-level region — don't conduct heat
            # Sea (not is_owned) always counted; same-root owned counted.
            valid_nb[i, write_k] = nb
            write_k += 1

    nb_count = (valid_nb >= 0).sum(axis=1)        # (N,) ints
    h = height_per_hex.copy()

    for _ in range(n_iters):
        # Vectorised gather. Use a safe index (clamp -1 to 0) and mask.
        safe = np.where(valid_nb >= 0, valid_nb, 0)
        gathered = h[safe]                                       # (N, 6)
        gathered = np.where(valid_nb >= 0, gathered, 0.0)
        nb_sum = gathered.sum(axis=1)
        nb_mean = np.where(nb_count > 0, nb_sum / np.maximum(nb_count, 1), h)
        new_h = alpha * h + (1.0 - alpha) * nb_mean
        # Pin tag hexes and leave sea unchanged.
        new_h = np.where(is_pinned | ~is_owned, h, new_h)
        h = new_h
    return h


def build_render_data(
    qs: np.ndarray, rs: np.ndarray,
    xs: np.ndarray, zs: np.ndarray,
    owners: np.ndarray,
    tag_idx_per_hex: np.ndarray,
    height_per_hex: np.ndarray,
    tag_id_index: list[str],
    tag_id_to_global: dict[str, int],
    tag_recency_index: list[float],
    regions: list[Region],
    src: dict,
    world_extent: float,
) -> dict:
    """Assemble the final render-data.json payload per §9 schema."""
    # Bounds derived from actual hex extent (matches §9: bounds describe the
    # rendered map's extent in world coords).
    owned_mask = owners >= 0
    if owned_mask.any():
        min_x = float(xs[owned_mask].min())
        max_x = float(xs[owned_mask].max())
        min_z = float(zs[owned_mask].min())
        max_z = float(zs[owned_mask].max())
        max_y = float(height_per_hex[owned_mask].max())
    else:
        min_x = max_x = min_z = max_z = 0.0
        max_y = 0.0

    regions_out = [
        {
            "id": r.id,
            "name": r.name,
            "level": r.level,
            "parentIdx": r.parent_idx,
            "isLeaf": r.is_leaf,
            "color": r.color,
            "accent": r.accent,
            "centroid": {"x": round(r.centroid[0], 2), "z": round(r.centroid[1], 2)},
            "radius": round(r.radius, 2),
            "basePlateauHeight": round(r.base_plateau_height, 2),
            "tagCount": r.tag_count,
            "notes": r.note_count,
            "sources": r.source_count,
            "avgElevation": round(r.avg_elevation, 2),
            "attentionScore": round(r.attention_score, 2),
            "attentionLevel": r.attention_level,
        }
        for r in regions
    ]

    # Hexes: only include OWNED hexes. Schema §9 says 5 numbers per hex:
    # q, r, regionIdx, height, tagIdx.
    hexes_flat: list = []
    tag_hex_pos: dict[str, tuple[float, float, float]] = {}
    for i in range(len(qs)):
        o = int(owners[i])
        if o < 0:
            continue
        ti = int(tag_idx_per_hex[i])
        h = round(float(height_per_hex[i]), 2)
        hexes_flat.extend([int(qs[i]), int(rs[i]), o, h, ti])
        if ti >= 0:
            tag_hex_pos[tag_id_index[ti]] = (
                round(float(xs[i]), 2), round(float(zs[i]), 2), h,
            )

    # Arcs: cross-region tagEdges, tip-to-tip world coords (§9). Retained as
    # render-data because the app/data layer (indexes.ts → selectors.ts →
    # TagProvenanceDrawer) derives related-tags / crosses-into from them. The
    # 3D arc *rendering* is removed; this is the underlying co-occurrence data.
    arcs_out = []
    for e in src["edges"].get("tagEdges", []):
        if not e.get("crossRegion"):
            continue
        f, t = e["from"], e["to"]
        if f not in tag_hex_pos or t not in tag_hex_pos:
            continue
        fx, fz, fy = tag_hex_pos[f]
        tx, tz, ty = tag_hex_pos[t]
        arcs_out.append({
            "from": [fx, fz, fy],
            "to":   [tx, tz, ty],
            "weight": round(float(e["weight"]), 3),
            "fromTagId": f,
            "toTagId": t,
        })

    # Human-readable tag labels (the LLM-generated names), parallel to
    # `tagIndex`. The v2 tree carries `tags[].label`; without this the frontend
    # can only prettify the raw id (`tag.node_abc123` → "Node Abc123").
    label_by_tag_id: dict[str, str] = {}
    attention_by_tag_id: dict[str, tuple[float, str]] = {}

    def _collect_tag_labels(nodes: list[dict]) -> None:
        for node in nodes:
            for tag in node.get("tags", []) or []:
                tid = tag.get("id")
                if tid:
                    label_by_tag_id[tid] = tag.get("label") or tid
                    attention_by_tag_id[tid] = (
                        float(tag.get("attentionScore") or 0.0),
                        str(tag.get("attentionLevel") or "none"),
                    )
            _collect_tag_labels(node.get("children", []) or [])

    _collect_tag_labels(src.get("tree", []) or [])
    tag_labels_index = [label_by_tag_id.get(tid, tid) for tid in tag_id_index]
    tag_attention_score_index = [
        round(attention_by_tag_id.get(tid, (0.0, "none"))[0], 2)
        for tid in tag_id_index
    ]
    tag_attention_level_index = [
        attention_by_tag_id.get(tid, (0.0, "none"))[1]
        for tid in tag_id_index
    ]

    # Weighted many-to-many region membership, parallel to `tagIndex`. Translate
    # the v2 tag.regionWeights (region ids) into render-data regionIdx, drop any
    # that don't map to an emitted region, and sort strongest-first.
    region_id_to_idx = {r.id: i for i, r in enumerate(regions)}
    weights_by_tag_id: dict[str, list[dict]] = {}

    def _collect_tag_region_weights(nodes: list[dict]) -> None:
        for node in nodes:
            for tag in node.get("tags", []) or []:
                tid = tag.get("id")
                if not tid:
                    continue
                entries = []
                for w in tag.get("regionWeights", []) or []:
                    idx = region_id_to_idx.get(w.get("regionId"))
                    if idx is None:
                        continue
                    entries.append({
                        "regionIdx": idx,
                        "weight": round(float(w.get("weight", 0.0)), 3),
                        "isHome": bool(w.get("isHome", False)),
                    })
                entries.sort(key=lambda e: (-e["weight"], e["regionIdx"]))
                weights_by_tag_id[tid] = entries
            _collect_tag_region_weights(node.get("children", []) or [])

    _collect_tag_region_weights(src.get("tree", []) or [])
    tag_region_weights_index = [
        weights_by_tag_id.get(tid, []) for tid in tag_id_index
    ]

    src_highlights = src.get("highlights", {})
    return {
        "version": 3,
        "schemaName": "cortex.brain-map.hex",
        "generatedAt": "2026-04-30T00:00:00Z",
        "bounds": {
            "minX": round(min_x, 2), "maxX": round(max_x, 2),
            "minZ": round(min_z, 2), "maxZ": round(max_z, 2),
            "maxY": round(max_y, 2),
        },
        "palette": {"bg": PALETTE_BG, "ramp": PALETTE_RAMP},
        "hexSize": HEX_APOTHEM,
        "regions": regions_out,
        "hexes": hexes_flat,
        "tagIndex": tag_id_index,
        "tagLabels": tag_labels_index,
        "tagRecency": [round(v, 3) for v in tag_recency_index],
        "tagAttentionScore": tag_attention_score_index,
        "tagAttentionLevel": tag_attention_level_index,
        "tagRegionWeights": tag_region_weights_index,
        "arcs": arcs_out,
        "highlights": {
            "godTagIds":      src_highlights.get("godTags", []),
            "bridgeTagIds":   src_highlights.get("bridgeTags", []),
            "trendingTagIds": src_highlights.get("trendingTags", []),
        },
        "shaderParams": {
            "warpAmp": LEVEL_PARAMS[0]["warp_amp"],
            "reachCapMultiplier": LEVEL_PARAMS[0]["reach_cap"],
        },
    }
