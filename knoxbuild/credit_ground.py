"""The credit, spelled out in the ground near where a player starts.

The game has no object that shows custom text, so this is done with the ground
itself: big letters in a contrasting floor tile on a clear patch of lawn close
to the first spawn house. It is part of the compiled cells, so taking it out
means building the map again. The words come from knoxbuild/credits.py.
"""
from __future__ import annotations

import numpy as np

from generator import pz_colors as C

from . import credits

# A 3 x 5 font: rows top to bottom, '#' set. Letters and digits only; anything
# else is a gap.
_FONT = {
    "A": ("###", "# #", "###", "# #", "# #"), "B": ("## ", "# #", "## ", "# #", "## "),
    "C": ("###", "#  ", "#  ", "#  ", "###"), "D": ("## ", "# #", "# #", "# #", "## "),
    "E": ("###", "#  ", "###", "#  ", "###"), "F": ("###", "#  ", "###", "#  ", "#  "),
    "G": ("###", "#  ", "# #", "# #", "###"), "H": ("# #", "# #", "###", "# #", "# #"),
    "I": ("###", " # ", " # ", " # ", "###"), "J": ("###", "  #", "  #", "# #", "###"),
    "K": ("# #", "# #", "## ", "# #", "# #"), "L": ("#  ", "#  ", "#  ", "#  ", "###"),
    "M": ("# #", "###", "###", "# #", "# #"), "N": ("## ", "# #", "# #", "# #", "# #"),
    "O": ("###", "# #", "# #", "# #", "###"), "P": ("###", "# #", "###", "#  ", "#  "),
    "Q": ("###", "# #", "# #", "###", "  #"), "R": ("###", "# #", "## ", "# #", "# #"),
    "S": ("###", "#  ", "###", "  #", "###"), "T": ("###", " # ", " # ", " # ", " # "),
    "U": ("# #", "# #", "# #", "# #", "###"), "V": ("# #", "# #", "# #", "# #", " # "),
    "W": ("# #", "# #", "###", "###", "# #"), "X": ("# #", "# #", " # ", "# #", "# #"),
    "Y": ("# #", "# #", " # ", " # ", " # "), "Z": ("###", "  #", " # ", "#  ", "###"),
    "0": ("###", "# #", "# #", "# #", "###"), "1": (" # ", "## ", " # ", " # ", "###"),
    "2": ("###", "  #", "###", "#  ", "###"), "3": ("###", "  #", "###", "  #", "###"),
    "4": ("# #", "# #", "###", "  #", "  #"), "5": ("###", "#  ", "###", "  #", "###"),
    "6": ("###", "#  ", "###", "# #", "###"), "7": ("###", "  #", "  #", "  #", "  #"),
    "8": ("###", "# #", "###", "# #", "###"), "9": ("###", "# #", "###", "  #", "###"),
}
GLYPH_W, GLYPH_H = 3, 5
# The words, and how big each line is drawn (tiles to a font pixel).
LINES = [("KNOXMAP", 2), (f"BY {credits.MAKER.upper()}", 1)]
# What is tried, biggest first: a dense town has no lawn for the big one.
LAYOUTS = [LINES,
           [("KNOXMAP", 1), (f"BY {credits.MAKER.upper()}", 1)],
           [("KNOXMAP", 1)]]
GAP = 2                  # tiles between lines
MARGIN = 2               # clear tiles all round the lettering
MAX_DISTANCE = 400       # tiles from the spawn house the patch may be


def render_line(text: str, scale: int = 1) -> np.ndarray:
    """One line of text as a boolean bitmap, one letter space between letters."""
    cols = []
    for ch in text.upper():
        glyph = _FONT.get(ch)
        cell = np.zeros((GLYPH_H, GLYPH_W + 1), dtype=bool)
        if glyph:
            for y, row in enumerate(glyph):
                for x, c in enumerate(row):
                    cell[y, x] = c == "#"
        cols.append(cell)
    if not cols:
        return np.zeros((GLYPH_H * scale, 0), dtype=bool)
    line = np.concatenate(cols, axis=1)[:, :-1]       # no space after the last letter
    return np.kron(line, np.ones((scale, scale), dtype=bool))


def render(lines=LINES) -> np.ndarray:
    """All the lines, centred on each other, as one bitmap."""
    parts = [render_line(text, scale) for text, scale in lines]
    width = max(p.shape[1] for p in parts)
    rows = []
    for i, p in enumerate(parts):
        pad = width - p.shape[1]
        rows.append(np.pad(p, ((0, 0), (pad // 2, pad - pad // 2))))
        if i < len(parts) - 1:
            rows.append(np.zeros((GAP, width), dtype=bool))
    return np.concatenate(rows, axis=0)


def find_patch(free: np.ndarray, size: tuple[int, int], near: tuple[int, int],
               margin: int = MARGIN) -> tuple[int, int] | None:
    """The top-left (x, y) of the free rectangle of `size` (height, width), with
    `margin` clear tiles round it, nearest `near`; None when there is none."""
    h, w = free.shape
    bh, bw = size[0] + 2 * margin, size[1] + 2 * margin
    if bh > h or bw > w:
        return None
    # A summed-area table: how many free tiles in any rectangle, in one lookup.
    table = np.zeros((h + 1, w + 1), dtype=np.int32)
    table[1:, 1:] = free.astype(np.int32).cumsum(axis=0).cumsum(axis=1)
    count = (table[bh:, bw:] - table[:-bh, bw:] - table[bh:, :-bw] + table[:-bh, :-bw])
    ok = count == bh * bw
    if not ok.any():
        return None
    ys, xs = np.nonzero(ok)
    cx, cy = xs + bw / 2, ys + bh / 2
    d2 = (cx - near[0]) ** 2 + (cy - near[1]) ** 2
    best = int(np.argmin(d2))
    if d2[best] > MAX_DISTANCE ** 2:
        return None
    return int(xs[best]) + margin, int(ys[best]) + margin


def spawn_house(rows: list[dict]) -> tuple[int, int] | None:
    """The middle of the home nearest the middle of all the homes: where
    tools/make_map_mod.py's first spawn point goes."""
    homes = [r for r in rows if r.get("kind") in ("house", "apartment")]
    if not homes:
        return None
    centres = np.array([(r["tile_x"] + r["width"] / 2, r["tile_y"] + r["height"] / 2)
                        for r in homes])
    mid = centres.mean(axis=0)
    x, y = centres[int(np.argmin(((centres - mid) ** 2).sum(axis=1)))]
    return int(x), int(y)


def paint(ground: np.ndarray, veg, free: np.ndarray, rows: list[dict]) -> tuple[int, int] | None:
    """Spell the credit on a clear patch near the first spawn house; where it
    went (top-left tile), or None when the map has no room for it."""
    near = spawn_house(rows) or (free.shape[1] // 2, free.shape[0] // 2)
    for layout in LAYOUTS:
        letters = render(layout)
        at = find_patch(free, letters.shape, near)
        if at is not None:
            break
    else:
        return None
    x0, y0 = at
    ys, xs = np.nonzero(letters)
    ground[y0 + ys, x0 + xs] = C.PALE_CONCRETE
    if veg is not None:
        veg[y0 + ys, x0 + xs] = C.VEG_NOTHING
    return at
