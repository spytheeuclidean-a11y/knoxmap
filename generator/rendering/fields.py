"""Ground that is not just a colour: fields, pools in a marsh, rock fields.

Farmland was a plain light-grass plain from hedge to hedge. A farmed landscape
is plots: a few hundred metres of ploughed rows, some standing in corn, some
bare, the odd one left fallow, and a hedgerow along some of the boundaries.
Stock WorldEd already has the tiles - "Horizontal Dirt" and "Vertical Dirt"
are furrowed soil, and "Farm Corn 1/2" are standing stalks - and KnoxMap never
used them.

Fields are drawn on OSM `landuse=farmland` and on WorldCover cropland that OSM
left blank. Wetland gets pools and rock-ground classes get rocks, here too,
since all three repaint the ground before anything is planted on it.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from .. import pz_colors as C

# How big a plot is, metres, drawn per field (OSM) or per row and column of
# the grid (WorldCover). A field no longer than the top of this is one plot.
FIELD_CELL_M = (60.0, 150.0)
CORN_SHARE = 0.5               # of plots: standing corn on furrows
BARE_SHARE = 0.35              # ...bare furrows; the rest lie fallow
HEDGE_CHANCE = 0.4             # a plot whose boundary is a hedgerow
FALLOW_TUFTS = 0.2             # of a fallow plot's tiles, a tuft of grass
FIELD_SEED = 4421
STRIP_ROWS = 512


def _hash01(values, salt: int):
    """A uniform number in [0, 1) for each integer in `values`, the same every
    run and independent of what order anything is painted in (splitmix64)."""
    with np.errstate(over="ignore"):
        z = values.astype(np.uint64) + np.uint64((salt * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _borders(field, pid):
    """Tiles of the field with a 4-neighbour outside it or in another plot."""
    h, w = field.shape
    edge = np.zeros((h, w), dtype=bool)
    pad_f = np.pad(field, 1, constant_values=False)
    pad_p = np.pad(pid, 1, constant_values=-1)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nf = pad_f[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        np_ = pad_p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        edge |= ~nf | (np_ != pid)
    return field & edge


def _paint_plots(land, veg, field, pid, furrow_h, tile_ids, salt: int):
    """Paint plots into the (rows, cols, 3) arrays `land` and `veg`, in place.

    `pid` numbers each tile's plot, `furrow_h` says per tile whether its plot's
    rows run across (else down). `tile_ids` are unique per tile on the map, for
    the per-tile tufts. Returns the plot ids painted.
    """
    if not field.any():
        return set()
    border = _borders(field, pid)
    inside = field & ~border
    kind = _hash01(pid, salt)
    corn = kind < CORN_SHARE
    fallow = kind >= CORN_SHARE + BARE_SHARE
    ploughed = inside & ~fallow
    empty = np.all(veg == 0, axis=2)
    land[ploughed & furrow_h] = C.DIRT_ROWS_H
    land[ploughed & ~furrow_h] = C.DIRT_ROWS_V
    second = _hash01(pid, salt + 1) < 0.5
    veg[ploughed & corn & ~second & empty] = C.CORN_1
    veg[ploughed & corn & second & empty] = C.CORN_2
    tufts = inside & fallow & empty & (_hash01(tile_ids, salt + 2) < FALLOW_TUFTS)
    veg[tufts] = C.SHORT_GRASS
    hedged = border & empty & (_hash01(pid, salt + 3) < HEDGE_CHANCE)
    veg[hedged] = C.BUSHES
    return set(np.unique(pid[field]).tolist())


def _polygon_field(landscape, veg, proj, ring, index: int) -> int:
    from shapely.geometry import Polygon

    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < 4:
        return 0
    w, h = landscape.size
    minx, miny, maxx, maxy = poly.bounds
    x0, y0 = max(0, int(math.floor(minx))), max(0, int(math.floor(miny)))
    x1, y1 = min(w, int(math.ceil(maxx)) + 1), min(h, int(math.ceil(maxy)) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in ring], fill=255)
    box = (x0, y0, x1, y1)
    land = np.array(landscape.crop(box))
    vegp = np.array(veg.crop(box))
    field = (np.asarray(mask) > 0) & np.all(land == C.LIGHT_GRASS, axis=2)
    if not field.any():
        return 0

    # The long side of the field sets which way the plots and the rows run.
    rect = list(poly.minimum_rotated_rectangle.exterior.coords)
    e1 = (rect[1][0] - rect[0][0], rect[1][1] - rect[0][1])
    e2 = (rect[2][0] - rect[1][0], rect[2][1] - rect[1][1])
    long_edge, short_edge = (e1, e2) if math.hypot(*e1) >= math.hypot(*e2) else (e2, e1)
    theta = math.atan2(long_edge[1], long_edge[0])
    across = abs(math.cos(theta)) >= abs(math.sin(theta))

    cx, cy = poly.centroid.x, poly.centroid.y
    seed = int((int(cx) * 73856093) ^ (int(cy) * 19349663) ^ FIELD_SEED) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    biggest = FIELD_CELL_M[1] / proj.meters_per_tile
    ys, xs = np.mgrid[y0:y1, x0:x1]
    if math.hypot(*long_edge) <= biggest:
        pid = np.zeros(field.shape, dtype=np.int64)
    else:
        cu = rng.uniform(*FIELD_CELL_M) / proj.meters_per_tile
        cv = rng.uniform(*FIELD_CELL_M) / proj.meters_per_tile
        u = xs * math.cos(theta) + ys * math.sin(theta) + rng.uniform(0, cu)
        v = -xs * math.sin(theta) + ys * math.cos(theta) + rng.uniform(0, cv)
        iu = np.floor(u / cu).astype(np.int64)
        iv = np.floor(v / cv).astype(np.int64)
        iu -= iu.min()
        iv -= iv.min()
        pid = iu * (int(iv.max()) + 1) + iv
    pid = pid + (index + 1) * (1 << 32)
    furrow_h = np.full(field.shape, across)
    tile_ids = ys.astype(np.int64) * w + xs
    painted = _paint_plots(land, vegp, field, pid, furrow_h, tile_ids, FIELD_SEED)
    landscape.paste(Image.fromarray(land, "RGB"), (x0, y0))
    veg.paste(Image.fromarray(vegp, "RGB"), (x0, y0))
    return len(painted)


def _cuts(length: int, cell, rng):
    """Boundaries of plots along one side of the map: plot index per tile, and
    each plot's size."""
    sizes = []
    total = 0
    while total < length:
        size = max(4, int(round(rng.uniform(*cell))))
        sizes.append(size)
        total += size
    index = np.repeat(np.arange(len(sizes)), sizes)[:length]
    return index, np.array(sizes)


def _cropland(landscape, veg, proj, cropland) -> int:
    h, w = cropland.shape
    rng = np.random.default_rng(FIELD_SEED + 1)
    cell = (FIELD_CELL_M[0] / proj.meters_per_tile, FIELD_CELL_M[1] / proj.meters_per_tile)
    col, col_w = _cuts(w, cell, rng)
    row, row_h = _cuts(h, cell, rng)
    painted = set()
    for top in range(0, h, STRIP_ROWS):
        bottom = min(h, top + STRIP_ROWS)
        a, b = max(0, top - 1), min(h, bottom + 1)
        field = cropland[a:b]
        if not field[top - a:top - a + (bottom - top)].any():
            continue
        r = row[a:b][:, None]
        c = col[None, :]
        pid = (r * len(col_w) + c).astype(np.int64)
        furrow_h = col_w[c] >= row_h[r]
        tile_ids = np.arange(a, b, dtype=np.int64)[:, None] * w + np.arange(w)[None, :]
        land = np.array(landscape.crop((0, a, w, b)))
        vegp = np.array(veg.crop((0, a, w, b)))
        painted |= _paint_plots(land, vegp, field, pid, furrow_h, tile_ids, FIELD_SEED)
        keep = slice(top - a, top - a + (bottom - top))
        landscape.paste(Image.fromarray(land[keep], "RGB"), (0, top))
        veg.paste(Image.fromarray(vegp[keep], "RGB"), (0, top))
    return len(painted)


def paint_fields(landscape, veg, proj, polygons, cropland) -> int:
    """Plots on each OSM farmland polygon (pixel rings) and on the `cropland`
    mask (WorldCover, bool, or None). Only light-grass ground is ploughed, so
    a road or a track OSM drew across a field stays. Returns plots painted."""
    plots = 0
    for index, ring in enumerate(polygons):
        if len(ring) >= 3:
            plots += _polygon_field(landscape, veg, proj, ring, index)
    if cropland is not None and cropland.any():
        plots += _cropland(landscape, veg, proj, cropland)
    return plots


# --- pools in wetland -------------------------------------------------------
#
# A marsh mapped as solid reeds is a hedge maze. Real ones are broken by open
# water: small pools among the reeds, banked by the thickest growth. They come
# from a small-scale noise field cut at the top tenth, which gives separate
# blobs a few to a dozen tiles across rather than one lake. Water cannot be
# walked through in Project Zomboid, so the share is kept low and the pools
# stay off roads, paths, buildings and the marsh's own edge.
POOL_SHARE = 0.10
POOL_CELL_M = 10.0
POOL_CLEAR_TILES = 2
POOL_SEED = 7001

# --- rock fields ----------------------------------------------------------
#
# Moss and lichen is tundra or bare upland: low ground cover broken by stone.
# Bare / sparse vegetation is scree, quarry spoil, desert. Both get clumps of
# low rocks you can walk over and the odd boulder that blocks the way, kept
# off roads and paths so it never closes a route; tundra also gets patches of
# moss (dark grass) and the odd low bush.
ROCK_SHARE = {100: 0.30, 60: 0.10}
BOULDER_SHARE = {100: 0.03, 60: 0.01}
MOSS_SHARE = 0.30
ROCK_CLUMP_M = 25.0
MOSS_CELL_M = 30.0
ROCK_CLEAR_TILES = 2
ROCK_SEED = 8123
TUNDRA_BUSH = 0.02


def _reach(mask, radius: int, outside: bool):
    """True wherever `mask` is true within `radius` tiles; past the map edge
    counts as `outside`."""
    from .vegetation import _box_any

    if not outside:
        return _box_any(mask, radius)
    padded = np.pad(mask, radius, constant_values=True)
    return _box_any(padded, radius)[radius:-radius, radius:-radius]


def _threshold(region, lats, share: float):
    """The noise value above which `share` of `region` lies, read off every
    fourth tile."""
    from .noise import smooth_noise

    h, w = region.shape
    sy, sx = np.arange(0, h, 4), np.arange(0, w, 4)
    sample = smooth_noise(sy.astype(np.float32), sx.astype(np.float32), lats)
    sample = sample[region[::4, ::4]]
    if sample.size == 0:
        return None
    return float(np.quantile(sample, 1.0 - share))


def _strips(h: int):
    for top in range(0, h, STRIP_ROWS):
        yield top, min(h, top + STRIP_ROWS)


def paint_pools(landscape, veg, proj, wet, blocked) -> int:
    """Open-water pools in the `wet` tiles, none on or near `blocked` ones
    (buildings) or the edge of the wet. Returns the pool tiles."""
    from .noise import lattices, smooth_noise

    if wet is None or not wet.any():
        return 0
    h, w = wet.shape
    allowed = wet & ~_reach(~wet | blocked, POOL_CLEAR_TILES, outside=True)
    if not allowed.any():
        return 0
    cell = max(3, int(round(POOL_CELL_M / proj.meters_per_tile)))
    lats = lattices(h, w, [(cell, 1.0)], POOL_SEED)
    edge = _threshold(wet, lats, POOL_SHARE)
    if edge is None:
        return 0
    pool = np.zeros((h, w), dtype=bool)
    xs = np.arange(w, dtype=np.float32)
    for top, bottom in _strips(h):
        if not allowed[top:bottom].any():
            continue
        n = smooth_noise(np.arange(top, bottom, dtype=np.float32), xs, lats)
        pool[top:bottom] = allowed[top:bottom] & (n > edge)
    if not pool.any():
        return 0
    bank = wet & ~pool & _reach(pool, 1, outside=False)
    for top, bottom in _strips(h):
        p, b = pool[top:bottom], bank[top:bottom]
        if not (p.any() or b.any()):
            continue
        land = np.array(landscape.crop((0, top, w, bottom)))
        vegp = np.array(veg.crop((0, top, w, bottom)))
        land[p] = C.WATER
        vegp[p] = C.VEG_NOTHING
        land[b] = C.DARK_GRASS
        vegp[b] = C.DENSE_BUSHES_GRASS
        landscape.paste(Image.fromarray(land, "RGB"), (0, top))
        veg.paste(Image.fromarray(vegp, "RGB"), (0, top))
    return int(pool.sum())


def paint_rocks(landscape, veg, proj, grid, owned) -> int:
    """Rock fields on WorldCover moss and lichen (100) and bare ground (60)
    that OSM left blank. Returns the rock and boulder tiles."""
    from .noise import lattices, smooth_noise

    if grid is None or owned is None:
        return 0
    h, w = owned.shape
    open_ = ~_reach(~owned, ROCK_CLEAR_TILES, outside=False)
    clump = max(3, int(round(ROCK_CLUMP_M / proj.meters_per_tile)))
    moss_cell = max(3, int(round(MOSS_CELL_M / proj.meters_per_tile)))
    xs = np.arange(w, dtype=np.float32)
    tile_ids = None
    placed = 0
    for code, share in ROCK_SHARE.items():
        region = owned & (grid == code)
        if not region.any():
            continue
        lats = lattices(h, w, [(clump, 0.8), (max(2, clump // 3), 0.2)], ROCK_SEED + code)
        edge = _threshold(region, lats, min(1.0, 2 * share))
        moss_lats = lattices(h, w, [(moss_cell, 1.0)], ROCK_SEED + 1000 + code)
        moss_edge = _threshold(region, moss_lats, MOSS_SHARE) if code == 100 else None
        boulder_p = BOULDER_SHARE[code] / max(1e-6, 2 * share)
        for top, bottom in _strips(h):
            r = region[top:bottom]
            if not r.any():
                continue
            ys = np.arange(top, bottom, dtype=np.float32)
            tile_ids = (np.arange(top, bottom, dtype=np.int64)[:, None] * w
                        + np.arange(w, dtype=np.int64)[None, :])
            land = np.array(landscape.crop((0, top, w, bottom)))
            vegp = np.array(veg.crop((0, top, w, bottom)))
            land[r] = C.DIRT
            if moss_edge is not None:
                land[r & (smooth_noise(ys, xs, moss_lats) > moss_edge)] = C.DARK_GRASS
            inside = r & (smooth_noise(ys, xs, lats) > edge)
            roll = _hash01(tile_ids, ROCK_SEED + code)
            rocks = inside & (roll < 0.5)
            boulders = rocks & open_[top:bottom] & (_hash01(tile_ids, ROCK_SEED + code + 1) < boulder_p)
            vegp[rocks] = C.ROCKS
            vegp[boulders] = C.BOULDERS
            if code == 100:
                bush = r & ~rocks & (_hash01(tile_ids, ROCK_SEED + 2) < TUNDRA_BUSH)
                vegp[bush] = C.BUSHES
            placed += int(rocks.sum())
            landscape.paste(Image.fromarray(land, "RGB"), (0, top))
            veg.paste(Image.fromarray(vegp, "RGB"), (0, top))
    return placed
