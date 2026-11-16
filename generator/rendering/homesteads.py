"""Room around a building: no field or water under it, a clearing in the woods.

A house mapped in a wood stood in the trees up to its walls, and nothing led
to it: the woods were painted over its yard and its drive. A house on ground
WorldCover calls cropland or water stood in a ploughed field or a lake, since
the 10 m grid does not know the farmyard is there.

Here every building keeps a small yard clear of fields and water, and a
building with woods around it gets a clearing of its own - 10 to 30 m out from
its walls, never a neat ring - thinning into the trees at its edge, and a
gently bent drive to the nearest road. The drive is dark tarmac, which is what
knoxbuild's own drives are (knoxbuild/yards.py), so a house's front path stops
at it rather than running beside it to the street.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from .. import pz_colors as C
from .fields import _hash01

YARD_M = 6.0                   # no field or water this near a building
YARD_CLASSES = (40, 80)        # WorldCover cropland and water
# How far a clearing runs out from the walls. It was 10-30 m, which in a town
# took the belts of trees between the houses: they are narrow, and every house
# beside one got a clearing as wide as the belt.
CLEAR_M = (8.0, 20.0)
WOBBLE = 0.35                  # ...varying this much round the building
EDGE_M = 4.0                   # the thinned fringe past it
EDGE_THIN = 0.5                # of the fringe's trees, the share stepped down
# Of a clearing's ground, the woods it needs to get one: a house in the woods,
# not a house in town with a tree belt along one side of its yard.
IN_WOODS = 0.5
DRIVE_MIN_M2 = 40.0            # sheds and garages get no drive of their own
DRIVE_MAX_M = 400.0
DRIVE_MIN_TILES = 3            # a road this close is the drive already
DRIVE_WIDTH = 3
DRIVE_BEND = 0.2               # the bend, as a share of the drive's length
DRIVE_SHARE_M = 10.0           # a drive this near a building serves it too
HOME_SEED = 5381

# What a clearing takes away: the woods, not a garden's flowers or a field.
WOODS = (C.TREES, C.TREES_DARK_GRASS, C.SPARSE_TREES, C.TREE_SMALL,
         C.LOT_OF_GRASS_AND_TREES, C.BUSHES_TREES_DARK_GRASS, C.BUSHES,
         C.DENSE_BUSHES_GRASS, C.TREE_BIG, C.TREE_HUGE, C.TREE_GIANT)
# One grade thinner, for the fringe.
THINNER = {C.TREES: C.TREES_DARK_GRASS, C.TREES_DARK_GRASS: C.SPARSE_TREES,
           C.LOT_OF_GRASS_AND_TREES: C.SPARSE_TREES,
           C.BUSHES_TREES_DARK_GRASS: C.BUSHES}
# Ground a drive may be laid on: grass, dirt and fields, never a road or water.
DRIVE_GROUND = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DIRT,
                C.DIRT_ROWS_H, C.DIRT_ROWS_V)


def footprint_mask(footprints, size) -> np.ndarray:
    """Bool (h, w), True inside any footprint (pixel rings)."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for ring in footprints:
        if len(ring) >= 3:
            draw.polygon([tuple(p) for p in ring], fill=255)
    return np.asarray(mask) > 0


def keep_yards_clear(landscape, grid, owned, footprints, meters_per_tile) -> np.ndarray:
    """Turn WorldCover cropland and water under a building, or within its
    yard, into lawn, and take it out of `owned` (in place). Returns the yards
    (bool), which OSM farmland is kept off as well."""
    from .vegetation import _box_any

    size = landscape.size
    yards = _box_any(footprint_mask(footprints, size),
                     max(1, int(round(YARD_M / meters_per_tile))))
    if grid is None or owned is None:
        return yards
    lawn = yards & owned & np.isin(grid, YARD_CLASSES)
    if lawn.any():
        land = np.array(landscape)
        land[lawn] = C.MEDIUM_GRASS
        landscape.paste(Image.fromarray(land, "RGB"))
        owned &= ~lawn
    return yards


def _is_woods(arr) -> np.ndarray:
    out = np.zeros(arr.shape[:2], dtype=bool)
    for colour in WOODS:
        out |= np.all(arr == colour, axis=2)
    return out


def _wobbly(poly, radius: float, seed: int, extra: float = 0.0):
    """`poly` grown by about `radius`, more on some sides than others: each
    point of the plain buffer is pushed out or in along its way from the
    walls by a few smooth waves round the building."""
    from shapely.geometry import Point, Polygon

    rng = np.random.default_rng(seed)
    waves = [(k, rng.uniform(0.3, 1.0), rng.uniform(0, 2 * math.pi)) for k in (2, 3, 5)]
    norm = sum(a for _k, a, _p in waves)
    plain = poly.buffer(radius, quad_segs=8)
    if plain.geom_type != "Polygon":
        plain = max(plain.geoms, key=lambda g: g.area)
    ring = plain.exterior.segmentize(2.0)
    cx, cy = poly.centroid.x, poly.centroid.y
    out = []
    for x, y in ring.coords:
        theta = math.atan2(y - cy, x - cx)
        wave = sum(a * math.sin(k * theta + p) for k, a, p in waves) / norm
        reach = radius * (1.0 + WOBBLE * wave) + extra
        q = poly.exterior.interpolate(poly.exterior.project(Point(x, y)))
        dx, dy = x - q.x, y - q.y
        d = math.hypot(dx, dy) or 1.0
        out.append((q.x + dx / d * reach, q.y + dy / d * reach))
    shape = Polygon(out)
    return shape if shape.is_valid else shape.buffer(0)


def _rasterise(shape, x0, y0, w, h) -> np.ndarray:
    if w <= 0 or h <= 0:
        return np.zeros((max(0, h), max(0, w)), dtype=bool)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    polys = [shape] if shape.geom_type == "Polygon" else list(getattr(shape, "geoms", []))
    for p in polys:
        if p.geom_type == "Polygon" and not p.is_empty:
            draw.polygon([(x - x0, y - y0) for x, y in p.exterior.coords], fill=255)
    return np.asarray(mask) > 0


def _bezier(p, q, bend: float, step: float = 1.0):
    """Points along a gentle curve from p to q, bowed sideways by `bend` of
    its length."""
    (px, py), (qx, qy) = p, q
    length = math.hypot(qx - px, qy - py)
    nx, ny = -(qy - py) / (length or 1.0), (qx - px) / (length or 1.0)
    cx = (px + qx) / 2 + nx * bend * length
    cy = (py + qy) / 2 + ny * bend * length
    n = max(2, int(length / step) + 1)
    t = np.linspace(0.0, 1.0, n)
    xs = (1 - t) ** 2 * px + 2 * (1 - t) * t * cx + t ** 2 * qx
    ys = (1 - t) ** 2 * py + 2 * (1 - t) * t * cy + t ** 2 * qy
    return list(zip(xs.tolist(), ys.tolist()))


def clear_homesteads(veg, landscape, footprints, roads, meters_per_tile,
                     clear_max_m: float = CLEAR_M[1]) -> tuple[np.ndarray, dict]:
    """Clearings and drives for buildings standing in woods.

    `footprints` are pixel rings, `roads` pixel polylines (the roads a drive
    may join). Returns the tiles cleared or paved (bool), for the planting
    passes after this to leave alone, and counts.

    clear_max_m: how far a clearing reaches from the walls at most (House
    clearings); the near end is CLEAR_M's ratio of it, 0 is none."""
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree

    w, h = landscape.size
    land = np.array(landscape)
    vegp = np.array(veg)
    done = np.zeros((h, w), dtype=bool)
    counts = {"clearings": 0, "drives": 0}
    if clear_max_m <= 0:
        return done, counts
    clear_min_m = clear_max_m * CLEAR_M[0] / CLEAR_M[1]
    mpt = meters_per_tile
    # Only the stretches on the map: a road running off its edge would send a
    # drive off it too.
    edge = box(0, 0, w - 1, h - 1)
    lines = []
    for r in roads:
        if len(r) < 2:
            continue
        part = LineString(r).intersection(edge)
        for piece in getattr(part, "geoms", [part]):
            if piece.geom_type == "LineString" and piece.length > 0:
                lines.append(piece)
    tree = STRtree(lines) if lines else None
    buildings = footprint_mask(footprints, (w, h))
    water = np.all(land == C.WATER, axis=2)
    drive_ground = np.zeros((h, w), dtype=bool)
    for colour in DRIVE_GROUND:
        drive_ground |= np.all(land == colour, axis=2)
    reach_max = clear_max_m * (1 + WOBBLE) / mpt + EDGE_M / mpt + 2

    polys = []
    for ring in footprints:
        if len(ring) < 3:
            continue
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty and poly.geom_type == "Polygon":
            polys.append(poly)
    # The biggest first: the house gets the drive, and the garage or shed
    # beside it shares it rather than getting one of its own.
    polys.sort(key=lambda p: (-p.area, p.centroid.x, p.centroid.y))
    tarmac = np.zeros((h, w), dtype=bool)        # the drives laid so far
    share = max(1, int(round(DRIVE_SHARE_M / mpt)))

    for poly in polys:
        minx, miny, maxx, maxy = poly.bounds
        x0, y0 = max(0, int(minx - reach_max)), max(0, int(miny - reach_max))
        x1, y1 = min(w, int(maxx + reach_max) + 1), min(h, int(maxy + reach_max) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        seed = int((int(poly.centroid.x) * 73856093) ^ (int(poly.centroid.y) * 19349663)
                   ^ HOME_SEED) & 0xFFFFFFFF
        roll = float(_hash01(np.array([seed]), HOME_SEED)[0])
        radius = (clear_min_m + roll * (clear_max_m - clear_min_m)) / mpt
        clearing = _wobbly(poly, radius, seed)
        fringe = _wobbly(poly, radius, seed, extra=EDGE_M / mpt)
        bw, bh = x1 - x0, y1 - y0
        inside = _rasterise(clearing, x0, y0, bw, bh)
        edge = _rasterise(fringe, x0, y0, bw, bh) & ~inside
        win = vegp[y0:y1, x0:x1]
        woods = _is_woods(win)
        own = _rasterise(poly, x0, y0, bw, bh)
        ground = inside & ~own
        if not ground.any() or woods[ground].mean() < IN_WOODS:
            continue

        # The clearing: no woods, and lawn where the woods had dark grass.
        cut = inside & woods
        win[cut] = C.VEG_NOTHING
        lw = land[y0:y1, x0:x1]
        dark = inside & ~own & np.all(lw == C.DARK_GRASS, axis=2)
        lw[dark] = C.MEDIUM_GRASS
        # The fringe: some trees a grade thinner, so the wood fades out.
        ids = (np.arange(y0, y1, dtype=np.int64)[:, None] * w
               + np.arange(x0, x1, dtype=np.int64)[None, :])
        thin = edge & woods & (_hash01(ids, HOME_SEED + 1) < EDGE_THIN)
        for colour, to in THINNER.items():
            sel = thin & np.all(win == colour, axis=2)
            win[sel] = to
        sel = thin & np.all(win == C.SPARSE_TREES, axis=2)
        win[sel] = C.VEG_NOTHING
        done[y0:y1, x0:x1] |= inside
        counts["clearings"] += 1

        # The drive, to the nearest road, if it is a house and not a shed.
        if tree is None or poly.area * mpt * mpt < DRIVE_MIN_M2:
            continue
        nx0, ny0 = max(0, int(minx) - share), max(0, int(miny) - share)
        nx1, ny1 = min(w, int(maxx) + share + 1), min(h, int(maxy) + share + 1)
        if nx1 > nx0 and ny1 > ny0 and tarmac[ny0:ny1, nx0:nx1].any():
            near = _rasterise(poly.buffer(share), nx0, ny0, nx1 - nx0, ny1 - ny0)
            if (near & tarmac[ny0:ny1, nx0:nx1]).any():
                continue
        line = lines[int(tree.nearest(poly))]
        gap = poly.distance(line)
        if gap <= DRIVE_MIN_TILES or gap * mpt > DRIVE_MAX_M:
            continue
        p, q = nearest_points(poly, line)
        bend = DRIVE_BEND * (2 * float(_hash01(np.array([seed]), HOME_SEED + 2)[0]) - 1)
        for b in (bend, 0.0):
            path = _bezier((p.x, p.y), (q.x, q.y), b)
            xs = [x for x, _ in path]
            ys = [y for _, y in path]
            dx0, dy0 = max(0, int(min(xs)) - DRIVE_WIDTH), max(0, int(min(ys)) - DRIVE_WIDTH)
            dx1 = min(w, int(max(xs)) + DRIVE_WIDTH + 1)
            dy1 = min(h, int(max(ys)) + DRIVE_WIDTH + 1)
            if dx1 <= dx0 or dy1 <= dy0:
                break
            mask = Image.new("L", (dx1 - dx0, dy1 - dy0), 0)
            ImageDraw.Draw(mask).line([(x - dx0, y - dy0) for x, y in path],
                                      fill=255, width=DRIVE_WIDTH)
            drive = np.asarray(mask) > 0
            own_d = _rasterise(poly, dx0, dy0, dx1 - dx0, dy1 - dy0)
            others = buildings[dy0:dy1, dx0:dx1] & ~own_d
            if (drive & (others | water[dy0:dy1, dx0:dx1])).any():
                continue
            lay = drive & ~own_d & drive_ground[dy0:dy1, dx0:dx1]
            land[dy0:dy1, dx0:dx1][lay] = C.DARK_ASPHALT
            tarmac[dy0:dy1, dx0:dx1] |= lay
            # Nothing grows on it, and the trees stand back a tile either side.
            from .vegetation import _box_any
            verge = _box_any(drive, 1) & ~own_d
            vw = vegp[dy0:dy1, dx0:dx1]
            vw[verge & _is_woods(vw)] = C.VEG_NOTHING
            vw[lay] = C.VEG_NOTHING
            done[dy0:dy1, dx0:dx1] |= verge
            counts["drives"] += 1
            break

    veg.paste(Image.fromarray(vegp, "RGB"))
    landscape.paste(Image.fromarray(land, "RGB"))
    return done, counts
