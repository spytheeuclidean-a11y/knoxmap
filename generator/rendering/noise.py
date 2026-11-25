"""Smooth value noise on coarse lattices, for anything that should clump.

Random numbers on a coarse grid, smoothstep-interpolated to every tile: blobs,
not a grid of squares. Several lattices of different cell sizes are summed by
weight, a big one for the shape and a small one for a ragged edge. The woods
on open ground (`_paint_groves`) were the first to use it; fields, pools and
rock fields use the same.
"""
from __future__ import annotations

import functools
import threading
from contextlib import contextmanager

import numpy as np

_tls = threading.local()


def _current_offset() -> tuple[int, int] | None:
    return getattr(_tls, "offset", None)


@contextmanager
def global_tile_offset(ox: int, oy: int, extent: tuple[int, int] | None = None):
    """Shift ``smooth_noise`` sampling to global tile coordinates ``(x + ox, y + oy)``.

    ``extent`` is the ``(width, height)`` of the whole map the window belongs
    to, when the window is only a part of it (a chunk); `noise_quantiles`
    reads its cuts over that.
    """
    prev = _current_offset()
    prev_extent = getattr(_tls, "extent", None)
    _tls.offset = (int(ox), int(oy))
    _tls.extent = extent
    try:
        yield
    finally:
        _tls.offset = prev
        _tls.extent = prev_extent


def map_extent(default: tuple[int, int]) -> tuple[int, int]:
    """``(width, height)`` of the whole map: what the chunk was told, else ``default``."""
    return getattr(_tls, "extent", None) or default


def global_tile_ids(top: int, bottom: int, w: int) -> np.ndarray:
    """Per-tile ids for rows ``[top, bottom)`` of a ``w``-wide window, as int64.

    An id depends only on the tile's global ``(row, col)`` (the window offset
    from ``global_tile_offset`` included), never on ``w``, so hashing it gives
    the same value for a world tile whatever chunk it is rendered in.
    Coordinates are assumed to stay below 2**31.
    """
    return global_window_ids(top, bottom, 0, w)


def global_window_ids(y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    """`global_tile_ids` for the window ``[y0, y1) x [x0, x1)`` of the local grid."""
    return global_ids_of(np.arange(y0, y1, dtype=np.int64)[:, None],
                         np.arange(x0, x1, dtype=np.int64)[None, :])


def global_ids_of(ys, xs) -> np.ndarray:
    """Global per-tile ids for already-built local row/col arrays (broadcastable)."""
    ox, oy = _current_offset() or (0, 0)
    gy = np.asarray(ys, dtype=np.int64) + oy
    gx = np.asarray(xs, dtype=np.int64) + ox
    return (gy << 32) | gx


def global_origin() -> tuple[int, int]:
    """``(ox, oy)``: where this window starts in global tiles, ``(0, 0)`` outside a chunk."""
    return _current_offset() or (0, 0)


def aligned_start(local_lo: int, offset: int, step: int) -> int:
    """First local index at or after ``local_lo`` whose global index is a multiple of ``step``.

    Blocks laid out from here sit on the same global grid in every chunk, so a
    block is the same block whichever chunk it is drawn in.
    """
    return local_lo + (-(local_lo + offset)) % step


def block_ids(first_row: int, rows: int, first_col: int, cols: int) -> np.ndarray:
    """Ids of a ``rows`` x ``cols`` run of blocks, from their global block indices."""
    by = np.arange(first_row, first_row + rows, dtype=np.int64)[:, None]
    bx = np.arange(first_col, first_col + cols, dtype=np.int64)[None, :]
    return (by << 32) | bx


def hash01(values, salt: int) -> np.ndarray:
    """A uniform number in [0, 1) for each integer in ``values``, the same every
    run and independent of what order anything is painted in (splitmix64)."""
    values = np.asarray(values)
    with np.errstate(over="ignore"):
        z = values.astype(np.uint64) + np.uint64((salt * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


@functools.lru_cache(maxsize=64)
def _noise_quantiles(specs: tuple, seed: int, qs: tuple, width: int, height: int) -> tuple:
    n = 300
    ys = (hash01(np.arange(n), 0x51) * height).astype(np.float32)
    xs = (hash01(np.arange(n), 0x52) * width).astype(np.float32)
    with global_tile_offset(0, 0):
        values = smooth_noise(ys, xs, lattices(0, 0, specs, seed))
    return tuple(float(v) for v in np.quantile(values, qs))


def noise_quantiles(specs, seed: int, qs, window: tuple[int, int]) -> tuple:
    """The quantiles ``qs`` of the noise `lattices` draws for ``specs`` and
    ``seed`` (``((cell, weight), ...)``) over the whole map, as one number
    every chunk of the map shares. ``window`` is the ``(width, height)`` of
    the map when it is drawn whole; a chunk is told the map's size by
    `global_tile_offset` and that wins.

    A cut taken as a quantile over a chunk's own tiles moves from chunk to
    chunk, so a wood's edge or a grade's share came out differently in each.
    This reads the same quantile off scattered points of the whole map's
    noise, so no lattice can line up with the sample. It is the share of the
    map's area, not of the open ground or the wood in it: those match it
    when the ground does not follow the noise, which is not exact on a small
    map.
    """
    width, height = map_extent(window)
    return _noise_quantiles(tuple((int(c), float(w)) for c, w in specs), int(seed),
                            tuple(float(q) for q in qs), int(width), int(height))


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
    """(lattice, cell, weight) for each (cell, weight) in `specs`, in order.

    A lattice is a hash of the global tile position and `seed` (see
    `global_tile_offset`), not an array drawn for this window, so the noise
    at a tile is the same whatever window it is read through: a whole map and
    each of its chunks see one noise. `h` and `w` are kept for the callers
    that pass them and are not used."""
    ox, oy = global_origin()
    return [((int(seed), ox, oy), max(1, int(cell)), weight) for cell, weight in specs]


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
