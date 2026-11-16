"""Smooth value noise on coarse lattices, for anything that should clump.

Random numbers on a coarse grid, smoothstep-interpolated to every tile: blobs,
not a grid of squares. Several lattices of different cell sizes are summed by
weight, a big one for the shape and a small one for a ragged edge. The woods
on open ground (`_paint_groves`) were the first to use it; fields, pools and
rock fields use the same.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

import numpy as np

_tls = threading.local()


def _current_offset() -> tuple[int, int] | None:
    return getattr(_tls, "offset", None)


@contextmanager
def global_tile_offset(ox: int, oy: int):
    """Shift ``smooth_noise`` sampling to global tile coordinates ``(x + ox, y + oy)``."""
    prev = _current_offset()
    _tls.offset = (int(ox), int(oy))
    try:
        yield
    finally:
        _tls.offset = prev


def _hash_lattice_slice(y0: int, y1: int, x0: int, x1: int,
                        cell: int, seed: int) -> np.ndarray:
    """Deterministic [0, 1) float32 lattice over global grid indices ``[y0..y1) x [x0..x1)``."""
    gy = np.arange(y0, y1, dtype=np.int64).astype(np.uint64)[:, None]
    gx = np.arange(x0, x1, dtype=np.int64).astype(np.uint64)[None, :]
    s = np.uint64((int(seed) ^ (int(cell) * 0x9E3779B97F4A7C15)) & 0xFFFFFFFFFFFFFFFF)
    h = (gy * np.uint64(0x9E3779B97F4A7C15)) ^ (gx * np.uint64(0xBF58476D1CE4E5B9)) ^ s
    h ^= h >> np.uint64(30)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(27)
    h *= np.uint64(0x94D049BB133111EB)
    h ^= h >> np.uint64(31)
    return ((h >> np.uint64(40)).astype(np.float32)) * np.float32(1.0 / (1 << 24))


def lattices(h: int, w: int, specs, seed: int) -> list:
    """(lattice, cell, weight) for each (cell, weight) in `specs`, in order,
    all drawn from one generator seeded with `seed`."""
    offset = _current_offset()
    if offset is not None:
        ox, oy = offset
        out = []
        for cell, weight in specs:
            cell = max(1, int(cell))
            out.append(((int(seed), ox, oy), cell, weight))
        return out
    rng = np.random.default_rng(seed)
    out = []
    for cell, weight in specs:
        cell = max(1, int(cell))
        out.append((rng.random((h // cell + 3, w // cell + 3), dtype=np.float32),
                    cell, weight))
    return out


def _lattice(lat, cell, ys, xs):
    if isinstance(lat, tuple):
        seed, ox, oy = lat
        fy = (ys + oy) / cell
        fx = (xs + ox) / cell
        y0 = np.floor(fy).astype(np.int64)
        x0 = np.floor(fx).astype(np.int64)
        ty, tx = fy - y0, fx - x0
        ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)
        gy_min, gx_min = int(y0.min()), int(x0.min())
        gy_max, gx_max = int(y0.max()) + 2, int(x0.max()) + 2
        grid = _hash_lattice_slice(gy_min, gy_max, gx_min, gx_max, cell, seed)
        ly0, lx0 = y0 - gy_min, x0 - gx_min
        ly1, lx1 = ly0 + 1, lx0 + 1
        top = grid[np.ix_(ly0, lx0)] * (1 - tx) + grid[np.ix_(ly0, lx1)] * tx
        bot = grid[np.ix_(ly1, lx0)] * (1 - tx) + grid[np.ix_(ly1, lx1)] * tx
        return top * (1 - ty[:, None]) + bot * ty[:, None]
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
