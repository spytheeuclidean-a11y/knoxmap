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
from PIL import Image

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
EDGE_STEPS = 8             # a wide edge is measured in about this many steps
STRIP_ROWS = 512


def shares(density: float) -> tuple[float, float, float, float]:
    """(open, sparse, grass, dense) for a density, from SHARE_TABLE."""
    d = min(max(float(density), SHARE_TABLE[0][0]), SHARE_TABLE[-1][0])
    for (d0, s0), (d1, s1) in zip(SHARE_TABLE, SHARE_TABLE[1:]):
        if d <= d1:
            t = (d - d0) / (d1 - d0)
            return tuple(round(a + (b - a) * t, 6) for a, b in zip(s0, s1))
    return SHARE_TABLE[-1][1]


def _erode(cur: np.ndarray) -> np.ndarray:
    """One step of 3 x 3 erosion, the map's border counting as forest."""
    p = np.pad(cur, 1, mode="edge")
    rows = np.minimum(np.minimum(p[:-2], p[1:-1]), p[2:])
    return np.minimum(np.minimum(rows[:, :-2], rows[:, 1:-1]), rows[:, 2:])


def edge_depth(forest: np.ndarray, reach: int) -> np.ndarray:
    """How many tiles in from the forest's edge each tile is, up to `reach`.
    The map's border is not an edge: the forest runs on past it.

    It only feeds a soft gradient, so a wide edge is measured on a coarser
    grid - blocks of `step` tiles, a block forest only if all of it is - and
    is right to within a block."""
    h, w = forest.shape
    step = max(1, reach // EDGE_STEPS)
    if step > 1:
        hh, ww = -(-h // step) * step, -(-w // step) * step
        padded = np.pad(forest, ((0, hh - h), (0, ww - w)), mode="edge")
        cur = padded.reshape(hh // step, step, ww // step, step).all(axis=(1, 3))
    else:
        cur = forest
    cur = cur.astype(np.uint8)
    depth = np.zeros(cur.shape, dtype=np.uint8)
    for _ in range(-(-reach // step)):
        cur = _erode(cur)
        if not cur.any():
            break
        depth += cur
    if step > 1:
        depth = np.minimum(depth.repeat(step, 0).repeat(step, 1)[:h, :w]
                           .astype(np.int32) * step, 255).astype(np.uint8)
    return depth


def _keys(arr: np.ndarray) -> np.ndarray:
    """Each RGB tile as one number, so a colour is one comparison."""
    return ((arr[..., 0].astype(np.uint32) << 16) | (arr[..., 1].astype(np.uint32) << 8)
            | arr[..., 2])


def _key(colour) -> int:
    return (colour[0] << 16) | (colour[1] << 8) | colour[2]


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
    vkey = _keys(vegp)
    lkey = _keys(land)
    todo = (forest & np.isin(vkey, [_key(c) for c in GRADES])
            & (lkey != _key(C.WATER)))
    del vkey
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
        lk = lkey[top:bottom]
        trees = t & (grade > 0)
        land[top:bottom][trees & ((lk == _key(C.MEDIUM_GRASS))
                                  | (lk == _key(C.LIGHT_GRASS)))] = C.DARK_GRASS
        counts += np.bincount(grade[t], minlength=4)
    veg.paste(Image.fromarray(vegp, "RGB"))
    landscape.paste(Image.fromarray(land, "RGB"))
    return dict(zip(NAMES, counts.tolist()))
