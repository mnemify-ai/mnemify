"""v2 KnowledgeMap → v3 hex render-data.

Runs the v2→v3 hex-layout bake against an in-memory v2 KnowledgeMap dict and
returns the v3 render-data dict. The compiler calls this as its final step
(``TerrainCompiler._emit_render_data``). The algorithm core lives in the
sibling module :mod:`._bake_v3` (vendored from the old offline bake script);
this module is just the public entry point + the call sequence. CPU-only
(numpy + plain Python).
"""

from __future__ import annotations

import random

import numpy as np

from . import _bake_v3 as _bake


def bake_v3(terrain: dict, notes: dict | None = None, *, seed: int = _bake.SEED) -> dict:
    """Bake a v2 KnowledgeMap dict (camelCase / ``by_alias``) into a v3 hex
    render-data dict (schema ``cortex.brain-map.hex``, version 3).

    ``notes`` is accepted for forward-compat / debugging but isn't used in the
    layout — the bake reads only ``terrain``.
    """
    if terrain.get("version") != 2:
        raise ValueError(f"expected KnowledgeMap version 2, got {terrain.get('version')!r}")

    random.seed(seed)
    np.random.seed(seed)

    src = terrain
    regions = _bake.load_regions(src["tree"])
    # Rescale the compiler's radius-120 semantic layout down to the bake's world
    # scale so regions pack tightly instead of scattering across an empty desk.
    _bake.normalize_semantic_centers(regions)
    region_edges = src["edges"]["regionEdges"]
    implicit_edges = _bake.derive_implicit_top_level_edges(
        regions, src["tree"], src["edges"].get("tagEdges", [])
    )
    _bake.assign_top_level_layout(
        regions, region_edges, implicit_edges, implicit_weight_mul=1.0
    )
    _bake.assign_nested_layout(regions, sibling_edges_idx=None)
    # Recompute over ALL regions: children placed at semantic centers can sit
    # beyond the top-level discs, so a top-level-only extent would clip islands.
    world_extent = _bake.compute_world_extent(regions)

    qs, rs, xs, zs = _bake.generate_hex_grid(world_extent, _bake.HEX_APOTHEM)
    owners = _bake.assign_hexes_to_leaves(xs, zs, regions)
    owners, _exclaves, _lakes = _bake.clean_islands_and_lakes(qs, rs, owners)
    owners, _stolen = _bake.expand_squeezed_leaves(qs, rs, xs, zs, owners, regions)
    _bake.recompute_leaf_centroids_from_voronoi(xs, zs, owners, regions)

    tag_idx, height, tag_id_index, tag_id_to_global, tag_recency = (
        _bake.assign_tags_and_heights(qs, rs, xs, zs, owners, regions)
    )
    height = _bake.diffuse_heights(
        qs, rs, owners, height, tag_idx, regions,
        n_iters=_bake.DIFFUSE_ITERS, alpha=_bake.DIFFUSE_ALPHA,
    )
    cold = (owners >= 0) & (tag_idx < 0) & (height < _bake.SEA_THRESHOLD)
    owners[cold] = -1
    height[cold] = 0.0

    return _bake.build_render_data(
        qs, rs, xs, zs, owners, tag_idx, height,
        tag_id_index, tag_id_to_global, tag_recency,
        regions, src, world_extent,
    )
