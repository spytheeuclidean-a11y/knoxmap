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
WILD_SAPLING_SHARE = 0.2       # and this much a young tree rather than a grown one
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
    young = C.TREE_SMALL if tree_rules_ready() else C.TREES
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
            roll = rng.random()
            px[int(x0 + xs[i]), int(y0 + ys[i])] = (
                C.BUSHES if roll < WILD_BUSH_SHARE
                else young if roll < WILD_BUSH_SHARE + WILD_SAPLING_SHARE
                else C.TREES)
            planted += 1
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


# Parks. A mapped park came out as mown grass with whatever the wild growth
# pass happened to drop on it, which is not what a park is. A park's trees
# stand round its edge, in a belt a few trees deep that screens it from the
# streets, and the middle is left open for whatever the park is for, with the
# odd specimen tree in it. Reported from a generated map: "in areas such as
# parks more big trees should probably generate, especially around the edges".
PARK_EDGE_M = 14.0              # how deep the belt of trees round a park runs
PARK_EDGE_TREE_EVERY_M = 5.0    # a tree about this far apart along the belt
PARK_EDGE_CHANCE = 0.9
PARK_EDGE_BUSH_SHARE = 0.3      # of what grows in the belt, this much is scrub
PARK_TREE_EVERY_M = 14.0        # and out in the middle, a tree now and then
PARK_CHANCE = 0.5
PARK_CLEAR_OF_PAVING = 1        # a path through a park keeps its width
# And of the trees, this share are young ones. Which size a tree comes out is
# otherwise the rule's to say, and the rule a park tree falls under calls for
# a grown one, so a park was a stand of trees all exactly the same height.
PARK_BELT_SAPLINGS = 0.25
PARK_SAPLINGS = 0.12
PARK_GROUND = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS)


def _polygon_mask(size, feats, proj):
    """A bool array, true inside these features' rings, or None if none drew."""
    import numpy as np

    mask = Image.new("1", size, 0)
    draw = ImageDraw.Draw(mask)
    drawn = 0
    for feat in feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                draw.polygon(ring, fill=1)
                drawn += 1
    if not drawn:
        return None
    return np.array(mask, dtype=bool)


def _block_picks(mask, step: int, rng, chance: float):
    """One place from each `step` x `step` block of the mask that wins its roll.

    The roll is per block, not per tile: one roll a tile plants something every
    so often everywhere, which is an orchard, while a block at a time leaves
    the gaps between trees that a wood or a park has. Which blocks come up is
    worked out over the whole mask at once - a town is thirty million tiles and
    looking at each of them in Python is minutes - and only the few that do are
    then looked into for a tile to use.
    """
    import numpy as np

    h, w = mask.shape
    rows, cols = h // step, w // step
    if rows < 1 or cols < 1:
        return
    blocks = (mask[:rows * step, :cols * step]
              .reshape(rows, step, cols, step)
              .transpose(0, 2, 1, 3)
              .reshape(rows * cols, step * step))
    wanted = blocks.any(1) & (rng.random(rows * cols) < chance)
    for i in np.nonzero(wanted)[0].tolist():
        inside = np.nonzero(blocks[i])[0]
        at = int(inside[rng.integers(len(inside))])
        row, col = divmod(i, cols)
        yield col * step + at % step, row * step + at // step


def _paint_parks(veg: Image.Image, landscape: Image.Image,
                 park_feats: list[OSMFeature], proj: Projector,
                 density: float = 1.0) -> int:
    """Trees round the edge of every mapped park, and a few in the middle.

    Returns how many were planted."""
    import numpy as np

    if not park_feats or density <= 0:
        return 0
    park = _polygon_mask(veg.size, park_feats, proj)
    if park is None:
        return 0
    ground = np.array(landscape.convert("RGB"))
    grass = np.zeros(park.shape, dtype=bool)
    for colour in PARK_GROUND:
        grass |= np.all(ground == colour, axis=2)
    del ground
    vegp = np.array(veg.convert("RGB"))
    free = park & grass & np.all(vegp == 0, axis=2)
    del vegp
    # Not up against a path or a road: the paths are the one thing in a park
    # people need, and a tree on the kerb of one blocks it.
    free &= ~_box_any(~grass, PARK_CLEAR_OF_PAVING)
    del grass
    # The belt is everything within PARK_EDGE_M of the park's own boundary.
    deep = max(1, int(round(PARK_EDGE_M / proj.meters_per_tile)))
    belt = free & _box_any(~park, deep)
    middle = free & ~belt
    del free, park

    rng = np.random.default_rng(0xBEEC4)
    px = veg.load()
    young = C.TREE_SMALL if tree_rules_ready() else C.TREES
    planted = 0
    for where, every_m, chance, bushes, saplings in (
            (belt, PARK_EDGE_TREE_EVERY_M, PARK_EDGE_CHANCE,
             PARK_EDGE_BUSH_SHARE, PARK_BELT_SAPLINGS),
            (middle, PARK_TREE_EVERY_M, PARK_CHANCE, 0.0, PARK_SAPLINGS)):
        step = max(2, int(round(every_m / proj.meters_per_tile)))
        for x, y in _block_picks(where, step, rng, min(1.0, chance * density)):
            roll = rng.random()
            px[x, y] = (C.BUSHES if roll < bushes
                        else young if roll < bushes + saplings else C.TREES)
            planted += 1
    return planted


# The big trees, and how thick on the ground each kind goes: one of that kind
# about every N tiles each way, as often as the chance says.
#
# Build 42 plants these as the ordinary tree of a wood - in its own maple
# forest a jumbo XL or XXL comes up about thirty times as often as a plain
# tree, and Knox County's cells carry some 1800 of them - while KnoxMap placed
# none at all, so every wood it made was undergrowth. A wood here is still
# mostly ordinary trees with the big ones standing out of it; a park's belt is
# where they matter most, because that is the side of a park people see.
WOOD_BIG_TREES = ((C.TREE_GIANT, 11, 0.55), (C.TREE_HUGE, 7, 0.6),
                  (C.TREE_BIG, 5, 0.6))
PARK_BELT_BIG_TREES = ((C.TREE_HUGE, 8, 0.6), (C.TREE_BIG, 5, 0.65))
PARK_BIG_TREES = ((C.TREE_GIANT, 22, 0.5), (C.TREE_HUGE, 14, 0.55),
                  (C.TREE_BIG, 10, 0.5))
WILD_BIG_TREES = ((C.TREE_GIANT, 24, 0.4), (C.TREE_HUGE, 14, 0.45),
                  (C.TREE_BIG, 9, 0.5))
# A mature tree in a garden, but never a jumbo XL or XXL: those lean over
# several squares, and a house behind one cannot be seen at all.
GARDEN_BIG_TREES = ((C.TREE_BIG, 15, 0.35),)
# Tree colours a big one may replace. The mix tiles count - the thin edge of a
# wood is where a big tree reads best of all - but not the sparse ones, which
# are mostly grass.
PLANTABLE = (C.TREES, C.TREES_DARK_GRASS)


class _Canopy:
    """Keeps the picture of one big tree off the next.

    A jumbo takes a 2x2 square, a jumbo XL 3x3 and a jumbo XXL 5x5 - the
    footprints the game's own tree features reserve, with the rest of the
    square left as bare ground (features/tree/maple_jumbo*.lua). Two planted
    inside each other's square read as one shapeless mass, so each claims its
    square and nothing else goes in it.
    """

    def __init__(self, shape):
        import numpy as np

        self.taken = np.zeros(shape, dtype=bool)
        self.blocked = None

    def box(self, x: int, y: int, side: int):
        """The square a tree at (x, y) needs, or None if it runs off the map."""
        h, w = self.taken.shape
        if side % 2:
            reach = side // 2
            x0, y0 = x - reach, y - reach
        else:
            x0, y0 = x, y           # the game's 2x2 keeps its tree in a corner
        if x0 < 0 or y0 < 0 or x0 + side > w or y0 + side > h:
            return None
        return slice(y0, y0 + side), slice(x0, x0 + side)

    def room(self, x: int, y: int, side: int):
        """That square, if nothing is standing in it already."""
        box = self.box(x, y, side)
        if box is None or self.taken[box].any():
            return None
        if self.blocked is not None and self.blocked[box].any():
            return None
        return box


def _plant_big_trees(veg: Image.Image, landscape: Image.Image,
                     wood_feats: list[OSMFeature], park_feats: list[OSMFeature],
                     building_feats: list[OSMFeature], proj: Projector,
                     density: float = 1.0) -> dict:
    """Grow some of the trees already planted into big ones.

    Every tree on the vegetation bitmap is one tile, and so was every tree in
    a KnoxMap map. The ones that make a wood look like a wood are several tiles
    across and need a square kept clear around them, so they are chosen here,
    out of the trees the passes above planted, once all of them are down and it
    can be seen what stands next to what.

    Returns how many of each kind went in."""
    import numpy as np

    counts: dict[str, int] = {}
    if density <= 0 or not tree_rules_ready():
        return counts
    vegp = np.array(veg.convert("RGB"))
    tree = np.zeros(vegp.shape[:2], dtype=bool)
    for colour in PLANTABLE:
        tree |= np.all(vegp == colour, axis=2)
    if not tree.any():
        return counts
    canopy = _Canopy(tree.shape)
    # A hedge, a bed of dense bush or a flower bed is something a mapper drew
    # or a pass put there on purpose; a big tree's square would clear a hole in
    # it, so it is kept off them. Water too: a tree does not stand in a river.
    blocked = np.zeros(tree.shape, dtype=bool)
    for colour in (C.BUSHES, C.DENSE_BUSHES_GRASS, C.FLOWERS):
        blocked |= np.all(vegp == colour, axis=2)
    del vegp
    ground = np.array(landscape.convert("RGB"))
    blocked |= np.all(ground == C.WATER, axis=2)
    del ground
    canopy.blocked = blocked

    woods = _polygon_mask(veg.size, [f for f in wood_feats if _is_polygon(f)
                                     and classify(f.tags, True) == "forest"], proj)
    parks = _polygon_mask(veg.size, park_feats, proj)
    gardens = _polygon_mask(veg.size, building_feats, proj)
    if gardens is not None:
        gardens = _box_any(gardens, GARDEN_REACH_TILES)
    # Each kind of ground gets its own mix, and the ground already spoken for
    # is left out of the next: a wood inside a park is park.
    rest = np.ones(tree.shape, dtype=bool)
    rounds = []
    if parks is not None:
        deep = max(1, int(round(PARK_EDGE_M / proj.meters_per_tile)))
        belt = parks & _box_any(~parks, deep)
        rounds.append((belt, PARK_BELT_BIG_TREES))
        rounds.append((parks & ~belt, PARK_BIG_TREES))
        rest &= ~parks
    if woods is not None:
        rounds.append((woods & rest, WOOD_BIG_TREES))
        rest &= ~woods
    if gardens is not None:
        rounds.append((gardens & rest, GARDEN_BIG_TREES))
        rest &= ~gardens
    rounds.append((rest, WILD_BIG_TREES))

    rng = np.random.default_rng(0x7E3E5)
    px = veg.load()
    for where, mix in rounds:
        here = tree & where
        if not here.any():
            continue
        for colour, every, chance in mix:
            side = C.BIG_TREE_ROOM[colour]
            for x, y in _block_picks(here, every, rng, min(1.0, chance * density)):
                box = canopy.room(x, y, side)
                if box is None:
                    continue
                canopy.taken[box] = True
                # The rest of the square is bare ground under the tree, the
                # way the game's own features leave it.
                rows, cols = box
                for fy in range(rows.start, rows.stop):
                    for fx in range(cols.start, cols.stop):
                        px[fx, fy] = C.VEG_NOTHING
                px[x, y] = colour
                counts[str(colour)] = counts.get(str(colour), 0) + 1
    return counts


def tree_rules_ready() -> bool:
    """Whether the map tools have the rules for trees of a size we choose.

    They are written by worlded/patch_rules_b42_trees.py when Setup runs, and a
    colour with no rule behind it is dropped with a warning - so on an install
    set up before the big trees existed, every tree stays the size its own rule
    says until Setup is run again. KNOXMAP_NO_BIG_TREES=1 turns them off.
    """
    import os

    if os.environ.get("KNOXMAP_NO_BIG_TREES") == "1":
        return False
    try:
        import knoxpaths
        rules = knoxpaths.mapping_tools_dir() / "config" / "Rules.txt"
        text = rules.read_text(encoding="utf-8", errors="replace")
        return all(f"KnoxMap tree {what}" in text
                   for what in ("Small tree", "Giant tree"))
    except Exception:      # noqa: BLE001 - no tools, no trees of our own
        return False
