"""The landmark silhouettes that are nobody's own feature.

A church has a steeple and a motel has a sign, and neither is drawn as an
object on OpenStreetMap: the spire is part of the nave's outline and the sign
is a detail of the business behind it. Both are put here, as tile-only lots the
way the monuments and the bridges are (knoxbuild/structures.py). The steeple is
the same solid block generator/structures.py stacks into a water tower, and the
sign is one of the game's shop signboards, the board a shop hangs a storey up,
on a post beside the road.

The rest of the skyline is not here: a water tower, a silo and a transmission
mast are mapped as their own features and generator/structures.py builds them.
"""
from __future__ import annotations

import os
import random

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.structures import BLOCK, PLINTH, POST

from . import catalog
from .bitmaps import read_rgb
from .props import ROAD, _blocked_mask, _ring
from .structures import CELL, render_tiles_tbx

LAYER = "Floor"
# The layer a shop's signboard hangs on. It is what makes a board on a post
# read as a sign rather than as a painted floor tile.
PANEL_LAYER = "WallFurniture"
# The pole the board is bolted to: fencing_01_043, the tall metal post the
# bridge piers stand on. A stack of the solid blocks the towers are built from
# reads as a concrete pillar two metres through, which is not a sign post.
POST_LAYER = "Furniture"
SIGN_POLE = POST
STEEPLE_STOREYS = 4        # over the nave of a one-storey church
STEEPLE_MAX = 7
SIGN_POST = {"motel": 2, "drive-in": 3}   # storeys of post under the board
# The signboards that are one picture across all four of their tiles. The rest
# of the family is a row of separate posters - a headline per tile - and four
# posters bolted to one post read as a rack, not as a sign. Both directions are
# here: a board faces south with the N strips and east with the W ones.
BOARD_STRIPS = {
    "N": [catalog.GAME_SIGNS["N"][2], catalog.GAME_SIGNS["N"][3]],
    "W": [catalog.GAME_SIGNS["W"][2], catalog.GAME_SIGNS["W"][3]],
}
SEARCH = 6                 # tiles out from the business to look for a run
# Without a road to face, a board is only put up close by: a motel set back
# from the street gets its sign at its own edge, not at the far end of the
# block.
FALLBACK = 3
SIGN_APART_M = 30.0        # two boards this close are one business, mapped twice
MAX_STEEPLES = 4000
MAX_SIGNS = 4000


def sign_for(tags: dict) -> str | None:
    """The sign a business puts by the road, or None.

    A drive-in is one that says so: drive_in=yes. An ordinary cinema has a
    frontage and a marquee, not a board by the road, and a board in front of
    every one of them was a town of drive-in signs.
    """
    if str(tags.get("drive_in") or "").lower() in ("yes", "true", "1"):
        return "drive-in"
    if (tags.get("tourism") or "") == "motel":
        return "motel"
    return None


def _beside(x0: int, y0: int, wide: int, tall: int, free) -> tuple[int, int] | None:
    """A free square touching a building, the one nearest its middle first.

    A steeple stands against the nave, not across the road from it, so the ring
    immediately around the building is tried before anything two or three
    squares out.
    """
    cx, cy = x0 + (wide - 1) / 2, y0 + (tall - 1) / 2
    for distance in range(1, SEARCH + 1):
        candidates = [(x, y) for x, y in _ring(x0, y0, wide, tall, distance)
                      if free(x, y)]
        if candidates:
            return min(candidates, key=lambda p: ((p[0] - cx) ** 2 + (p[1] - cy) ** 2,
                                                 p[1], p[0]))
    return None


def _faces_road(cells, ground, width: int, height: int, along_x: bool) -> bool:
    """True when a road runs along one side of these squares, so a sign there
    is read from the street and not from somebody's back garden."""
    for x, y in cells:
        for step in (-1, 1):
            nx, ny = (x, y + step) if along_x else (x + step, y)
            if 0 <= nx < width and 0 <= ny < height and tuple(ground[ny, nx]) in ROAD:
                return True
    return False


def _sign_run(box_: tuple[int, int, int, int], length: int, free, ground,
              width: int, height: int, need_road: bool = True,
              reach: int = SEARCH):
    """The nearest free run of `length` squares for a board, and its direction.

    The run starts on a ring around the business itself - the first ring that
    has one wins - so a board stands at the edge of the lot however wide the
    lot is, and never at the far end of the block. A run with the road along
    one side is taken first: a sign is read from the street.
    """
    x0, y0, x1, y1 = box_
    wide, tall = x1 - x0 + 1, y1 - y0 + 1
    for distance in range(1, reach + 1):
        best = None
        for sx, sy in _ring(x0, y0, wide, tall, distance):
            for along_x in (True, False):
                cells = ([(sx + k, sy) for k in range(length)] if along_x
                         else [(sx, sy + k) for k in range(length)])
                if not all(free(x, y) for x, y in cells):
                    continue
                if need_road and not _faces_road(cells, ground, width, height, along_x):
                    continue
                if best is None:
                    best = (cells, "N" if along_x else "W")
        if best is not None:
            return best
    return (None, None)


def place_landmarks(out_dir: str, map_name: str, bdir: str, occupied: np.ndarray,
                    rows: list, businesses: list, metres_per_tile: float = 2.0,
                    seed: int = 0x1A4D) -> tuple[list, dict]:
    """A steeple on every church and a sign at every motel and drive-in.

    `businesses` is [(x0, y0, x1, y1, "motel" | "drive-in")], the footprint of
    each place in map tiles (a point feature is a one-tile box): the places
    that put a board up, found by knoxbuild/build.py in what the map itself
    says.

    Returns (placements, counts). Squares already taken by a building, a road
    or water are left alone, and the trees under what is put down are cleared,
    as the headstones in knoxbuild/props.py do.
    """
    from .world import Placement

    counts = {"steeples": 0, "signs": 0, "motel_signs": 0, "drive_in_signs": 0}
    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(bmp) or occupied is None:
        return [], counts
    ground = read_rgb(bmp)
    height, width = ground.shape[:2]
    blocked = _blocked_mask(ground) | occupied[:height, :width]
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    veg = read_rgb(veg_path) if os.path.exists(veg_path) else None
    rng = random.Random(seed)
    apart = max(4, int(round(SIGN_APART_M / max(0.05, metres_per_tile))))
    tiles: list[tuple[int, int, int, str, str]] = []
    taken: set = set()

    def free(x: int, y: int) -> bool:
        return (0 <= x < width and 0 <= y < height
                and not blocked[y, x] and (x, y) not in taken)

    def put(x: int, y: int, z: int, layer: str, tile: str) -> None:
        taken.add((x, y))
        tiles.append((x, y, z, layer, tile))
        if veg is not None:
            veg[y, x] = C.VEG_NOTHING

    for row in rows or []:
        if counts["steeples"] >= MAX_STEEPLES:
            break
        if row.get("kind") != "church":
            continue
        square = _beside(int(row["tile_x"]), int(row["tile_y"]),
                         int(row["width"]), int(row["height"]), free)
        if square is None:
            continue
        sx, sy = square
        storeys = min(STEEPLE_MAX, max(STEEPLE_STOREYS,
                                       int(row.get("levels", 1)) + 2))
        for z in range(storeys):
            put(sx, sy, z, LAYER, BLOCK)
        put(sx, sy, storeys, LAYER, PLINTH)     # the finial, a point on the needle
        counts["steeples"] += 1

    placed_boards: list[tuple[str, int, int]] = []
    for x0, y0, x1, y1, what in sorted(set(businesses or [])):
        if counts["signs"] >= MAX_SIGNS:
            break
        px, py = (x0 + x1) // 2, (y0 + y1) // 2
        # One board per business. A motel is often mapped twice - the outline
        # and a point inside it - and a board at each is two signs in front of
        # one motel.
        if any(kind == what and abs(bx - px) <= apart and abs(by - py) <= apart
               for kind, bx, by in placed_boards):
            continue
        strip = list(rng.choice(BOARD_STRIPS["N"]))   # read along x, facing south
        box_ = (x0, y0, x1, y1)
        cells, direction = _sign_run(box_, len(strip), free, ground, width, height)
        if cells is None:
            cells, direction = _sign_run(box_, len(strip), free, ground, width, height,
                                         need_road=False, reach=FALLBACK)
        if cells is None:
            continue
        if direction == "W":
            # The same board turned to face east: its tiles read along y.
            strip = list(rng.choice(BOARD_STRIPS["W"]))
        post = SIGN_POST[what]
        cx, cy = cells[len(cells) // 2]
        # The board goes up on all of its squares, the post's included: the
        # post rises through it to hold it, and a board with a tile missing is
        # half a word.
        for (tx, ty), tile in zip(cells, strip):
            taken.add((tx, ty))
            tiles.append((tx, ty, post, PANEL_LAYER, tile))
            if veg is not None:
                veg[ty, tx] = C.VEG_NOTHING
        # The pole runs one storey above the board, so the board hangs on it
        # rather than floating over its top: a post stops at the bottom of the
        # board, and the board is read against the length of pole behind it.
        for z in range(post + 1):
            put(cx, cy, z, POST_LAYER, SIGN_POLE)
        placed_boards.append((what, px, py))
        counts["signs"] += 1
        counts[f"{what.replace('-', '_')}_signs"] += 1

    if not tiles:
        return [], counts
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")

    by_cell: dict[tuple[int, int], list] = {}
    for t in tiles:
        by_cell.setdefault((t[0] // CELL, t[1] // CELL), []).append(t)
    placements = []
    for (cx, cy), group in sorted(by_cell.items()):
        gx0 = min(t[0] for t in group)
        gy0 = min(t[1] for t in group)
        gw = max(t[0] for t in group) - gx0 + 1
        gh = max(t[1] for t in group) - gy0 + 1
        fname = f"{map_name}_landmarks_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_tiles_tbx(gw, gh, [(x - gx0, y - gy0, z, layer, tile)
                                              for x, y, z, layer, tile in group]))
        placements.append(Placement(f"buildings/{fname}", gx0, gy0, gw, gh))
    return placements, counts
