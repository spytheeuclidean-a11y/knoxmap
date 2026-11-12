"""The things that make a piece of land what it is, once the ground is painted.

Some land uses are not buildings and not terrain, so they fell through both:
a cemetery came out as a lawn with flowers on it, and an army base as a patch
of bare dirt. What is missing in each case is the furniture of the place -
the headstones in rows, the supply crates and drums behind the wire - and
that is what this puts there.

Everything here is driven by the land-use polygons the renderer wrote
(<map>_areas.geojson, read through knoxbuild/areas.py), which come from
OpenStreetMap tags used the world over: landuse=cemetery and amenity=grave_yard
anywhere there are graves, landuse=military and the military=* tags anywhere
there is a base. Spacing is worked out in metres, so a map drawn at two metres
a tile gets the same graveyard as one drawn at half a metre.

The props go into tile-only lots, one per map cell, the way the fuel pumps and
the bridges do (knoxbuild/structures.py render_tiles_tbx).
"""
from __future__ import annotations

import os
import random

import numpy as np
from PIL import Image

from generator import pz_colors as C

from . import catalog
from .bitmaps import read_rgb, same_colour
from .structures import CELL, render_tiles_tbx
from .world import Placement

# location_community_cemetary_01: headstones, wooden crosses and the angel on
# her plinth. Several shapes, because a churchyard where every stone is the
# same reads as a car park.
HEADSTONES = ["location_community_cemetary_01_8", "location_community_cemetary_01_9",
              "location_community_cemetary_01_11", "location_community_cemetary_01_12",
              "location_community_cemetary_01_13", "location_community_cemetary_01_16",
              "location_community_cemetary_01_17"]
CROSSES = ["location_community_cemetary_01_30", "location_community_cemetary_01_31",
           "location_community_cemetary_01_44", "location_community_cemetary_01_46"]
ANGELS = ["location_community_cemetary_01_19", "location_community_cemetary_01_20",
          "location_community_cemetary_01_21", "location_community_cemetary_01_22"]
CROSS_SHARE = 0.12         # of the graves, a wooden cross instead of a stone
ANGEL_SHARE = 0.006        # and once in a while a monument
GRAVE_SPACING_M = 2.0      # along a row
GRAVE_ROW_M = 3.0          # between rows
PATH_EVERY_ROWS = 8        # a way through, so it is not one solid block
MAX_GRAVES = 40000         # a whole county of churchyards, and no more

# location_military_generic_01: ammunition crates, fuel drums and lockers.
# Nothing with English writing on it - the same base has to read as a base in
# any country the map is of.
CRATES = ["location_military_generic_01_8", "location_military_generic_01_9",
          "location_military_generic_01_16", "location_military_generic_01_17",
          "location_military_generic_01_0", "location_military_generic_01_1"]
DRUMS = ["location_military_generic_01_14", "location_military_generic_01_15",
         "location_military_generic_01_22", "location_military_generic_01_23"]
DUMP_EVERY_M = 26.0        # a stack of stores about this often across the site
DUMP_MIN_M2 = 400          # sites smaller than this get nothing
MAX_DUMPS = 600
PICNIC_SPACING_M = 38.0
PICNIC_MIN_M2 = 500
MAX_PICNIC_TABLES = 300

LAYER = "Furniture"
# Ground a prop never stands on: the carriageway, its pavement, and water.
ROAD = {C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT, C.DARKEST_ASPHALT,
    C.PALE_CONCRETE, C.DARK_POTHOLE, C.LIGHT_POTHOLE}
BLOCKED = ROAD | {C.WATER}


def _ring(x0: int, y0: int, wide: int, tall: int, distance: int) -> list:
    """The squares `distance` out from a rectangle, its top-left corner first."""
    out = []
    for x in range(x0 - distance, x0 + wide - 1 + distance + 1):
        out.append((x, y0 - distance))
        out.append((x, y0 + tall - 1 + distance))
    for y in range(y0 - distance + 1, y0 + tall - 1 + distance):
        out.append((x0 - distance, y))
        out.append((x0 + wide - 1 + distance, y))
    return out


def _write_lots(bdir: str, map_name: str, tag: str,
                tiles: list) -> list:
    """Tile-only lots, one per map cell, the way the fences and pumps go down."""
    by_cell: dict[tuple[int, int], list] = {}
    for t in tiles:
        by_cell.setdefault((t[0] // CELL, t[1] // CELL), []).append(t)
    placements = []
    for (cx, cy), group in sorted(by_cell.items()):
        gx0 = min(t[0] for t in group)
        gy0 = min(t[1] for t in group)
        gw = max(t[0] for t in group) - gx0 + 1
        gh = max(t[1] for t in group) - gy0 + 1
        fname = f"{map_name}_{tag}_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_tiles_tbx(gw, gh, [(x - gx0, y - gy0, z, layer, tile)
                                              for x, y, z, layer, tile in group]))
        placements.append(Placement(f"buildings/{fname}", gx0, gy0, gw, gh))
    return placements


def lattice_on_map(first: int, stop: int, step: int, limit: int) -> range:
    """The values first, first + step, ... below `stop` that are on the map, 0..limit.

    A polygon's whole bounding box used to be walked and what fell off the map
    thrown away afterwards. A military range mapped as one polygon is a hundred
    kilometres across, and a few thousand headstone-sized steps become billions
    of Shapely calls. The values are the same ones on the same lattice; the ones
    below 0 or at `limit` and past are simply never visited."""
    if first < 0:
        first += -(-(-first) // step) * step         # the first value that is 0 or more
    return range(first, min(stop, limit), step)


def _blocked_mask(ground: np.ndarray) -> np.ndarray:
    out = np.zeros(ground.shape[:2], dtype=bool)
    for colour in BLOCKED:
        out |= same_colour(ground, colour)
    return out


def _polygons(areas, category: str) -> list:
    """The land-use polygons of one category, in tiles."""
    return [shape for shape, props in getattr(areas, "_items", [])
            if (props.get("category") or "") == category and not shape.is_empty]


def place_props(out_dir: str, map_name: str, bdir: str, occupied: np.ndarray,
                areas, metres_per_tile: float,
                seed: int = 0x6FADE) -> tuple[list, dict]:
    """Headstones in the cemeteries and stores on the army bases.

    Returns (placements, counts). Tiles already taken by a building, a road or
    water are left alone, and anything put down is cleared of trees so a
    headstone does not grow out of a pine.
    """
    from shapely.geometry import Point

    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    counts = {"graves": 0, "dumps": 0, "picnic_tables": 0}
    if not os.path.exists(bmp) or areas is None:
        return [], counts
    cemeteries = _polygons(areas, "cemetery")
    bases = _polygons(areas, "military")
    parks = _polygons(areas, "park") + _polygons(areas, "playground")
    if not cemeteries and not bases and not parks:
        return [], counts

    ground = read_rgb(bmp)
    height, width = ground.shape[:2]
    blocked = _blocked_mask(ground)
    blocked |= occupied[:height, :width]
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    veg = read_rgb(veg_path) if os.path.exists(veg_path) else None
    rng = random.Random(seed)
    tiles: list[tuple[int, int, int, str, str]] = []

    def put(x: int, y: int, tile: str) -> bool:
        if not (0 <= x < width and 0 <= y < height) or blocked[y, x]:
            return False
        blocked[y, x] = True
        occupied[y, x] = True
        if veg is not None:
            veg[y, x] = C.VEG_NOTHING
        tiles.append((x, y, 0, LAYER, tile))
        return True

    def step(metres: float) -> int:
        return max(1, int(round(metres / max(0.05, metres_per_tile))))

    across, down = step(GRAVE_SPACING_M), step(GRAVE_ROW_M)
    for poly in cemeteries:
        if counts["graves"] >= MAX_GRAVES:
            break
        minx, miny, maxx, maxy = (int(v) for v in poly.bounds)
        for y in lattice_on_map(miny + down, maxy, down, height):
            row = (y - (miny + down)) // down + 1     # counted from the polygon's own edge
            if row % PATH_EVERY_ROWS == 0:
                continue                       # a way through the plots
            for x in lattice_on_map(minx + across, maxx, across, width):
                if counts["graves"] >= MAX_GRAVES:
                    break
                if not poly.contains(Point(x + 0.5, y + 0.5)):
                    continue
                roll = rng.random()
                if roll < ANGEL_SHARE:
                    tile = rng.choice(ANGELS)
                elif roll < ANGEL_SHARE + CROSS_SHARE:
                    tile = rng.choice(CROSSES)
                else:
                    tile = rng.choice(HEADSTONES)
                if put(x, y, tile):
                    counts["graves"] += 1

    gap = step(DUMP_EVERY_M)
    for poly in bases:
        if counts["dumps"] >= MAX_DUMPS:
            break
        if poly.area * metres_per_tile * metres_per_tile < DUMP_MIN_M2:
            continue
        minx, miny, maxx, maxy = (int(v) for v in poly.bounds)
        for y in lattice_on_map(miny + gap, maxy, gap, height):
            for x in lattice_on_map(minx + gap, maxx, gap, width):
                if counts["dumps"] >= MAX_DUMPS:
                    break
                if not poly.contains(Point(x + 0.5, y + 0.5)):
                    continue
                # A stack of stores: a short row of crates with a drum or two
                # at the end of it, as they are stacked on a real apron.
                run = rng.randint(2, 5)
                horizontal = rng.random() < 0.5
                placed = 0
                for k in range(run):
                    tile = rng.choice(DRUMS if k == run - 1 and rng.random() < 0.4
                                      else CRATES)
                    px = x + (k if horizontal else 0)
                    py = y + (0 if horizontal else k)
                    placed += bool(put(px, py, tile))
                if placed:
                    counts["dumps"] += 1

    pitch = step(PICNIC_SPACING_M)
    for poly in parks:
        if counts["picnic_tables"] >= MAX_PICNIC_TABLES:
            break
        if poly.area * metres_per_tile * metres_per_tile < PICNIC_MIN_M2:
            continue
        minx, miny, maxx, maxy = poly.bounds
        x_start = int(minx) + pitch // 2
        y_start = int(miny) + pitch // 2
        for gy, y in enumerate(range(y_start, int(maxy), pitch)):
            for gx, x in enumerate(range(x_start, int(maxx), pitch)):
                if counts["picnic_tables"] >= MAX_PICNIC_TABLES:
                    break
                if rng.random() >= 0.72:
                    continue
                cx = x + rng.randint(-max(1, pitch // 5), max(1, pitch // 5))
                cy = y + rng.randint(-max(1, pitch // 5), max(1, pitch // 5))
                orient = ("W", "N")[(gx + gy + rng.randrange(2)) % 2]
                definition = catalog.FURNITURE["picnic_table"][orient]
                footprint = []
                for offset, tile in definition.items():
                    dx, dy = (int(value) for value in offset.split(","))
                    px, py = cx + dx, cy + dy
                    if (not (0 <= px < width and 0 <= py < height)
                            or blocked[py, px]
                            or not poly.contains(Point(px + 0.5, py + 0.5))):
                        footprint = []
                        break
                    footprint.append((px, py, tile))
                if len(footprint) != len(definition):
                    continue
                for px, py, tile in footprint:
                    put(px, py, tile)
                counts["picnic_tables"] += 1

    if not tiles:
        return [], counts
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return _write_lots(bdir, map_name, "props", tiles), counts


# --- vignettes ---------------------------------------------------------------
#
# Three scenes, not land uses: the road out of town held by the army, the
# school turned into an evacuation centre, a main road stopped with whatever
# could be dragged across it. A scene is a handful of the same props the
# headstones above are made of, put where the story of the map is.

CARRIAGEWAY = {C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT, C.DARKEST_ASPHALT,
               C.DARK_POTHOLE, C.LIGHT_POTHOLE}
# location_military_generic_01_040-047: a barricade is four tiles long, one
# segment per tile, and the two facings are the run along x and the run along y.
BARRICADE_X = ["location_military_generic_01_044", "location_military_generic_01_045",
               "location_military_generic_01_046", "location_military_generic_01_047"]
BARRICADE_Y = ["location_military_generic_01_043", "location_military_generic_01_042",
               "location_military_generic_01_041", "location_military_generic_01_040"]
MAIN_ROAD = 6              # primary and above (generator.osm.ROAD_HIERARCHY_CODES)
CHECKPOINT_AT = 24         # tiles: a road ending this near the border leaves town
CHECKPOINT_APART = 12      # tiles between two checkpoints on the same road end
ROAD_BLOCK_SPACING = 60    # tiles between blocks along a main road
MAX_CHECKPOINTS = 4
MAX_ROAD_BLOCKS = 6
MAX_EVAC_CENTRES = 8
EVAC_PROPS = 4             # crates and drums in a school yard


def _carriageway(ground: np.ndarray, x: int, y: int) -> bool:
    return tuple(ground[y, x]) in CARRIAGEWAY


def _run(ground: np.ndarray, x: int, y: int, axis: str,
         width: int, height: int) -> list:
    """The contiguous carriageway squares through (x, y), in order."""
    if not _carriageway(ground, x, y):
        return []
    step = (1, 0) if axis == "x" else (0, 1)
    cells = [(x, y)]
    for sign in (-1, 1):
        nx, ny = x + step[0] * sign, y + step[1] * sign
        while 0 <= nx < width and 0 <= ny < height and _carriageway(ground, nx, ny):
            if sign < 0:
                cells.insert(0, (nx, ny))
            else:
                cells.append((nx, ny))
            nx += step[0] * sign
            ny += step[1] * sign
    return cells


def _stop_the_road(ground: np.ndarray, width: int, height: int, x: int, y: int,
                   put, rng) -> int:
    """Barriers across the carriageway through (x, y), crates in the gaps.

    A road is stopped across it and not along it: the road runs one way and the
    barrier lies across that, which is what "a roadblock" means. The four-tile
    barricade is used where the carriageway is at least that wide; a narrower
    one gets crates, because half a barricade hanging over the pavement is not
    a scene anybody meant to make.
    """
    run_x = _run(ground, x, y, "x", width, height)
    run_y = _run(ground, x, y, "y", width, height)
    if not run_x and not run_y:
        return 0
    road_along_x = len(run_x) > len(run_y)
    across = run_y if road_along_x else run_x
    barrier = BARRICADE_Y if road_along_x else BARRICADE_X
    placed = 0
    if len(across) >= len(barrier):
        for (bx, by), tile in zip(across[:len(barrier)], barrier):
            placed += put(bx, by, tile, road=True)
        spare = across[len(barrier):]
    else:
        spare = across
    for bx, by in spare[:2]:
        placed += put(bx, by, rng.choice(CRATES), road=True)
    return placed


def _edge_exits(ground: np.ndarray, width: int, height: int) -> list:
    """A point on the carriageway that comes closest to each border.

    Where a road leaves the map is where a checkpoint belongs. A padded map -
    one built to a minimum size, so the town sits inside it - has no road at
    the border at all, and then the single road that runs furthest out of the
    town is the way out: the same gate, seen from the street.
    """
    mask = np.zeros((height, width), dtype=bool)
    for colour in CARRIAGEWAY:
        mask |= np.all(ground == np.array(colour, dtype=ground.dtype), axis=2)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return []
    sides = [xs, ys, width - 1 - xs, height - 1 - ys]

    def pick(near) -> tuple[int, int]:
        closest = int(near.min())
        index = np.nonzero(near == closest)[0]
        middle = index[len(index) // 2]
        return int(xs[middle]), int(ys[middle])

    if min(int(side.min()) for side in sides) > CHECKPOINT_AT:
        return [pick(np.minimum.reduce(sides))]
    return [pick(side) for side in sides if int(side.min()) <= CHECKPOINT_AT]


def place_vignettes(out_dir: str, map_name: str, bdir: str, occupied: np.ndarray,
                    rows: list, road_hierarchy: np.ndarray | None = None,
                    seed: int = 0x5161) -> tuple[list, dict]:
    """A checkpoint on the way out of town, a school that became a refuge, and
    a main road stopped.

    Returns (placements, counts). Vignettes stand where nothing else does, but
    a barricade is meant to stand on the carriageway - it is the one prop here
    that goes on the road - so the occupancy test is the whole of the "is it
    taken" question, and the ground only decides what may be put where.
    """
    counts = {"checkpoints": 0, "road_blocks": 0, "evac_centres": 0,
              "vignette_props": 0}
    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(bmp) or occupied is None:
        return [], counts
    ground = read_rgb(bmp)
    height, width = ground.shape[:2]
    blocked = occupied[:height, :width].copy()
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    veg = read_rgb(veg_path) if os.path.exists(veg_path) else None
    rng = random.Random(seed)
    tiles: list = []

    def put(x: int, y: int, tile: str, road: bool = False) -> int:
        if not (0 <= x < width and 0 <= y < height) or blocked[y, x]:
            return 0
        if not road and _carriageway(ground, x, y):
            return 0
        blocked[y, x] = True
        occupied[y, x] = True
        if veg is not None:
            veg[y, x] = C.VEG_NOTHING
        tiles.append((x, y, 0, LAYER, tile))
        return 1

    seen: list = []
    for x, y in _edge_exits(ground, width, height):
        if counts["checkpoints"] >= MAX_CHECKPOINTS:
            break
        if any(abs(x - sx) < CHECKPOINT_APART and abs(y - sy) < CHECKPOINT_APART
               for sx, sy in seen):
            continue
        placed = _stop_the_road(ground, width, height, x, y, put, rng)
        if not placed:
            continue
        seen.append((x, y))
        counts["checkpoints"] += 1
        counts["vignette_props"] += placed

    if road_hierarchy is not None:
        main = road_hierarchy[:height, :width] >= MAIN_ROAD
        ys, xs = np.nonzero(main)
        picked: list = []
        for y, x in zip(ys[::5].tolist(), xs[::5].tolist()):
            if counts["road_blocks"] >= MAX_ROAD_BLOCKS:
                break
            if any(abs(x - px) < ROAD_BLOCK_SPACING and abs(y - py) < ROAD_BLOCK_SPACING
                   for px, py in picked):
                continue
            placed = _stop_the_road(ground, width, height, x, y, put, rng)
            if not placed:
                continue
            picked.append((x, y))
            counts["road_blocks"] += 1
            counts["vignette_props"] += placed

    for row in rows or []:
        if counts["evac_centres"] >= MAX_EVAC_CENTRES:
            break
        if row.get("kind") != "school":
            continue
        x0, y0 = int(row["tile_x"]), int(row["tile_y"])
        wide, tall = int(row["width"]), int(row["height"])
        spots: list = []
        for distance in (1, 2, 3):
            spots.extend((sx, sy) for sx, sy in _ring(x0, y0, wide, tall, distance)
                         if 0 <= sx < width and 0 <= sy < height
                         and not blocked[sy, sx]
                         and not _carriageway(ground, sx, sy))
            if len(spots) >= EVAC_PROPS:
                break
        if not spots:
            continue
        rng.shuffle(spots)
        made = sum(put(sx, sy, rng.choice(DRUMS if rng.random() < 0.3 else CRATES))
                   for sx, sy in spots[:EVAC_PROPS])
        if made:
            counts["evac_centres"] += 1
            counts["vignette_props"] += made

    if not tiles:
        return [], counts
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return _write_lots(bdir, map_name, "vignettes", tiles), counts
