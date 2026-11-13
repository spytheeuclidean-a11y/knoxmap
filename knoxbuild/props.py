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

# location_community_cemetary_01: stone headstones, wooden crosses, filled
# grave mounds and angel statues, verified against BuildingFurniture.txt.
# Tile names are spelled the way BuildingEd's own config spells them, three
# digits: BuildingFurniture.txt carries every one of these sheets that way and
# never a short form, and a tbx that names a tile the pack does not have is
# dropped without a word.
HEADSTONES_N = [
    "location_community_cemetary_01_000",
    "location_community_cemetary_01_002",
    "location_community_cemetary_01_004",
    "location_community_cemetary_01_008",
]
HEADSTONES_W = [
    "location_community_cemetary_01_001",
    "location_community_cemetary_01_003",
    "location_community_cemetary_01_005",
    "location_community_cemetary_01_009",
]
HEADSTONES = HEADSTONES_N + HEADSTONES_W
CROSSES_N = [
    "location_community_cemetary_01_022",
    "location_community_cemetary_01_039",
]
CROSSES_W = [
    "location_community_cemetary_01_023",
    "location_community_cemetary_01_038",
]
CROSSES = CROSSES_N + CROSSES_W
ANGELS = [
    "location_community_cemetary_01_011",
    "location_community_cemetary_01_012",
    "location_community_cemetary_01_013",
    "location_community_cemetary_01_014",
]
GRAVE_MOUND_N = (
    "location_community_cemetary_01_043",
    "location_community_cemetary_01_042",
)
GRAVE_MOUND_W = (
    "location_community_cemetary_01_040",
    "location_community_cemetary_01_041",
)
CEMETERY_PATH_FLOORS = (
    "floors_exterior_tilesandstone_01_005",
    "floors_exterior_tilesandstone_01_007",
)
CEMETERY_PLAZA_FLOOR = "floors_exterior_tilesandstone_01_004"
CEMETERY_PLAZA_CENTER = "floors_exterior_tilesandstone_01_006"
CEMETERY_BENCH_N = (
    "furniture_seating_outdoor_01_011",
    "furniture_seating_outdoor_01_010",
)
CEMETERY_BENCH_W = (
    "furniture_seating_outdoor_01_009",
    "furniture_seating_outdoor_01_008",
)
CROSS_SHARE = 0.10         # of the graves, a wooden cross instead of a stone
MONUMENT_SHARE = 0.05      # paved 2x2 family plot with statue or twin stones
MOUND_SHARE = 0.65         # filled earth mound in front of the headstone
GRAVE_SPACING_M = 2.0      # along a row
GRAVE_ROW_M = 3.0          # between rows
SECTION_ROWS = 4           # rows per block before a paved cross-walkway
MAX_GRAVES = 40000         # a whole county of churchyards, and no more

# location_military_generic_01: ammunition crates and fuel drums, and nothing
# with English writing on it - the same base has to read as a base in any
# country the map is of. 000-005 and 008-013 are the crates and 006-007 and
# 014-015 the drums; 016-021 are ARMY PROPERTY and KEEP OUT placards, which
# stand on a wall rather than a yard, and 022-023 are two-tile lockers.
CRATES = ["location_military_generic_01_000", "location_military_generic_01_001",
          "location_military_generic_01_002", "location_military_generic_01_008",
          "location_military_generic_01_009", "location_military_generic_01_011"]
DRUMS = ["location_military_generic_01_006", "location_military_generic_01_007",
         "location_military_generic_01_014", "location_military_generic_01_015"]
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


def _place_cemetery(
    poly,
    width: int,
    height: int,
    across: int,
    row_pitch: int,
    budget: int,
    blocked: np.ndarray,
    put_layer,
    rng: random.Random,
    point_cls,
) -> int:
    """Lay out one cemetery with paved paths, a focal plaza, and neat grave rows."""
    minx, miny, maxx, maxy = (int(v) for v in poly.bounds)
    x0, y0 = max(0, minx), max(0, miny)
    x1, y1 = min(width, maxx), min(height, maxy)
    poly_w, poly_h = x1 - x0, y1 - y0
    if poly_w < 3 or poly_h < 3 or budget <= 0:
        return 0

    def can_use(x: int, y: int) -> bool:
        return (
            0 <= x < width
            and 0 <= y < height
            and not blocked[y, x]
            and poly.contains(point_cls(x + 0.5, y + 0.5))
        )

    orient_n = poly_w >= poly_h
    path_floor = rng.choice(CEMETERY_PATH_FLOORS)
    placed_graves = 0

    # 1. Central memorial plaza on medium/large cemeteries with focal statue & benches.
    if poly_w >= 14 and poly_h >= 14:
        radius = 2 if (poly_w >= 22 and poly_h >= 22) else 1
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        plaza_cells = [
            (px, py)
            for py in range(cy - radius, cy + radius + 1)
            for px in range(cx - radius, cx + radius + 1)
        ]
        if all(can_use(px, py) for px, py in plaza_cells):
            for px, py in plaza_cells:
                if px == cx and py == cy:
                    floor_tile = CEMETERY_PLAZA_CENTER
                elif abs(px - cx) == radius or abs(py - cy) == radius:
                    floor_tile = path_floor
                else:
                    floor_tile = CEMETERY_PLAZA_FLOOR
                put_layer(px, py, "Floor", floor_tile, block=False)
            # Central angel statue facing down the main avenue.
            statue = ANGELS[2] if orient_n else ANGELS[3]
            put_layer(cx, cy, LAYER, statue, block=True)
            if radius == 2:
                if can_use(cx - 1, cy - 2) and can_use(cx, cy - 2):
                    put_layer(cx - 1, cy - 2, LAYER, CEMETERY_BENCH_N[0], block=True)
                    put_layer(cx, cy - 2, LAYER, CEMETERY_BENCH_N[1], block=True)
                if can_use(cx - 2, cy - 1) and can_use(cx - 2, cy):
                    put_layer(cx - 2, cy - 1, LAYER, CEMETERY_BENCH_W[0], block=True)
                    put_layer(cx - 2, cy, LAYER, CEMETERY_BENCH_W[1], block=True)
            for px, py in plaza_cells:
                blocked[py, px] = True

    # 2. Central paved avenue running perpendicular to the grave rows.
    if poly_w >= 10 and poly_h >= 10:
        if orient_n:
            ave_w = 2 if poly_w >= 18 else 1
            ax0 = (x0 + x1) // 2 - (ave_w // 2)
            for py in range(y0 + 1, y1 - 1):
                for px in range(ax0, ax0 + ave_w):
                    if can_use(px, py):
                        put_layer(px, py, "Floor", path_floor, block=True)
        else:
            ave_h = 2 if poly_h >= 18 else 1
            ay0 = (y0 + y1) // 2 - (ave_h // 2)
            for px in range(x0 + 1, x1 - 1):
                for py in range(ay0, ay0 + ave_h):
                    if can_use(px, py):
                        put_layer(px, py, "Floor", path_floor, block=True)

    # 3. Neat rows of headstones, crosses, filled grave mounds, and paved cross-paths.
    headstones = HEADSTONES_N if orient_n else HEADSTONES_W
    crosses = CROSSES_N if orient_n else CROSSES_W
    mound = GRAVE_MOUND_N if orient_n else GRAVE_MOUND_W
    tall_stone = headstones[0]
    monument_angel = ANGELS[2] if orient_n else ANGELS[3]

    def place_family_monument(gx: int, gy: int) -> bool:
        """A paved 2x2 family plot with an angel statue or twin tall stones."""
        footprint = [(gx, gy), (gx + 1, gy), (gx, gy + 1), (gx + 1, gy + 1)]
        if not all(can_use(px, py) for px, py in footprint):
            return False
        for px, py in footprint:
            put_layer(px, py, "Floor", CEMETERY_PLAZA_FLOOR, block=False)
        if rng.random() < 0.5:
            put_layer(gx, gy, LAYER, monument_angel, block=False)
            if orient_n:
                put_layer(gx, gy + 1, "FloorFurniture", mound[1], block=False)
            else:
                put_layer(gx + 1, gy, "FloorFurniture", mound[1], block=False)
        else:
            put_layer(gx, gy, LAYER, tall_stone, block=False)
            if orient_n:
                put_layer(gx + 1, gy, LAYER, tall_stone, block=False)
                put_layer(gx, gy + 1, "FloorFurniture", mound[1], block=False)
                put_layer(gx + 1, gy + 1, "FloorFurniture", mound[1], block=False)
            else:
                put_layer(gx, gy + 1, LAYER, tall_stone, block=False)
                put_layer(gx + 1, gy, "FloorFurniture", mound[1], block=False)
                put_layer(gx + 1, gy + 1, "FloorFurniture", mound[1], block=False)
        for px, py in footprint:
            blocked[py, px] = True
        return True

    def place_single_grave(gx: int, gy: int) -> bool:
        fx, fy = (gx, gy + 1) if orient_n else (gx + 1, gy)
        if not (can_use(gx, gy) and can_use(fx, fy)):
            return False
        stone = rng.choice(crosses if rng.random() < CROSS_SHARE else headstones)
        if rng.random() < MOUND_SHARE:
            put_layer(gx, gy, "FloorFurniture", mound[0], block=False)
            put_layer(fx, fy, "FloorFurniture", mound[1], block=False)
        put_layer(gx, gy, LAYER, stone, block=True)
        put_layer(fx, fy, "", "", block=True)
        return True

    if orient_n:
        y = y0 + 1
        row_idx = 0
        while y + 1 < y1 and placed_graves < budget:
            if row_idx > 0 and row_idx % SECTION_ROWS == 0:
                for px in range(x0 + 1, x1 - 1):
                    if can_use(px, y):
                        put_layer(px, y, "Floor", path_floor, block=True)
                y += 2
                row_idx = 0
                continue
            x = x0 + 1
            while x < x1 - 1 and placed_graves < budget:
                if x + 1 < x1 - 1 and rng.random() < MONUMENT_SHARE and place_family_monument(x, y):
                    placed_graves += 1
                    x += max(across, 3)
                    continue
                if place_single_grave(x, y):
                    placed_graves += 1
                x += across
            y += row_pitch
            row_idx += 1
    else:
        x = x0 + 1
        col_idx = 0
        while x + 1 < x1 and placed_graves < budget:
            if col_idx > 0 and col_idx % SECTION_ROWS == 0:
                for py in range(y0 + 1, y1 - 1):
                    if can_use(x, py):
                        put_layer(x, py, "Floor", path_floor, block=True)
                x += 2
                col_idx = 0
                continue
            y = y0 + 1
            while y < y1 - 1 and placed_graves < budget:
                if y + 1 < y1 - 1 and rng.random() < MONUMENT_SHARE and place_family_monument(x, y):
                    placed_graves += 1
                    y += max(across, 3)
                    continue
                if place_single_grave(x, y):
                    placed_graves += 1
                y += across
            x += row_pitch
            col_idx += 1

    return placed_graves


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

    def put_layer(x: int, y: int, layer: str, tile: str, *,
                  block: bool = True) -> bool:
        if not (0 <= x < width and 0 <= y < height) or blocked[y, x]:
            return False
        if block:
            blocked[y, x] = True
        occupied[y, x] = True
        if veg is not None:
            veg[y, x] = C.VEG_NOTHING
        if tile:
            tiles.append((x, y, 0, layer, tile))
        return True

    def put(x: int, y: int, tile: str) -> bool:
        return put_layer(x, y, LAYER, tile)

    def step(metres: float) -> int:
        return max(1, int(round(metres / max(0.05, metres_per_tile))))

    across = max(2, step(GRAVE_SPACING_M))
    row_pitch = max(3, step(GRAVE_ROW_M))
    for poly in cemeteries:
        if counts["graves"] >= MAX_GRAVES:
            break
        counts["graves"] += _place_cemetery(
            poly, width, height, across, row_pitch,
            MAX_GRAVES - counts["graves"],
            blocked, put_layer, rng, Point,
        )

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
ROAD_BLOCK_SPACING = 60    # tiles between two blocks on roads that end apart
MAX_CHECKPOINTS = 4
MAX_ROAD_BLOCKS = 2        # one or two, at the ends of main roads - not a cordon
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


def _runs(mask: np.ndarray, axis: int) -> tuple[np.ndarray, np.ndarray]:
    """For a road mask, how long the run each square sits in is, and whether it
    ends that run - measured along `axis` (1 is x, 0 is y)."""
    import numpy as np

    m = mask if axis == 1 else mask.T
    height, width = m.shape
    length = np.zeros_like(m, dtype=np.int32)
    ends = np.zeros_like(m)
    for row in range(height):
        line = m[row]
        if not line.any():
            continue
        edges = np.diff(line.astype(np.int8), prepend=0, append=0)
        starts = np.nonzero(edges == 1)[0]
        stops = np.nonzero(edges == -1)[0] - 1
        for first, last in zip(starts.tolist(), stops.tolist()):
            length[row, first:last + 1] = last - first + 1
            if last - first + 1 >= 8:            # a road, not a stub
                ends[row, first] = True
                ends[row, last] = True
    if axis == 1:
        return length, ends
    return length.T, ends.T


def _road_ends(main: np.ndarray, margin: int = 2) -> list[tuple[int, int]]:
    """Where a main road stops: the square that ends a run longer than the road
    is wide, and that runs along the road rather than across it.

    Counting neighbours only finds the end of a one-tile lane - the last column
    of a four-lane road has three neighbours, all of them road - and looking one
    way along an axis flags the kerb row of every wide road. What separates an
    end from a kerb is which run ends: the long one is the road.
    """
    import numpy as np

    length_x, ends_x = _runs(main, 1)
    length_y, ends_y = _runs(main, 0)
    ends = main & np.where(length_x >= length_y, ends_x, ends_y)
    height, width = main.shape
    inside = np.zeros_like(main)
    inside[margin:-margin, margin:-margin] = True   # the border is the checkpoint's
    ys, xs = np.nonzero(ends & inside)
    return list(zip(xs.tolist(), ys.tolist()))


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
        # A block belongs where a road actually stops, not at intervals along
        # it: a cordon every few hundred metres reads as scenery, and the point
        # of the scene is that this road, here, is the end of the way.
        ends = _road_ends(main)
        middle_x, middle_y = width / 2, height / 2
        ends.sort(key=lambda p: -((p[0] - middle_x) ** 2 + (p[1] - middle_y) ** 2))
        picked: list = []
        for x, y in ends:
            if counts["road_blocks"] >= MAX_ROAD_BLOCKS:
                break
            # Two ends of the same road are the two ends of the same road: the
            # spacing is a distance, not a box, or the second is always refused.
            if any((x - px) ** 2 + (y - py) ** 2 < ROAD_BLOCK_SPACING ** 2
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
