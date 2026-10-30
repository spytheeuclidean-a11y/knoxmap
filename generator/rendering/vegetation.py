"""The vegetation pass: woodland, hedges and orchards, gardens, wild growth, and clearing
trees off buildings and roads."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from .. import pz_colors as C
from ..osm import OSMFeature, classify
from .geometry import _feature_coords_px, _is_polygon
from .projection import Projector


def _paint_vegetation(veg: Image.Image, landscape: Image.Image,
                      feats: list[OSMFeature], proj: Projector,
                      density: float = 1.0) -> None:
    _paint_vegetation_extras(veg, landscape, feats, proj)
    _paint_woodland(veg, landscape,
                    [f for f in feats if classify(f.tags, _is_polygon(f)) in
                     {"forest", "scrub", "tree_single"}], proj, density)


def _paint_woodland(veg: Image.Image, landscape: Image.Image,
                    feats: list[OSMFeature], proj: Projector,
                    density: float = 1.0) -> None:
    """Paint trees on the vegetation bitmap.

    Forest polygons get full density (TREES), scrub becomes bushes+trees,
    single-tree nodes become small dots. Forest edges get downgraded to a
    mix with dark grass so the transition isn't a hard rectangle.

    `density` below 1 thins the woodland by stepping every tile down one
    grade - full trees become a mix with dark grass, a mix becomes sparse,
    sparse becomes nothing - and above 1 it does the reverse. Which matters
    because trees are cover: a map buried in forest plays completely
    differently from the same map with hedgerows.
    """
    mask = Image.new("L", veg.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    scrub_mask = Image.new("L", veg.size, 0)
    scrub_draw = ImageDraw.Draw(scrub_mask)

    for feat in feats:
        cat = classify(feat.tags, _is_polygon(feat))
        rings = _feature_coords_px(feat, proj)
        if cat == "forest":
            if _is_polygon(feat):
                for ring in rings:
                    if len(ring) >= 3:
                        mask_draw.polygon(ring, fill=255)
        elif cat == "scrub":
            if _is_polygon(feat):
                for ring in rings:
                    if len(ring) >= 3:
                        scrub_draw.polygon(ring, fill=255)
        elif cat == "tree_single":
            if rings and rings[0]:
                x, y = rings[0][0]
                r = max(1, int(2 / proj.meters_per_tile))
                mask_draw.ellipse((x - r, y - r, x + r, y + r), fill=255)

    # Build a "border band" of the forest mask so we can paint edges lighter.
    eroded = mask.filter(ImageFilter.MinFilter(5))
    veg_px = veg.load()
    mask_px = mask.load()
    eroded_px = eroded.load()
    scrub_px = scrub_mask.load()
    land_px = landscape.load()

    # Thickest to thinnest. `density` shifts every tile along this ladder.
    GRADES = [C.VEG_NOTHING, C.SPARSE_TREES, C.TREES_DARK_GRASS, C.TREES]

    def graded(colour) -> tuple[int, int, int]:
        if density == 1.0:
            return colour
        i = GRADES.index(colour)
        shift = round((density - 1.0) * 2)
        return GRADES[min(max(i + shift, 0), len(GRADES) - 1)]

    w, h = veg.size
    for y in range(h):
        for x in range(w):
            if scrub_px[x, y]:
                veg_px[x, y] = C.BUSHES_TREES_DARK_GRASS
            if mask_px[x, y]:
                # Only paint trees on grass / dirt. Skip water, roads, buildings.
                lp = land_px[x, y]
                if lp == C.WATER:
                    continue
                shade = graded(C.TREES if eroded_px[x, y]
                               else C.TREES_DARK_GRASS)
                if shade == C.VEG_NOTHING:
                    continue
                veg_px[x, y] = shade
                # Trees on a grass tile → switch the landscape to DARK_GRASS
                # so the PZ renderer is happy (trees sit on dark grass best).
                if lp in (C.MEDIUM_GRASS, C.LIGHT_GRASS):
                    land_px[x, y] = C.DARK_GRASS


def _paint_vegetation_extras(veg: Image.Image, landscape: Image.Image,
                             feats: list[OSMFeature], proj: Projector) -> None:
    """Hedges, orchards, cemeteries and wetland, which are not woodland.

    Hedges are rows of bushes a metre or two wide along their line. Orchard
    trees go in on a regular grid - what makes an orchard recognisable from
    the air is that its trees stand in rows. Cemeteries get scattered flowers
    and the odd tree, wetland patches of dense bush.
    """
    import random

    rng = random.Random(0x5EED)
    draw = ImageDraw.Draw(veg)
    land_draw = ImageDraw.Draw(landscape)
    vp = veg.load()
    lp = landscape.load()
    w, h = veg.size

    def polygon_mask(feat):
        mask = Image.new("1", veg.size, 0)
        md = ImageDraw.Draw(mask)
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                md.polygon(ring, fill=1)
        return mask

    for feat in feats:
        cat = classify(feat.tags, _is_polygon(feat))
        if feat.tags.get("barrier") == "hedge":
            width = max(1, int(round(1.5 / proj.meters_per_tile)))
            for ring in _feature_coords_px(feat, proj):
                if len(ring) >= 2:
                    draw.line(ring, fill=C.BUSHES, width=width)
        elif cat in {"orchard", "cemetery", "wetland"} and _is_polygon(feat):
            mask = polygon_mask(feat)
            bbox = mask.getbbox()
            if not bbox:
                continue
            mp = mask.load()
            x0, y0, x1, y1 = bbox
            spacing = max(2, int(round(4 / proj.meters_per_tile)))
            for y in range(y0, y1):
                for x in range(x0, x1):
                    if not mp[x, y] or lp[x, y] == C.WATER:
                        continue
                    if cat == "orchard":
                        if x % spacing == 0 and y % spacing == 0:
                            vp[x, y] = C.TREES
                            lp[x, y] = C.DARK_GRASS
                    elif cat == "cemetery":
                        # A few flowers between the graves, not instead of
                        # them: the headstones themselves go in later, as
                        # props (knoxbuild/props.py).
                        roll = rng.random()
                        if roll < 0.012:
                            vp[x, y] = C.TREES
                            lp[x, y] = C.DARK_GRASS
                        elif roll < 0.04:
                            vp[x, y] = C.FLOWERS
                    else:
                        if rng.random() < 0.35:
                            vp[x, y] = C.DENSE_BUSHES_GRASS
                            lp[x, y] = C.DARK_GRASS


# Garden planting. Trees came only from mapped woods, orchards and single-tree
# nodes, and suburbs rarely map their garden trees, so a real leafy suburb
# came out as houses standing on bare lawn. Yards - grass within reach of a
# house, clear of roads and paths - get a tree about every GARDEN_TREE_EVERY
# tiles each way, and a few shrubs against the house walls.
GARDEN_REACH_TILES = 18        # how far from a house its yard reaches
GARDEN_TREE_EVERY = 9
GARDEN_TREE_CHANCE = 0.6
GARDEN_CLEAR_OF_HOUSE = 3      # a tree trunk this far off the wall at least
GARDEN_CLEAR_OF_PAVING = 2     # and off the kerb, drive or path
SHRUB_CHANCE = 0.12            # per tile of lawn along a house wall
# Tufts over open grass. A lawn of one flat grass tile looked like felt beside
# the vanilla map, whose grass is broken up by clumps everywhere.
SHORT_GRASS_SHARE = 0.2
# Long grass is off: its rule mixes in flowerbed tiles, which came out as pink
# and blue squares all over every lawn.
LONG_GRASS_SHARE = 0.0
GRASS_COLOURS = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS)


# Rows of the map worked on at a time in _box_any. A whole town's summed-area
# table is four bytes a tile twice over - a 6000 x 5400 map needed a third of a
# gigabyte for one call, which is what ran a 32-bit Python out of memory. In
# strips it is a few megabytes, for the same answer.
BOX_STRIP_ROWS = 512


def _box_any(mask, radius: int):
    """True wherever `mask` is true within `radius` tiles (a square reach)."""
    import numpy as np

    h, w = mask.shape
    out = np.zeros((h, w), dtype=bool)
    k = 2 * radius + 1
    for top in range(0, h, BOX_STRIP_ROWS):
        bottom = min(h, top + BOX_STRIP_ROWS)
        # The strip, plus the rows on either side that can reach into it. Past
        # the top and bottom of the map there is nothing, which is what the
        # padding stands for, exactly as it did for the whole map at once.
        y0, y1 = max(0, top - radius), min(h, bottom + radius)
        block = np.pad(mask[y0:y1].astype(np.int32), radius + 1)
        ii = block.cumsum(0)
        ii = ii.cumsum(1)
        rows = y1 - y0
        total = (ii[k:k + rows, k:k + w] - ii[0:rows, k:k + w]
                 - ii[k:k + rows, 0:w] + ii[0:rows, 0:w])
        out[top:bottom] = total[top - y0:bottom - y0] > 0
    return out


def _paint_gardens(veg: Image.Image, landscape: Image.Image,
                   building_feats: list[OSMFeature], proj: Projector,
                   density: float = 1.0) -> int:
    """Trees in yards and shrubs along house walls. Returns trees planted."""
    import numpy as np

    if not building_feats or density <= 0:
        return 0
    houses = Image.new("1", veg.size, 0)
    hd = ImageDraw.Draw(houses)
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                hd.polygon(ring, fill=1)
    house = np.array(houses, dtype=bool)
    del houses
    ground = np.array(landscape.convert("RGB"))
    grass = np.zeros(house.shape, dtype=bool)
    for colour in GRASS_COLOURS:
        grass |= np.all(ground == colour, axis=2)
    del ground                       # a town's worth of pixels; let it go
    vegp = np.array(veg.convert("RGB"))
    empty = np.all(vegp == 0, axis=2)
    del vegp
    lawn = grass & empty & ~house
    del empty
    paved_near = _box_any(~grass & ~house, GARDEN_CLEAR_OF_PAVING)

    yard = lawn & _box_any(house, GARDEN_REACH_TILES)         & ~_box_any(house, GARDEN_CLEAR_OF_HOUSE) & ~paved_near
    rng = np.random.default_rng(1234)
    step = GARDEN_TREE_EVERY
    chance = min(1.0, GARDEN_TREE_CHANCE * density)
    h, w = house.shape
    px = veg.load()
    planted = 0
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            if rng.random() >= chance:
                continue
            ys, xs = np.nonzero(yard[y0:y0 + step, x0:x0 + step])
            if len(xs) == 0:
                continue
            i = rng.integers(len(xs))
            px[int(x0 + xs[i]), int(y0 + ys[i])] = C.TREES
            planted += 1

    # Shrubs: lawn right against a wall, not in front of the paving.
    # The dice are rolled for the tiles in question, not for every tile on the
    # map: one roll each way over a town is a quarter of a gigabyte of floats.
    beside = lawn & _box_any(house, 1) & ~house & ~paved_near
    ys, xs = np.nonzero(beside)
    keep = rng.random(len(xs)) < SHRUB_CHANCE * density
    for x, y in zip(xs[keep].tolist(), ys[keep].tolist()):
        px[x, y] = C.BUSHES

    open_grass = lawn & ~beside & ~_box_any(house, 0)
    ys, xs = np.nonzero(open_grass)
    roll = rng.random(len(xs))
    for colour, share, lo in ((C.SHORT_GRASS, SHORT_GRASS_SHARE, 0.0),
                              (C.GRASS_ON_DARK, LONG_GRASS_SHARE, SHORT_GRASS_SHARE)):
        pick = (roll >= lo) & (roll < lo + share)
        for x, y in zip(xs[pick].tolist(), ys[pick].tolist()):
            if px[x, y] == C.VEG_NOTHING:
                px[x, y] = colour
    return planted


# Growth on land nobody mapped.
#
# Trees came only from mapped woods, orchards, single-tree nodes and the
# gardens of houses, so any ground OpenStreetMap says nothing about came out
# as an unbroken lawn - "more often than not it's the program getting
# confused and not just a field of nothing". Real open country has scrub and
# stands of trees in it wherever nobody is farming or mowing.
#
# It is kept off light grass, which is what farmland and churchyards are
# painted, so a wheat field stays a wheat field. And it clumps: one roll per
# tile puts a tree every so often everywhere, which is an orchard, while a
# slow noise field over the map gives thickets here and open ground there.
WILD_TREE_EVERY_M = 11.0
WILD_CLUMP_M = 70.0            # how far a thicket or a clearing runs
WILD_TREE_CHANCE = 0.75        # at the thickest, per patch of that size
WILD_BUSH_SHARE = 0.45         # of what grows, this much is scrub
WILD_CLEAR_OF_PAVING = 2       # tiles off a kerb, a drive or a path
WILD_GROUND = (C.DARK_GRASS, C.MEDIUM_GRASS)


def _paint_wild_growth(veg: Image.Image, landscape: Image.Image,
                       proj: Projector, density: float = 1.0) -> int:
    """Scatter trees and scrub over open grass. Returns what was planted."""
    import numpy as np

    if density <= 0:
        return 0
    ground = np.array(landscape.convert("RGB"))
    open_ground = np.zeros(ground.shape[:2], dtype=bool)
    for colour in WILD_GROUND:
        open_ground |= np.all(ground == colour, axis=2)
    del ground
    vegp = np.array(veg.convert("RGB"))
    bare = np.all(vegp == 0, axis=2)
    del vegp
    free = open_ground & bare
    del bare
    # Not up against a road, a pavement or a building: those tiles are the
    # verge, and the road details pass has its own plans for them.
    free &= ~_box_any(~open_ground, WILD_CLEAR_OF_PAVING)
    del open_ground

    h, w = free.shape
    step = max(2, int(round(WILD_TREE_EVERY_M / proj.meters_per_tile)))
    clump = max(step * 2, int(round(WILD_CLUMP_M / proj.meters_per_tile)))
    rng = np.random.default_rng(9871)
    field = rng.random(((h // clump) + 2, (w // clump) + 2)) ** 1.6
    px = veg.load()
    planted = 0
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            thickness = field[y0 // clump, x0 // clump]
            if rng.random() >= min(1.0, WILD_TREE_CHANCE * thickness * density):
                continue
            ys, xs = np.nonzero(free[y0:y0 + step, x0:x0 + step])
            if len(xs) == 0:
                continue
            i = int(rng.integers(len(xs)))
            px[int(x0 + xs[i]), int(y0 + ys[i])] = (
                C.BUSHES if rng.random() < WILD_BUSH_SHARE else C.TREES)
            planted += 1
    return planted


# Woods in the open. The scatter above is one tree to a patch, which across a
# field is a few lone trees and an empty horizon. A wood is a place: a few
# hundred metres of trees close together with a ragged edge, and a clearing
# between it and the next. They grow where smooth noise is highest, so they
# are blobs, not a grid of squares, and the share of open ground they take is
# a number to turn.
GROVE_SHARE = 0.14             # of open ground, at density 1
GROVE_CELL_M = 260.0           # how far apart woods are, give or take
GROVE_RAGGED_M = 70.0          # how ragged their edges are
GROVE_SOLID = 0.07             # noise above the edge where trees stand close
GROVE_LOOSE = 0.025            # ...and where they thin out toward the edge
GROVE_SEED = 5513


def _paint_groves(veg: Image.Image, landscape: Image.Image,
                  proj: Projector, density: float = 1.0) -> int:
    """Woods on open grass. Returns the tiles planted."""
    import numpy as np

    if density <= 0:
        return 0
    ground = np.array(landscape.convert("RGB"))
    open_ground = np.zeros(ground.shape[:2], dtype=bool)
    for colour in WILD_GROUND:
        open_ground |= np.all(ground == colour, axis=2)
    del ground
    vegp = np.array(veg.convert("RGB"))
    free = open_ground & np.all(vegp == 0, axis=2)
    del vegp
    free &= ~_box_any(~open_ground, WILD_CLEAR_OF_PAVING)
    del open_ground
    h, w = free.shape
    if not free.any():
        return 0

    rng = np.random.default_rng(GROVE_SEED)
    big = max(8, int(round(GROVE_CELL_M / proj.meters_per_tile)))
    small = max(4, int(round(GROVE_RAGGED_M / proj.meters_per_tile)))
    lat_big = rng.random((h // big + 3, w // big + 3), dtype=np.float32)
    lat_small = rng.random((h // small + 3, w // small + 3), dtype=np.float32)

    def lattice(lat, cell, ys, xs):
        fy, fx = ys / cell, xs / cell
        y0, x0 = fy.astype(int), fx.astype(int)
        ty, tx = fy - y0, fx - x0
        ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)   # smoothstep
        y1, x1 = y0 + 1, x0 + 1
        top = lat[np.ix_(y0, x0)] * (1 - tx) + lat[np.ix_(y0, x1)] * tx
        bot = lat[np.ix_(y1, x0)] * (1 - tx) + lat[np.ix_(y1, x1)] * tx
        return top * (1 - ty[:, None]) + bot * ty[:, None]

    def noise(ys, xs):
        return (0.85 * lattice(lat_big, big, ys, xs)
                + 0.15 * lattice(lat_small, small, ys, xs))

    # The edge is where the noise is high enough for `share` of the open
    # ground to lie above it, read off a thin sample rather than every tile.
    share = min(0.6, GROVE_SHARE * density)
    sy, sx = np.arange(0, h, 6), np.arange(0, w, 6)
    sample = noise(sy.astype(np.float32), sx.astype(np.float32))[free[::6, ::6]]
    if sample.size == 0:
        return 0
    edge = float(np.quantile(sample, 1.0 - share))

    planted = 0
    xs = np.arange(w, dtype=np.float32)
    for top in range(0, h, BOX_STRIP_ROWS):
        bottom = min(h, top + BOX_STRIP_ROWS)
        n = noise(np.arange(top, bottom, dtype=np.float32), xs)
        inside = free[top:bottom] & (n > edge)
        if not inside.any():
            continue
        strip = np.array(veg.crop((0, top, w, bottom)).convert("RGB"))
        strip[inside] = C.SPARSE_TREES
        strip[inside & (n > edge + GROVE_LOOSE)] = C.TREES_DARK_GRASS
        strip[inside & (n > edge + GROVE_SOLID)] = C.TREES
        veg.paste(Image.fromarray(strip), (0, top))
        # Trees sit on dark grass, as the woods the mapper drew do.
        land = np.array(landscape.crop((0, top, w, bottom)).convert("RGB"))
        lawn = inside & (np.all(land == C.MEDIUM_GRASS, axis=2)
                         | np.all(land == C.LIGHT_GRASS, axis=2))
        if lawn.any():
            land[lawn] = C.DARK_GRASS
            landscape.paste(Image.fromarray(land), (0, top))
        planted += int(inside.sum())
    return planted


def _clear_building_vegetation(veg: Image.Image, feats: list[OSMFeature],
                               proj: Projector) -> None:
    """No trees or bushes inside a building.

    Woodland polygons and single-tree nodes are mapped independently of the
    buildings standing in them, so a tree painted under a house came out as a
    tree growing through its living-room floor.
    """
    mask = Image.new("1", veg.size, 0)
    md = ImageDraw.Draw(mask)
    for feat in feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                md.polygon(ring, fill=1)
    blank = Image.new("RGB", veg.size, C.VEG_NOTHING)
    veg.paste(blank, (0, 0), mask)


def _clear_road_vegetation(veg: Image.Image, landscape: Image.Image) -> None:
    """Keep mapped woodland and scrub off every rasterized road surface."""
    import numpy as np

    road_colours = np.array((C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                             C.DARKEST_ASPHALT, C.DARK_POTHOLE,
                             C.LIGHT_POTHOLE), dtype=np.uint8)
    width, height = landscape.size
    for top in range(0, height, 256):
        bottom = min(height, top + 256)
        ground = np.asarray(landscape.crop((0, top, width, bottom)))
        road = np.zeros(ground.shape[:2], dtype=bool)
        for colour in road_colours:
            road |= np.all(ground == colour, axis=2)
        if not road.any():
            continue
        vegetation = np.array(veg.crop((0, top, width, bottom)))
        vegetation[road] = C.VEG_NOTHING
        veg.paste(Image.fromarray(vegetation), (0, top))
