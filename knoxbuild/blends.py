"""Edge blends: overlay tiles where one kind of ground meets another (Blends.txt).

Blends.txt is a data file that ships with the mapping tools. Each rule names a ground
kind (`mainTile`), the overlay that goes on the square beside it (`blendTile`), the
direction the main ground lies in (`dir`), the layer the overlay goes on, and kinds of
ground that do not get it (`exclude`). Kinds are tiles or aliases from Rules.txt.

What the rules mean was worked out from WorldEd's own output (see tools/blend_check.py):

- A square that is not itself the main kind, not excluded and has a tile, gets the
  cardinal overlay (n, e, s, w) when the neighbour in that direction is the main kind.
- A corner overlay (nw, ne, sw, se) goes on a square whose two neighbours either side of
  that corner are both the main kind, and then replaces those two cardinal overlays.
  A main neighbour on a diagonal alone gives nothing.
- Rules share four overlay layers. Where several fit one square and layer, the one later
  in the file wins (a pothole's overlay beats a grass corner).
- Which of the overlay's tiles is used is picked from its alias by position, like any
  other tile.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .rules import Ruleset
from .terrain import Palette, mix

CARDINAL = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
CORNER = {"nw": ("n", "w"), "ne": ("n", "e"), "sw": ("s", "w"), "se": ("s", "e")}


@dataclass
class Blend:
    layer: str
    main: str
    tile: str
    dir: str
    exclude: list[str]
    exclude2: list[tuple[str, str]] = field(default_factory=list)


def parse_blends(text: str) -> list[Blend]:
    out: list[Blend] = []
    cur: dict | None = None
    lines = [ln.split("//")[0].strip() for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        s = lines[i]
        if s == "blend":
            cur = {}
        elif s == "}" and cur is not None:
            out.append(Blend(cur["layer"], cur["mainTile"], cur["blendTile"], cur["dir"],
                             cur.get("exclude", "").split(),
                             [tuple(p.split()) for p in cur.get("exclude2", [])]))
            cur = None
        elif cur is not None and "=" in s:
            k, v = (t.strip() for t in s.split("=", 1))
            if v == "[":
                items = []
                i += 1
                while i < len(lines) and lines[i] != "]":
                    if lines[i]:
                        items.append(lines[i])
                    i += 1
                cur[k] = items
            else:
                cur[k] = v
        i += 1
    return out


def load_blends(path: str) -> list[Blend]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_blends(f.read())


def _members(rules: Ruleset, pal: Palette, kind: str) -> np.ndarray:
    """Which palette entries are `kind` (a tile, or an alias of tiles). Kept on the
    palette and only extended as it grows."""
    cache = pal.__dict__.setdefault("_kinds", {})
    have = cache.get(kind)
    if have is None or len(have) < len(pal.names):
        wanted = set(rules.aliases.get(kind, [kind]))
        new = np.array([n in wanted for n in pal.names[0 if have is None else len(have):]], bool)
        have = new if have is None else np.concatenate([have, new])
        cache[kind] = have
    return have


def _neighbour(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """For every square, `mask` at the square (+dx, +dy) from it (False off the edge)."""
    h, w = mask.shape
    out = np.zeros_like(mask)
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[ys, xs] = mask[yd, xd]
    return out


def blend_layers(floor: np.ndarray, rules: Ruleset, blends: list[Blend], pal: Palette, seed: int,
                 x0: int = 0, y0: int = 0, seam: int | None = None) -> dict[str, np.ndarray]:
    """{layer: (h, w) palette numbers} of overlay tiles for a window of floor tiles.

    `floor` is (h, w) of palette numbers, 0 where there is no tile. Squares past the
    window's edge are taken to have no ground, so a window should include a one-square
    margin of its neighbours (cut away by the caller) to blend correctly at its edge.

    `seam`, if given, makes squares on either side of every multiple of that many tiles
    (300 for WorldEd) see nothing of each other, as WorldEd does when it blends each
    300 x 300 map on its own. Left out, blends run across the whole world."""
    h, w = floor.shape
    gy, gx = np.mgrid[0:h, 0:w]
    gx = gx.astype(np.int64) + x0
    gy = gy.astype(np.int64) + y0
    has_tile = floor > 0
    reach: dict[tuple[int, int], np.ndarray | None] = {}

    def look(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
        """`mask` at the neighbour (+dx, +dy), unseen across a seam."""
        out = _neighbour(mask, dx, dy)
        if seam:
            key = (dx, dy)
            if key not in reach:
                reach[key] = (gx // seam == (gx + dx) // seam) & (gy // seam == (gy + dy) // seam)
            out &= reach[key]
        return out
    layers: dict[str, np.ndarray] = {}
    main_cache: dict[str, np.ndarray] = {}
    takes_cache: dict[tuple, np.ndarray] = {}
    seen_cache: dict[tuple, np.ndarray] = {}
    for n, b in enumerate(blends):
        is_main = main_cache.get(b.main)
        if is_main is None:
            is_main = main_cache[b.main] = _members(rules, pal, b.main)[floor] & has_tile
        if not is_main.any():
            continue                          # none of this ground in the window
        tkey = (b.main, tuple(b.exclude))
        takes = takes_cache.get(tkey)
        if takes is None:
            excl_tab = np.zeros(len(pal.names), bool)
            for e in b.exclude:
                excl_tab = excl_tab | _members(rules, pal, e)[: len(pal.names)]
            takes = takes_cache[tkey] = has_tile & ~is_main & ~excl_tab[floor]

        def see(dx, dy, main=b.main, mask=is_main):
            k = (main, dx, dy)
            if k not in seen_cache:
                seen_cache[k] = look(mask, dx, dy)
            return seen_cache[k]
        if b.dir in CARDINAL:
            dx, dy = CARDINAL[b.dir]
            cond = takes & see(dx, dy)
            # dropped where a corner overlay of the same ground takes over
            for corner, (a, c) in CORNER.items():
                if b.dir in (a, c):
                    ax, ay = CARDINAL[a]
                    cx, cy = CARDINAL[c]
                    cond &= ~(see(ax, ay) & see(cx, cy))
        else:
            a, c = CORNER[b.dir]
            cond = takes & see(*CARDINAL[a]) & see(*CARDINAL[c])
        if not cond.any():
            continue
        layer = layers.setdefault(b.layer, np.zeros((h, w), np.int64))
        free = cond                          # one overlay to a layer: the last rule in the file that fits keeps it
        tiles = rules.aliases.get(b.tile, [b.tile])
        ids = np.array([pal.of(t) for t in tiles], np.int64)
        pick = (mix(gx[free], gy[free], seed * 1000003 + 5000 + n) % np.uint64(len(ids))).astype(np.int64)
        layer[free] = ids[pick]
    return layers
