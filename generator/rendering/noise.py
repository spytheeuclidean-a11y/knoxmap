"""Smooth value noise on coarse lattices, for anything that should clump.

Random numbers on a coarse grid, smoothstep-interpolated to every tile: blobs,
not a grid of squares. Several lattices of different cell sizes are summed by
weight, a big one for the shape and a small one for a ragged edge. The woods
on open ground (`_paint_groves`) were the first to use it; fields, pools and
rock fields use the same.
"""
from __future__ import annotations

import numpy as np


def lattices(h: int, w: int, specs, seed: int) -> list:
    """(lattice, cell, weight) for each (cell, weight) in `specs`, in order,
    all drawn from one generator seeded with `seed`."""
    rng = np.random.default_rng(seed)
    out = []
    for cell, weight in specs:
        cell = max(1, int(cell))
        out.append((rng.random((h // cell + 3, w // cell + 3), dtype=np.float32),
                    cell, weight))
    return out


def _lattice(lat, cell, ys, xs):
    fy, fx = ys / cell, xs / cell
    y0, x0 = fy.astype(int), fx.astype(int)
    ty, tx = fy - y0, fx - x0
    ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)   # smoothstep
    y1, x1 = y0 + 1, x0 + 1
    top = lat[np.ix_(y0, x0)] * (1 - tx) + lat[np.ix_(y0, x1)] * tx
    bot = lat[np.ix_(y1, x0)] * (1 - tx) + lat[np.ix_(y1, x1)] * tx
    return top * (1 - ty[:, None]) + bot * ty[:, None]


def smooth_noise(ys: np.ndarray, xs: np.ndarray, lats) -> np.ndarray:
    """The noise at rows `ys` and columns `xs` (float32 arrays of tile
    coordinates), as a (len(ys), len(xs)) array."""
    total = None
    for lat, cell, weight in lats:
        part = weight * _lattice(lat, cell, ys, xs)
        total = part if total is None else total + part
    return total
