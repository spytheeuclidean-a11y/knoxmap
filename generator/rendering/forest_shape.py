"""Forests with stands, thin patches and clearings, thinning to their edge.

A forest was every tile the same grade, stepped thicker or thinner all at
once by the Forests setting: a wall of trees, or a uniformly thinner one.
Here each forest tile takes its grade from a smooth noise field - blobs about
Stand size across - pulled down near the forest's edge, and the field is cut
at its own quantiles so the share of each grade is exactly what the density
asks for. Lowering the density opens clearings where the noise is lowest and
thins the edge first, rather than thinning every tile.

The woodland pass (generator/rendering/vegetation.py) draws the forest first,
natively on big maps; this re-grades it after.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from .. import pz_colors as C

FOREST_SEED = 2207
# Thinnest first: the grade is an index into this.
GRADES = (C.VEG_NOTHING, C.SPARSE_TREES, C.TREES_DARK_GRASS, C.TREES)
NAMES = ("open", "sparse", "grass", "dense")
# (density, (open, sparse, grass, dense)), linear in between.
SHARE_TABLE = (
    (0.0, (1.0, 0.0, 0.0, 0.0)),
    (0.5, (0.40, 0.25, 0.20, 0.15)),
    (1.0, (0.10, 0.15, 0.25, 0.50)),
    (2.0, (0.03, 0.07, 0.20, 0.70)),
    (3.0, (0.0, 0.0, 0.10, 0.90)),
)
EDGE_FLOOR = 0.35          # the edge's own tiles rank this low against the middle
FINE = 0.25                # weight of the small lattice that roughens the stands
SAMPLE_EVERY = 4           # the quantiles are read off every fourth tile
STRIP_ROWS = 512


def shares(density: float) -> tuple[float, float, float, float]:
    """(open, sparse, grass, dense) for a density, from SHARE_TABLE."""
    d = min(max(float(density), SHARE_TABLE[0][0]), SHARE_TABLE[-1][0])
    for (d0, s0), (d1, s1) in zip(SHARE_TABLE, SHARE_TABLE[1:]):
        if d <= d1:
            t = (d - d0) / (d1 - d0)
            return tuple(round(a + (b - a) * t, 6) for a, b in zip(s0, s1))
    return SHARE_TABLE[-1][1]


def edge_depth(forest: np.ndarray, reach: int) -> np.ndarray:
    """How many tiles in from the forest's edge each tile is, up to `reach`.
    The map's border is not an edge: the forest runs on past it."""
    depth = np.zeros(forest.shape, dtype=np.uint8)
    cur = Image.fromarray(forest.astype(np.uint8) * 255, "L")
    for _ in range(reach):
        cur = cur.filter(ImageFilter.MinFilter(3))
        inside = np.asarray(cur) > 0
        if not inside.any():
            break
        depth += inside
    return depth


def _value(ys, xs, lats, depth, reach):
    from .noise import smooth_noise

    v = smooth_noise(ys.astype(np.float32), xs.astype(np.float32), lats)
    if reach:
        d = depth[np.ix_(ys, xs)].astype(np.float32)
        v = v * (EDGE_FLOOR + (1 - EDGE_FLOOR) * np.minimum(1.0, d / reach))
    return v


def shape_forest(veg, landscape, forest, density: float, stand_m: float,
                 edge_m: float, metres_per_tile: float) -> dict:
    """Re-grade the `forest` tiles (bool, h x w) of `veg` that the woodland
    pass gave a tree grade or left empty, on ground that is not water.
    Returns tiles per grade name."""
    from .noise import lattices

    vegp = np.array(veg)
    land = np.array(landscape)
    h, w = forest.shape
    graded = np.zeros((h, w), dtype=bool)
    for c in GRADES:
        graded |= np.all(vegp == c, axis=2)
    todo = forest & graded & ~np.all(land == C.WATER, axis=2)
    if not todo.any():
        return {n: 0 for n in NAMES}

    cell = max(2, int(round(stand_m / metres_per_tile)))
    lats = lattices(h, w, [(cell, 1.0 - FINE), (max(2, cell // 4), FINE)], FOREST_SEED)
    reach = int(round(edge_m / metres_per_tile))
    depth = edge_depth(forest, reach) if reach else None

    # The cuts: quantiles of the value over the forest, so each grade gets
    # exactly its share. A share of nothing or everything is an infinite cut.
    sy = np.arange(0, h, SAMPLE_EVERY)
    sx = np.arange(0, w, SAMPLE_EVERY)
    sample = _value(sy, sx, lats, depth, reach)[todo[np.ix_(sy, sx)]]
    if sample.size == 0:
        sample = _value(np.arange(h), np.arange(w), lats, depth, reach)[todo]
    cuts, total = [], 0.0
    for share in shares(density)[:3]:
        total += share
        cuts.append(-np.inf if total <= 0 else np.inf if total >= 1
                    else float(np.quantile(sample, total)))
    cuts = np.array(cuts)

    counts = np.zeros(4, dtype=np.int64)
    colours = np.array(GRADES, dtype=np.uint8)
    xs = np.arange(w)
    for top in range(0, h, STRIP_ROWS):
        bottom = min(h, top + STRIP_ROWS)
        t = todo[top:bottom]
        if not t.any():
            continue
        v = _value(np.arange(top, bottom), xs, lats, depth, reach)
        grade = np.searchsorted(cuts, v, side="right")
        vp = vegp[top:bottom]
        vp[t] = colours[grade[t]]
        lp = land[top:bottom]
        trees = t & (grade > 0)
        lp[trees & (np.all(lp == C.MEDIUM_GRASS, axis=2)
                    | np.all(lp == C.LIGHT_GRASS, axis=2))] = C.DARK_GRASS
        counts += np.bincount(grade[t], minlength=4)
    veg.paste(Image.fromarray(vegp, "RGB"))
    landscape.paste(Image.fromarray(land, "RGB"))
    return dict(zip(NAMES, counts.tolist()))
