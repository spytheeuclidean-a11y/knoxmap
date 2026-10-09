"""Writing cell sources for `knoxlots compile` (format: rust/knoxlots/SOURCE_FORMAT.md).

Squares are given as stacks of tile layers, bottom first: `layers` is a list of
(256, 256) integer arrays, one per layer, with 0 meaning no tile there and any other
number an index into `names` plus one. Several levels are a list of such lists.
"""
from __future__ import annotations

import struct

import numpy as np

SIDE = 256
NONE = 0xFFFFFFFF


def _squares(layers: list[np.ndarray]) -> np.ndarray:
    """The square records of one level, row by row, as uint32 words."""
    stack = np.stack(layers, axis=-1).reshape(SIDE * SIDE, -1)          # (squares, layers)
    present = stack > 0
    # Pack each square's tiles to the front, keeping their order.
    order = np.argsort(~present, axis=1, kind="stable")
    tiles = np.take_along_axis(stack, order, axis=1)
    k = present.sum(axis=1)
    filled = k > 0
    run_start = ~filled & np.concatenate(([True], filled[:-1]))
    # Length of each run of empty squares, at its start.
    idx = np.arange(SIDE * SIDE)
    next_filled = np.minimum.accumulate(np.where(filled, idx, SIDE * SIDE)[::-1])[::-1]
    run_len = np.where(run_start, next_filled - idx, 0)
    size = np.where(filled, 2 + k, np.where(run_start, 2, 0))
    off = np.concatenate(([0], np.cumsum(size)[:-1]))
    out = np.zeros(int(size.sum()), np.uint32)
    f = np.nonzero(filled)[0]
    out[off[f]] = (1 + k[f]).astype(np.uint32)
    out[off[f] + 1] = NONE
    for j in range(tiles.shape[1]):
        sel = f[k[f] > j]
        out[off[sel] + 2 + j] = (tiles[sel, j] - 1).astype(np.uint32)
    r = np.nonzero(run_start)[0]
    out[off[r]] = NONE
    out[off[r] + 1] = run_len[r].astype(np.uint32)
    return out


def _runs_across_levels(parts: list[np.ndarray]) -> np.ndarray:
    return np.concatenate(parts) if parts else np.zeros(0, np.uint32)


def cell_source(cell_x: int, cell_y: int, names: list[str], levels: list[list[np.ndarray]],
                min_z: int = 0, rooms=(), buildings=(), zombie: bytes | None = None) -> bytes:
    """The bytes of a `cell_<x>_<y>.kcell` file."""
    out = bytearray(b"KCEL")
    out += struct.pack("<5I", 1, cell_x, cell_y, min_z, len(levels))
    out += struct.pack("<I", len(names))
    for n in names:
        b = n.encode("utf-8")
        out += struct.pack("<H", len(b)) + b
    out += struct.pack("<I", len(rooms))
    for name, z, rects, objects in rooms:
        b = name.encode("utf-8")
        out += struct.pack("<H", len(b)) + b + struct.pack("<II", z, len(rects))
        for r in rects:
            out += struct.pack("<4I", *r)
        out += struct.pack("<I", len(objects))
        for o in objects:
            out += struct.pack("<3I", *o)
    out += struct.pack("<I", len(buildings))
    for b in buildings:
        out += struct.pack("<I", len(b)) + struct.pack(f"<{len(b)}I", *b)
    if zombie is None:
        out += b"\x00"
    else:
        assert len(zombie) == 1024
        out += b"\x01" + zombie
    # Level after level; one run of empty squares may not cross a level, as the
    # compiler counts the squares of each level exactly.
    words = _runs_across_levels([_squares(lv) for lv in levels])
    out += words.astype("<u4").tobytes()
    return bytes(out)
