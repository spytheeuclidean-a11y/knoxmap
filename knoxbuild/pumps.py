"""Fuel pumps on the forecourt of every petrol station.

A petrol station was only its shop: amenity=fuel made the building a gas
station store inside, and outside it stood in the grass with nowhere to fill a
car. Here each one gets a forecourt of tarmac on the side facing the street
and a row of the game's own pumps down the middle of it - the Fossoil and
Gas 2 Go pumps Knox County's stations have, which hold fuel (fuelAmount) and
work with a hose and a jerry can.

A station mapped only as a point, with no building around it, gets the
forecourt and pumps where the point is.

The pumps go into tile-only lots, one per map cell, like the fences and the
bridges (see structures.py).
"""
from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image

from generator import pz_colors as C

from .bitmaps import read_rgb, same_colour
from .structures import CELL, render_tiles_tbx

# One tile each, holding 20000 units of fuel. The pump facing south stands in
# a row that runs west to east, the one facing east in a row north to south.
PUMPS = {
    "fossoil": {"x": "location_shop_fossoil_01_14", "y": "location_shop_fossoil_01_12"},
    "gas2go": {"x": "location_shop_gas2go_01_14", "y": "location_shop_gas2go_01_12"},
}
FORECOURT_DEPTH = 8         # tiles out from the shop front
FORECOURT_MIN_DEPTH = 6
FORECOURT_MIN_LENGTH = 9
PUMP_SPACING = 4
FORECOURT_REACH = 6         # how much further it may run to meet the street
MAX_PUMPS = 4
# Carriageways: a forecourt stops short of the street rather than covering it.
ROAD = {C.MEDIUM_ASPHALT, C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE}
NOT_GROUND = {C.WATER}

SIDES = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}

# How a real station is laid out (the shop's side of NFPA 30A, and the
# design guides that follow it): the dispensers stand on raised islands, not
# loose on the tarmac, and no nearer a shop with windows than 5.5 m, so a
# fire at a pump does not reach the glass. Cars drive round the islands in
# lanes about 4 m wide. The shop has pavement along its front. Dimensions
# are in metres and turned into tiles by the scale of the map.
PUMP_SETBACK_M = 5.5
LANE_M = 4.0
REAR_CLEAR_M = 2.5
# One island's worth of tiles beyond the last pump at each end.
ISLAND_OVERHANG = 1
# The roof over an island, as the game's own stations have: a flat slab one
# floor up, a tile wider than the island either side, on a post at each
# corner. The slab is a pale paving tile on the floor layer of level 1 - which
# is what a flat roof is to the game - and the posts the plain pole from the
# station's own tile sheet.
CANOPY_ROOF = "floors_exterior_tilesandstone_01_3"
CANOPY_POST = "location_shop_fossoil_01_56"
CANOPY_OVERHANG = 1

# A car in the game is two tiles across and four or five long whatever the
# map's scale, so these are not allowed to shrink with it: at least this many
# tiles from the shop to the first island, from island to island, and room
# behind the last.
MIN_SETBACK_TILES = 4
MIN_LANE_TILES = 4
MIN_REAR_TILES = 2


def full_depth(metres_per_tile: float) -> int:
    """The forecourt depth that holds two islands."""
    mpt = max(0.25, metres_per_tile)
    near = max(MIN_SETBACK_TILES, int(math.ceil(PUMP_SETBACK_M / mpt)))
    lane = max(MIN_LANE_TILES, int(math.ceil(LANE_M / mpt)))
    rear = max(MIN_REAR_TILES, int(math.ceil(REAR_CLEAR_M / mpt)))
    return near + lane + 1 + rear


def island_rows(depth: int, metres_per_tile: float) -> list[int]:
    """Where the pump islands go, as tiles out from the shop front (0 is the
    row touching the shop's pavement): one at the setback, a second a lane
    further out when the forecourt is deep enough, none nearer than a tile or
    two of pavement."""
    mpt = max(0.25, metres_per_tile)
    near = max(MIN_SETBACK_TILES, int(math.ceil(PUMP_SETBACK_M / mpt)))
    lane = max(MIN_LANE_TILES, int(math.ceil(LANE_M / mpt)))
    rear = max(MIN_REAR_TILES, int(math.ceil(REAR_CLEAR_M / mpt)))
    if near + 1 + rear > depth:
        near = max(1, depth // 2)       # a shallow forecourt: as far as it goes
        return [near]
    rows = [near]
    if near + lane + 1 + rear <= depth:
        rows.append(near + lane)
    return rows


def _forecourt(x0, y0, w, h, side, depth):
    """The rectangle (x, y, width, height) in front of a footprint's side."""
    length_x = max(w, FORECOURT_MIN_LENGTH)
    length_y = max(h, FORECOURT_MIN_LENGTH)
    fx = x0 + (w - length_x) // 2
    fy = y0 + (h - length_y) // 2
    if side == "S":
        return fx, y0 + h + 1, length_x, depth
    if side == "N":
        return fx, y0 - 1 - depth, length_x, depth
    if side == "E":
        return x0 + w + 1, fy, depth, length_y
    return x0 - 1 - depth, fy, depth, length_y


def place_pumps(out_dir: str, map_name: str, bdir: str, occupied: np.ndarray,
                stations: list, points: list,
                forecourts: list | None = None,
                canopies: list | None = None,
                metres_per_tile: float = 2.0) -> tuple[list, int]:
    """Forecourts and pumps for `stations` - (x0, y0, width, height, street
    side or None) of each station's building - and `points`, (x, y) of the
    stations mapped with no building, and `canopies`, the outlines of the
    roofs mapped over forecourts. Returns (placements, pumps placed), and
    adds each forecourt (x, y, width, height) to `forecourts` when given."""
    from .world import Placement

    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    canopies = canopies or []
    if not (stations or points or canopies) or not os.path.exists(bmp):
        return [], 0
    ground = read_rgb(bmp)
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    veg = read_rgb(veg_path) if os.path.exists(veg_path) else None
    H, W = ground.shape[:2]

    blocked = occupied[:H, :W].copy()
    for colour in ROAD | NOT_GROUND:
        blocked |= same_colour(ground, colour)

    def clear(x, y, w, h):
        return (x >= 0 and y >= 0 and x + w <= W and y + h <= H
                and not blocked[y:y + h, x:x + w].any())

    tiles: list[tuple[int, int, int, str, str]] = []
    pumps = 0
    ground_free = np.ones((H, W), dtype=bool)

    paved = np.zeros((H, W), dtype=bool)
    for colour in ROAD | {C.PALE_CONCRETE, C.DARK_ASPHALT}:
        paved |= same_colour(ground, colour)

    def reach(x, y, w, h, side):
        """The forecourt run on out to the pavement or road when that is a
        few tiles further, so cars can drive onto it."""
        dx, dy = SIDES[side]
        for _ in range(FORECOURT_REACH):
            if dx:
                nx = x + w if dx > 0 else x - 1
                row = (nx, y, 1, h)
            else:
                ny = y + h if dy > 0 else y - 1
                row = (x, ny, w, 1)
            rx, ry, rw, rh = row
            if not (rx >= 0 and ry >= 0 and rx + rw <= W and ry + rh <= H):
                break
            if paved[ry:ry + rh, rx:rx + rw].any():
                return x, y, w, h
            if blocked[ry:ry + rh, rx:rx + rw].any():
                break
            if dx:
                x, w = (x, w + 1) if dx > 0 else (x - 1, w + 1)
            else:
                y, h = (y, h + 1) if dy > 0 else (y - 1, h + 1)
        return None

    def lay(x, y, w, h, brand, pumps_at=None, side=None):
        nonlocal pumps
        if forecourts is not None:
            forecourts.append((x, y, w, h))
        ground[y:y + h, x:x + w] = C.DARK_ASPHALT
        if veg is not None:
            veg[y:y + h, x:x + w] = 0
        blocked[y:y + h, x:x + w] = True
        occupied[y:y + h, x:x + w] = True
        px0, py0, pw, ph = pumps_at or (x, y, w, h)
        # Along the shop front when it is known, else along the long way.
        along_x = side in ("N", "S") if side in SIDES else pw >= ph
        length = pw if along_x else ph
        depth = ph if along_x else pw
        count = max(1, min(MAX_PUMPS, (length - 2) // PUMP_SPACING))
        start = (length - (count - 1) * PUMP_SPACING) // 2
        rows = island_rows(depth, metres_per_tile) if side in SIDES else [depth // 2]

        def at(t, d):
            """The tile `t` along the front and `d` out from the shop's side."""
            if along_x:
                return (px0 + t, py0 + (d if side != "N" else ph - 1 - d))
            return (px0 + (d if side != "W" else pw - 1 - d), py0 + t)

        def tarmac_or_concrete(tx, ty, colour):
            if 0 <= tx < W and 0 <= ty < H and ground_free[ty, tx]:
                ground[ty, tx] = colour

        # Pavement along the shop front, then each island: a strip of
        # concrete a tile past the first and last pump, the pumps standing
        # in it.
        if side in SIDES:
            for t in range(length):
                tarmac_or_concrete(*at(t, 0), C.PALE_CONCRETE)
        for d in rows:
            for t in range(start - ISLAND_OVERHANG,
                           start + (count - 1) * PUMP_SPACING + ISLAND_OVERHANG + 1):
                if 0 <= t < length:
                    tarmac_or_concrete(*at(t, d), C.PALE_CONCRETE)
            for k in range(count):
                px, py = at(start + k * PUMP_SPACING, d)
                tiles.append((px, py, 0, "Furniture", PUMPS[brand]["x" if along_x else "y"]))
                pumps += 1
            if side in SIDES:
                t0 = max(0, start - CANOPY_OVERHANG - ISLAND_OVERHANG)
                t1 = min(length - 1, start + (count - 1) * PUMP_SPACING
                         + CANOPY_OVERHANG + ISLAND_OVERHANG)
                d0, d1 = max(1, d - 1), min(depth - 1, d + 1)
                for t in range(t0, t1 + 1):
                    for dd in range(d0, d1 + 1):
                        rx, ry = at(t, dd)
                        if 0 <= rx < W and 0 <= ry < H:
                            tiles.append((rx, ry, 1, "Floor", CANOPY_ROOF))
                for t in (t0, t1):
                    for dd in (d0, d1):
                        rx, ry = at(t, dd)
                        if 0 <= rx < W and 0 <= ry < H:
                            tiles.append((rx, ry, 0, "Furniture", CANOPY_POST))

    def brand_for(x, y):
        return "fossoil" if (x * 7 + y * 13) % 2 else "gas2go"

    # Canopies first: they are where the pumps really are. The ground under
    # one becomes forecourt, and its pumps stand in one row down the middle,
    # or two when it is deep enough for cars either side of each.
    from shapely.geometry import Polygon, box
    done_near: list[tuple[float, float]] = []
    for outline in canopies:
        shape = Polygon(outline)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if shape.is_empty:
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in shape.bounds)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        cw, ch = x1 - x0, y1 - y0
        if cw < 3 or ch < 3:
            continue
        under = np.zeros((ch, cw), dtype=bool)
        for yy in range(ch):
            for xx in range(cw):
                under[yy, xx] = shape.contains(box(x0 + xx + .25, y0 + yy + .25,
                                                   x0 + xx + .75, y0 + yy + .75))
        under &= ~blocked[y0:y1, x0:x1]
        if under.sum() < 12:
            continue
        ground[y0:y1, x0:x1][under] = C.DARK_ASPHALT
        if veg is not None:
            veg[y0:y1, x0:x1][under] = 0
        along_x = cw >= ch
        depth = ch if along_x else cw
        rows = [depth // 3, depth - 1 - depth // 3] if depth >= 9 else [depth // 2]
        brand = brand_for(x0, y0)
        placed = 0
        length = cw if along_x else ch
        count = max(1, min(MAX_PUMPS, (length - 2) // PUMP_SPACING))
        step = length / count
        for r in rows:
            for k in range(count):
                t = int(step * (k + 0.5))
                xx, yy = (t, r) if along_x else (r, t)
                if under[yy, xx]:
                    tiles.append((x0 + xx, y0 + yy, 0, "Furniture", PUMPS[brand]["x" if along_x else "y"]))
                    placed += 1
        pumps += placed
        blocked[y0:y1, x0:x1] |= under
        occupied[y0:y1, x0:x1] |= under
        if forecourts is not None:
            forecourts.append((x0, y0, cw, ch))
        if placed:
            done_near.append((x0 + cw / 2, y0 + ch / 2))

    def near_canopy(x, y, reach=40):
        return any(abs(x - cx) < reach and abs(y - cy) < reach for cx, cy in done_near)

    for x0, y0, w, h, side in stations:
        if near_canopy(x0 + w / 2, y0 + h / 2):
            continue          # its pumps are under its canopy already
        order = ([side] if side in SIDES else []) + [s for s in SIDES if s != side]
        done = False
        wide = full_depth(metres_per_tile) + 1
        for depth in (wide, FORECOURT_DEPTH, FORECOURT_MIN_DEPTH):
            for s in order:
                rect = _forecourt(x0, y0, w, h, s, depth)
                if clear(*rect):
                    lay(*(reach(*rect, s) or rect), brand_for(x0, y0), pumps_at=rect, side=s)
                    done = True
                    break
            if done:
                break

    for px, py in points:
        px, py = int(px), int(py)
        if near_canopy(px, py):
            continue
        for fw, fh in ((12, FORECOURT_DEPTH), (FORECOURT_DEPTH, 12),
                       (FORECOURT_MIN_LENGTH, FORECOURT_MIN_DEPTH),
                       (FORECOURT_MIN_DEPTH, FORECOURT_MIN_LENGTH)):
            rect = (px - fw // 2, py - fh // 2, fw, fh)
            if clear(*rect):
                lay(*rect, brand_for(px, py))
                break

    if not tiles:
        return [], 0
    Image.fromarray(ground).save(bmp, format="BMP")
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
        fname = f"{map_name}_pumps_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_tiles_tbx(gw, gh, [(x - gx0, y - gy0, z, layer, tile)
                                              for x, y, z, layer, tile in group]))
        placements.append(Placement(f"buildings/{fname}", gx0, gy0, gw, gh))
    return placements, pumps
