"""The front and back of every house: path, stoop, drive, mailbox, bin, fence.

Knox County's houses have all of these and generated ones stood in unbroken
lawn with the front door opening onto grass. The door is only known once the
building is laid out, after the terrain was drawn, so they are painted into
the terrain and vegetation bitmaps here, starting from the renderer's
untouched copy of the ground (<map>_ground_base.bmp) so that building again
does not keep old paths. Back-yard fences are returned as lines for the fence
builder (knoxbuild/fences.py).

Measured on the vanilla map's outdoor squares: stone slabs
(floors_exterior_tilesandstone_01) are its commonest outdoor floor after
grass, dark tarmac drives the next, then wooden fences.
"""
from __future__ import annotations

import os
import random
import re
import shutil
from collections import deque

import numpy as np
from PIL import Image

from generator import pz_colors as C

from .bitmaps import read_rgb, same_colour

# A farmhouse stands well back from its road, and its drive and front path run
# that far. The path stops at the drive when it meets it first. On Piqua 383
# houses were a median 61 tiles from the pavement with no straight drive.
PATH_MAX_TILES = 120
WALK_MAX_TILES = 20
NON_HOME_WALK_MAX_TILES = 45
GARAGE_DRIVE_MAX_TILES = 40
# A house the terrain already gave a drive to (generator/rendering/homesteads.py:
# a house in the woods) gets no second one beside it: tarmac this near its walls.
DRIVE_THERE_TILES = 3
# Who gets a front path, a stoop and a porch light. Only houses get the drive
# and the yard: flats and public buildings have lots of their own (and get a
# modest concrete apron round their walls rather than flooding the block).
FRONT_PATH_KINDS = (
    "house", "apartment", "church", "civic", "medical", "library",
    "shop", "office", "offices", "retail", "mall", "restaurant",
    "school", "hotel", "police", "fire", "fire_police", "military", "stadium",
)
BUILDING_APRON_MIN = 2
BUILDING_APRON_MAX = 3
MERGE_DOOR_MIN_GAP = 4
MERGE_DOOR_MAX_GAP = 18
MERGE_DOOR_SHARE = 0.65
DRIVE_WIDTH = 3
DRIVE_EXTRA = 5          # how far the drive runs past the front of the house
YARD_DEPTH = 9           # back yard, from the back wall to the back fence
YARD_MIN_DEPTH = 4
YARD_SIDE = 2            # how far the fence stands out past the house's sides
PAVED = (C.PALE_CONCRETE, C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
# Ground the yard props do not stand on: paving, drives and the patio stone.
LAWNLESS = PAVED + (C.PAVING_STONE, C.LIGHT_ASPHALT)
CROSSABLE = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DIRT,
             C.DIRT_ROWS_H, C.DIRT_ROWS_V)
YARD_FENCE_STYLES = ("tall_wooden", "short_wooden", "white_picket", "short_chainlink")
YARD_ARCHETYPES = ("family", "grill", "laundry", "garden", "bare")
YARD_ARCHETYPE_WEIGHTS = (30, 22, 18, 18, 12)
YARD_FENCE_WEIGHTS = (40, 30, 18, 12)
FENCED_SHARE = 0.85
# The dog's house and the kids' swing: not every yard, but enough of them that
# a street reads as lived in rather than laid out.
DOG_HOUSE_SHARE = 0.45


def _rule_ready(label: str) -> bool:
    """Whether the map tools' Rules.txt carries one of our rules yet.

    A colour with no rule behind it is dropped with a warning, so an install
    set up before these props existed gets neither until Setup runs again.
    """
    try:
        import knoxpaths
        rules = knoxpaths.mapping_tools_dir() / "config" / "Rules.txt"
        return f"KnoxMap road {label}" in rules.read_text(encoding="utf-8", errors="replace")
    except Exception:      # noqa: BLE001 - no tools, no props
        return False


def yard_plan(bx0: int, by0: int) -> tuple[str, bool, str]:
    """(fence style, fenced, archetype) for the house at bx0,by0.

    Stable per house so a rebuild is the same map, and independent of the
    order houses are visited in.
    """
    rng = random.Random((bx0 * 73856093) ^ (by0 * 19349663) ^ 0x9E3779B9)
    style = rng.choices(YARD_FENCE_STYLES, weights=YARD_FENCE_WEIGHTS)[0]
    fenced = rng.random() < FENCED_SHARE
    archetype = rng.choices(YARD_ARCHETYPES, weights=YARD_ARCHETYPE_WEIGHTS)[0]
    return style, fenced, archetype

# A light by the front door. Knox County has one on 92% of its houses and a
# railing on 71%; generated ones had a light on 1%, which is most of why they
# read as unfinished from the street. Seven in ten of the game's sit within a
# tile of a door, all but 3% on the ground outside the wall rather than on the
# building's own tiles, so that is where these go.
#
# Which sprite goes on which wall was read off the vanilla map, not guessed:
# for every outdoor light standing outside a house with house tiles on exactly
# one side, that side. The five sets below each came back 96-100% one-sided
# over 60 to 140 sightings. The key is the side the house is on, seen from the
# light's own tile.
PORCH_LIGHTS = [
    {"N": "lighting_outdoor_01_24", "W": "lighting_outdoor_01_25",
     "S": "lighting_outdoor_01_28", "E": "lighting_outdoor_01_29"},
    {"N": "lighting_outdoor_01_26", "W": "lighting_outdoor_01_27",
     "S": "lighting_outdoor_01_30", "E": "lighting_outdoor_01_31"},
    {"N": "lighting_outdoor_01_32", "W": "lighting_outdoor_01_33",
     "S": "lighting_outdoor_01_36", "E": "lighting_outdoor_01_37"},
    {"N": "lighting_outdoor_01_34", "W": "lighting_outdoor_01_35",
     "S": "lighting_outdoor_01_39", "E": "lighting_outdoor_01_38"},
    {"N": "lighting_outdoor_01_40", "W": "lighting_outdoor_01_41",
     "S": "lighting_outdoor_01_44", "E": "lighting_outdoor_01_45"},
]
PORCH_LIGHT_SHARE = 0.92
# The square the light stands on usually carries the house wall as well, and
# what is written last is drawn last: on the Furniture layer the wall went on
# top and the light was invisible. Every one of the 659 vanilla porch lights
# that shares a square with an exterior wall is written after it.
PORCH_LIGHT_LAYER = "WallFurniture"
# The side the house is on, from the tile the light stands on.
_SIDE = {(0, -1): "N", (0, 1): "S", (-1, 0): "W", (1, 0): "E"}


_OUTSIDE_DOORS_CACHE: dict[tuple[str, int], list[tuple[int, int, int, int]]] = {}
_OUTSIDE_WINDOWS_CACHE: dict[tuple[str, int], set[tuple[int, int]]] = {}


def _outside_windows(tbx_path: str) -> set[tuple[int, int]]:
    """(outside x, y) for every ground-floor exterior window in ``tbx_path``."""
    try:
        key = (tbx_path, os.stat(tbx_path).st_mtime_ns)
    except OSError:
        key = None
    if key is not None and key in _OUTSIDE_WINDOWS_CACHE:
        return _OUTSIDE_WINDOWS_CACHE[key]
    with open(tbx_path, encoding="utf-8") as f:
        text = f.read()
    first = text.split("<floor>", 2)
    if len(first) < 2:
        return set()
    floor = first[1]
    grid_text = re.search(r"<rooms>(.*?)</rooms>", floor, re.S)
    if not grid_text:
        return set()
    grid = [[int(v) for v in row.strip().strip(",").split(",")]
            for row in grid_text.group(1).strip().splitlines() if row.strip()]
    h, w = len(grid), len(grid[0])

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and grid[y][x] != 0

    found: set[tuple[int, int]] = set()
    for m in re.finditer(r'type="window"[^>]*? x="(\d+)" y="(\d+)" dir="([NW])"', floor):
        x, y, d = int(m.group(1)), int(m.group(2)), m.group(3)
        a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
        if inside(*a) != inside(*b):
            out = a if inside(*b) else b
            found.add((out[0], out[1]))
    if key is not None:
        _OUTSIDE_WINDOWS_CACHE[key] = found
    return found


def _outside_doors(tbx_path: str, skip_garage: bool = False) -> list[tuple[int, int, int, int]]:
    """(outside x, y, inside x, y) of each ground-floor outside door, front first.

    `skip_garage` leaves out the panels of a garage door: a house's front path
    goes to its front door, and its drive to the garage (_outside_garage_doors)."""
    try:
        key = (tbx_path, os.stat(tbx_path).st_mtime_ns, skip_garage)
    except OSError:
        key = None
    if key is not None and key in _OUTSIDE_DOORS_CACHE:
        return _OUTSIDE_DOORS_CACHE[key]
    with open(tbx_path, encoding="utf-8") as f:
        text = f.read()
    first = text.split("<floor>", 2)
    if len(first) < 2:
        return []
    floor = first[1]
    grid_text = re.search(r"<rooms>(.*?)</rooms>", floor, re.S)
    if not grid_text:
        return []
    grid = [[int(v) for v in row.strip().strip(",").split(",")]
            for row in grid_text.group(1).strip().splitlines() if row.strip()]
    h, w = len(grid), len(grid[0])

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and grid[y][x] != 0

    found = []
    garage = {str(t) for t in _catalog().GARAGE_DOOR} if skip_garage else ()
    for m in re.finditer(r'type="door"[^>]*? x="(\d+)" y="(\d+)" dir="([NW])"([^>]*)', floor):
        if garage and re.search(r'Tile="(\d+)"', m.group(4)) and                 re.search(r'Tile="(\d+)"', m.group(4)).group(1) in garage:
            continue
        x, y, d = int(m.group(1)), int(m.group(2)), m.group(3)
        a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
        if inside(*a) != inside(*b):
            out, into = (a, b) if inside(*b) else (b, a)
            found.append((out[0], out[1], into[0], into[1]))
    if key is not None:
        _OUTSIDE_DOORS_CACHE[key] = found
    return found


_GARAGE_DOORS_CACHE: dict = {}


def _catalog():
    from . import catalog
    return catalog


def _outside_garage_doors(tbx_path: str) -> list[tuple[int, int, int, int]]:
    """(outside x, y, inside x, y) of each ground-floor garage door panel of a
    house: the doors _widen_vehicle_entry cut, which the .tbx writes with the
    garage door tiles (catalog.GARAGE_DOOR). Empty for a house with none."""
    from . import catalog as C
    try:
        key = (tbx_path, os.stat(tbx_path).st_mtime_ns)
    except OSError:
        return []
    if key in _GARAGE_DOORS_CACHE:
        return _GARAGE_DOORS_CACHE[key]
    with open(tbx_path, encoding="utf-8") as f:
        text = f.read()
    first = text.split("<floor>", 2)
    found: list[tuple[int, int, int, int]] = []
    grid_text = re.search(r"<rooms>(.*?)</rooms>", first[1], re.S) if len(first) > 1 else None
    if grid_text:
        grid = [[int(v) for v in row.strip().strip(",").split(",")]
                for row in grid_text.group(1).strip().splitlines() if row.strip()]
        h, w = len(grid), len(grid[0])

        def inside(x, y):
            return 0 <= x < w and 0 <= y < h and grid[y][x] != 0

        garage = {str(t) for t in C.GARAGE_DOOR}
        for m in re.finditer(r'type="door"[^>]*? x="(\d+)" y="(\d+)" dir="([NW])"[^>]*? Tile="(\d+)"',
                             first[1]):
            if m.group(4) not in garage:
                continue
            x, y, d = int(m.group(1)), int(m.group(2)), m.group(3)
            a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
            if inside(*a) != inside(*b):
                out, into = (a, b) if inside(*b) else (b, a)
                found.append((out[0], out[1], into[0], into[1]))
    _GARAGE_DOORS_CACHE[key] = found
    return found


DOOR_FRONT_DEPTH = 2


def door_fronts(out_dir: str, rows: list[dict]) -> set[tuple[int, int]]:
    """The squares in front of every ground-floor outside door, DOOR_FRONT_DEPTH deep, as map
    tiles: where nothing that blocks (a tree, a fence) may stand."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        lists = list(pool.map(lambda r: _outside_doors(os.path.join(out_dir, "buildings", r["file"])), rows))
    out: set[tuple[int, int]] = set()
    for row, doors in zip(rows, lists):
        for ox, oy, ix, iy in doors:
            dx, dy = ox - ix, oy - iy
            for k in range(DOOR_FRONT_DEPTH):
                out.add((row["tile_x"] + ox + dx * k, row["tile_y"] + oy + dy * k))
    return out


def _pave_patio(ground, veg, crossable, claimed, cells, colour=C.PAVING_STONE):
    """Pave only unclaimed lawn so one home's patio cannot overwrite a neighbor's path."""
    h, w = crossable.shape
    paved = []
    for x, y in cells:
        if not (0 <= x < w and 0 <= y < h) or not crossable[y, x] or claimed[y, x]:
            continue
        ground[y, x] = colour
        if veg is not None:
            veg[y, x] = C.VEG_NOTHING
        paved.append((x, y))
    return paved


def _find_walk(sx: int, sy: int, dx: int, dy: int, w: int, h: int,
               paved_at, free, drive_tiles: set,
               max_steps: int = WALK_MAX_TILES):
    """Shortest walk from (sx, sy) to paved_at/drive, preferring straight runs."""
    if not free(sx, sy):
        return None, None
    prev = {(sx, sy): None}
    queue = deque([(sx, sy, 0)])
    end = None
    order = [(dx, dy)] + [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if d != (dx, dy)]
    while queue:
        x, y, n = queue.popleft()
        if paved_at[y * w + x]:
            end = (x, y)
            break
        if n >= max_steps:
            continue
        for ddx, ddy in order:
            nx, ny = x + ddx, y + ddy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in prev \
                    and (paved_at[ny * w + nx] or free(nx, ny)):
                prev[(nx, ny)] = (x, y)
                queue.append((nx, ny, n + 1))
    if end is None:
        return None, None
    walk = []
    step = prev[end]
    while step is not None:
        walk.append(step)
        step = prev[step]
    if walk and end not in drive_tiles:
        straight_walk = []
        for t in range(max(len(walk) + 4, 1)):
            if t >= max_steps:
                break
            tx, ty = sx + dx * t, sy + dy * t
            if not (0 <= tx < w and 0 <= ty < h):
                break
            if paved_at[ty * w + tx]:
                if straight_walk:
                    end = (tx, ty)
                    walk = list(reversed(straight_walk))
                break
            if not free(tx, ty):
                break
            straight_walk.append((tx, ty))
    return walk, end


_NON_HOME_BENCH_KINDS = frozenset({
    "apartment", "civic", "medical", "library", "school",
    "hotel", "shop", "mall", "restaurant", "office", "offices",
})
_SERVICE_CLUTTER_KINDS = frozenset({"shop", "retail", "mall", "restaurant", "barn"})
_DUMPSTER_KINDS = _NON_HOME_BENCH_KINDS | frozenset({"retail"})


def _place_orderly_seating(can_fn, clear_neighbors_fn, veg: np.ndarray,
                           tx: int, ty: int, rng: random.Random,
                           allow_loungers: bool = True) -> bool:
    """Place orderly outdoor seating: chairs facing each other across one empty
    tile, a neat line of chairs spaced by one, or parallel loungers."""
    mode = rng.randrange(3 if allow_loungers else 2)
    if mode == 0:
        # Two chairs facing each other across 1 clear tile.
        if rng.random() < 0.5:
            pts = ((tx, ty), (tx + 1, ty), (tx + 2, ty))
            if all(can_fn(*p) for p in pts) and clear_neighbors_fn(tx, ty) and clear_neighbors_fn(tx + 2, ty):
                veg[ty, tx] = C.CHAIR_E
                veg[ty, tx + 2] = C.CHAIR_W
                return True
        else:
            pts = ((tx, ty), (tx, ty + 1), (tx, ty + 2))
            if all(can_fn(*p) for p in pts) and clear_neighbors_fn(tx, ty) and clear_neighbors_fn(tx, ty + 2):
                veg[ty, tx] = C.CHAIR_S
                veg[ty + 2, tx] = C.CHAIR_N
                return True
        return False
    if mode == 1:
        # Line of 2-3 chairs spaced by 1 empty tile.
        if rng.random() < 0.5:
            slots = [0, 2, 4] if can_fn(tx + 4, ty) and clear_neighbors_fn(tx + 4, ty) else [0, 2]
            if all(can_fn(tx + s, ty) and clear_neighbors_fn(tx + s, ty) for s in slots) and can_fn(tx + 1, ty):
                for s in slots:
                    veg[ty, tx + s] = C.CHAIR_S
                return True
        else:
            slots = [0, 2, 4] if can_fn(tx, ty + 4) and clear_neighbors_fn(tx, ty + 4) else [0, 2]
            if all(can_fn(tx, ty + s) and clear_neighbors_fn(tx, ty + s) for s in slots) and can_fn(tx, ty + 1):
                for s in slots:
                    veg[ty + s, tx] = C.CHAIR_E
                return True
        return False
    # Two parallel deck-chair loungers separated by a 1-tile aisle.
    pts = ((tx, ty), (tx + 1, ty), (tx, ty + 1), (tx + 1, ty + 1), (tx, ty + 2), (tx + 1, ty + 2))
    if all(can_fn(*p) for p in pts) and clear_neighbors_fn(tx, ty) and clear_neighbors_fn(tx, ty + 2):
        veg[ty, tx] = C.TABLE_X0
        veg[ty, tx + 1] = C.TABLE_X1
        veg[ty + 2, tx] = C.TABLE_X0
        veg[ty + 2, tx + 1] = C.TABLE_X1
        return True
    return False


def _dress_non_home_surroundings(
    rows: list[dict],
    door_lists: dict,
    out_dir: str,
    ground: np.ndarray,
    veg: np.ndarray,
    w: int,
    h: int,
    occupied: np.ndarray,
    road_at: np.ndarray,
    paved_at: np.ndarray,
    free,
    fronts: set[tuple[int, int]] | None,
) -> None:
    """Place foundation hedges, flower beds, bins, benches, patio seating,
    dumpsters, service clutter, litter, and shade trees around non-residential
    buildings so commercial, apartment, and civic blocks feel lived in."""
    from .works import _dumpster

    bench_ready = _rule_ready("Bench")
    door_clear = fronts or set()

    def can_veg(x: int, y: int) -> bool:
        if not (0 <= x < w and 0 <= y < h):
            return False
        if (x, y) in door_clear or road_at[y * w + x] or occupied[y, x]:
            return False
        if tuple(veg[y, x]) != C.VEG_NOTHING:
            return False
        g = tuple(ground[y, x])
        return g in CROSSABLE or g in PAVED

    def place_veg(x: int, y: int, colour: tuple[int, int, int]) -> bool:
        if not can_veg(x, y):
            return False
        veg[y, x] = colour
        return True

    def is_grass(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and tuple(ground[y, x]) in CROSSABLE

    def is_paved(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and (paved_at[y * w + x] or tuple(ground[y, x]) in PAVED)

    for row in rows:
        kind = row.get("kind", "")
        # A hangar stands on the apron, not in a garden: the foundation
        # planting put a bed of shrubs and flowers against the wall an
        # aircraft is rolled through.
        if kind in ("house", "garage", "industrial", "hangar"):
            continue
        bx0, by0 = row["tile_x"], row["tile_y"]
        bw, bh = row["width"], row["height"]
        if bw < 3 or bh < 3:
            continue
        doors = door_lists.get(row["file"], [])
        tbx_file = os.path.join(out_dir, "buildings", row["file"])
        window_tiles = {(bx0 + wx, by0 + wy) for wx, wy in _outside_windows(tbx_file)} if os.path.isfile(tbx_file) else set()
        nrng = random.Random((bx0 * 73856093) ^ (by0 * 19349663) ^ 0xA5A5A5A5)
        bin_spots: list[tuple[int, int]] = []

        # 1. Entrance bins and benches flanking doors.
        if doors:
            for ox, oy, ix, iy in doors[:3]:
                dx, dy = ox - ix, oy - iy
                px, py = -dy, dx
                sx, sy = bx0 + ox, by0 + oy
                if nrng.random() < 0.90:
                    sides = [(-2, 2), (2, -2)]
                    for k in nrng.choice(sides) + (-3, 3):
                        bx_, by_ = sx + px * k, sy + py * k
                        if (bx_, by_) not in window_tiles and place_veg(bx_, by_, C.BIN):
                            bin_spots.append((bx_, by_))
                            break
                if bench_ready and kind in _NON_HOME_BENCH_KINDS and nrng.random() < 0.75:
                    bench = C.BENCH_X if py == 0 else C.BENCH_Y
                    for k in (2, -3, 3, -4, 4):
                        ax, ay = sx + px * k, sy + py * k
                        bx_, by_ = ax + px, ay + py
                        if (can_veg(ax, ay) and can_veg(bx_, by_)
                                and (ax, ay) not in window_tiles
                                and (bx_, by_) not in window_tiles
                                and is_paved(ax, ay) and is_paved(bx_, by_)):
                            veg[ay, ax] = bench[0]
                            veg[by_, bx_] = bench[1]
                            break

        # 2. Organic foundation hedges and flower beds on grass hugging the apron/walls.
        ring_min, ring_max = 1, BUILDING_APRON_MAX + 1
        candidates: list[tuple[int, int]] = []
        for y in range(max(0, by0 - ring_max), min(h, by0 + bh + ring_max)):
            for x in range(max(0, bx0 - ring_max), min(w, bx0 + bw + ring_max)):
                dist = max(bx0 - x, x - (bx0 + bw - 1), by0 - y, y - (by0 + bh - 1), 0)
                if not ring_min <= dist <= ring_max:
                    continue
                if not is_grass(x, y) or not can_veg(x, y):
                    continue
                if dist == 1 or any(
                    0 <= x + nx < w and 0 <= y + ny < h
                    and (is_paved(x + nx, y + ny) or occupied[y + ny, x + nx])
                    for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1))
                ):
                    candidates.append((x, y))
        if candidates:
            cx, cy = bx0 + bw / 2, by0 + bh / 2
            import math
            candidates.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
            cand_set = set(candidates)
            i = nrng.randrange(3)
            while i < len(candidates):
                run_len = nrng.randint(2, 5)
                colour = C.FLOWERS if nrng.random() < 0.30 else C.BUSHES
                for x, y in candidates[i:i + run_len]:
                    if (x, y) in cand_set and not (colour == C.BUSHES and (x, y) in window_tiles):
                        place_veg(x, y, colour)
                i += run_len + nrng.randint(1, 3)

        # 3. Orderly outdoor seating (facing chairs or spaced line) 3+ tiles clear of walls.
        if bw >= 6 and bh >= 6 and kind in _NON_HOME_BENCH_KINDS and nrng.random() < 0.50:
            spots = [
                (bx0 + bw // 2, by0 + bh + 3),
                (bx0 + bw // 2, by0 - 5),
                (bx0 - 5, by0 + bh // 2),
                (bx0 + bw + 3, by0 + bh // 2),
            ]
            nrng.shuffle(spots)
            door_pts_t = [(bx0 + ox, by0 + oy) for ox, oy, _ix, _iy in doors]

            def clear_n(x: int, y: int) -> bool:
                return all(
                    0 <= x + nx < w and 0 <= y + ny < h
                    and tuple(veg[y + ny, x + nx]) == C.VEG_NOTHING
                    for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )

            for tx, ty in spots:
                if any(abs(tx - dx_) + abs(ty - dy_) <= 3 for dx_, dy_ in door_pts_t):
                    continue
                if _place_orderly_seating(can_veg, clear_n, veg, tx, ty, nrng, allow_loungers=False):
                    break

        # 4. Rear/side dumpsters & service clutter: only on doorless South/East walls
        # and never directly in front of a ground-floor window.
        door_walls = set()
        door_pts = []
        for ox, oy, ix, iy in doors:
            door_pts.append((bx0 + ox, by0 + oy))
            if oy - iy > 0:
                door_walls.add("S")
            elif oy - iy < 0:
                door_walls.add("N")
            elif ox - ix > 0:
                door_walls.add("E")
            elif ox - ix < 0:
                door_walls.add("W")

        service_ring = []
        if "S" not in door_walls:
            sy_w = by0 + bh
            if 0 <= sy_w < h:
                service_ring.extend(
                    (x, sy_w) for x in range(max(0, bx0 + 1), min(w, bx0 + bw - 1))
                    if can_veg(x, sy_w)
                    and (x, sy_w) not in window_tiles
                    and not any(abs(x - dx_) + abs(sy_w - dy_) <= 3 for dx_, dy_ in door_pts)
                )
        if "E" not in door_walls:
            ex_w = bx0 + bw
            if 0 <= ex_w < w:
                service_ring.extend(
                    (ex_w, y) for y in range(max(0, by0 + 1), min(h, by0 + bh - 1))
                    if can_veg(ex_w, y)
                    and (ex_w, y) not in window_tiles
                    and not any(abs(ex_w - dx_) + abs(y - dy_) <= 3 for dx_, dy_ in door_pts)
                )
        if service_ring and bw >= 6 and bh >= 6:
            if kind in _DUMPSTER_KINDS and nrng.random() < 0.85:
                _dumpster(service_ring, bx0, by0, bw, bh, doors, can_veg, place_veg, nrng,
                          lambda x, y: 0 <= x < w and 0 <= y < h and bool(occupied[y, x]))
            clutter_chance = 0.75 if kind in _SERVICE_CLUTTER_KINDS else 0.45
            if nrng.random() < clutter_chance:
                far_wall = sorted(
                    service_ring,
                    key=lambda p: min(abs(p[0] - dx_) + abs(p[1] - dy_) for dx_, dy_ in door_pts)
                    if door_pts else 0,
                    reverse=True,
                )
                props = (C.WORKS_CRATE, C.WORKS_BARREL, C.WORKS_PALLET, C.WORKS_DRUM, C.WORKS_TIRES)
                n_clusters = nrng.randint(2, 4) if kind in _SERVICE_CLUTTER_KINDS else nrng.randint(1, 2)
                idx = 0
                for _ in range(n_clusters):
                    if idx >= len(far_wall):
                        break
                    prop = nrng.choice(props)
                    placed = 0
                    while idx < len(far_wall) and placed < nrng.randint(2, 3):
                        px_, py_ = far_wall[idx]
                        idx += 1
                        if place_veg(px_, py_, prop):
                            placed += 1
                    idx += nrng.randint(1, 3)

        # Occasional litter near entrance bins or service walls.
        for bx_, by_ in bin_spots:
            if nrng.random() < 0.50:
                for ox_, oy_ in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if place_veg(bx_ + ox_, by_ + oy_, C.LITTER):
                        break

        # 5. Varied shade trees at least 4 tiles clear of walls/doors/props so canopies don't clip.
        tree_target = 1 if (bw < 10 and bh < 10) else nrng.randint(2, 4)
        tree_candidates = [
            (bx0 - nrng.randint(4, 7), by0 - nrng.randint(4, 6)),
            (bx0 + bw + nrng.randint(4, 6), by0 - nrng.randint(4, 6)),
            (bx0 - nrng.randint(4, 7), by0 + bh + nrng.randint(4, 6)),
            (bx0 + bw + nrng.randint(4, 6), by0 + bh + nrng.randint(4, 6)),
            (bx0 + bw // 2 + nrng.randint(-3, 3), by0 - nrng.randint(5, 8)),
            (bx0 + bw // 2 + nrng.randint(-3, 3), by0 + bh + nrng.randint(4, 7)),
        ]
        nrng.shuffle(tree_candidates)
        trees = 0
        for cx_, cy_ in tree_candidates:
            if (is_grass(cx_, cy_) and can_veg(cx_, cy_)
                    and not any(abs(cx_ - dx_) + abs(cy_ - dy_) <= 4 for dx_, dy_ in door_pts)
                    and all(
                        0 <= cx_ + nx < w and 0 <= cy_ + ny < h
                        and tuple(veg[cy_ + ny, cx_ + nx]) == C.VEG_NOTHING
                        for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    )):
                veg[cy_, cx_] = C.TREE_SMALL if nrng.random() < 0.7 else C.TREES
                trees += 1
                if trees >= tree_target:
                    break


def _connected_yard(ground, occupied, roads, building_slice):
    """Land reachable from a building wall within the local decoration area."""
    land = ~occupied & ~roads & ~np.all(ground == C.WATER, axis=2)
    reached = np.zeros_like(land)
    reached[building_slice] = occupied[building_slice]
    while True:
        neighbors = np.zeros_like(land)
        neighbors[1:] |= reached[:-1]
        neighbors[:-1] |= reached[1:]
        neighbors[:, 1:] |= reached[:, :-1]
        neighbors[:, :-1] |= reached[:, 1:]
        added = neighbors & land & ~reached
        if not added.any():
            return reached & land
        reached |= added


def _dress_open_yards(
    rows: list[dict],
    door_lists: dict,
    ground: np.ndarray,
    veg: np.ndarray,
    w: int,
    h: int,
    occupied: np.ndarray,
    road_at: np.ndarray,
    free,
    fronts: set[tuple[int, int]] | None,
) -> None:
    """Scale exterior yard decor to how much open grass surrounds a building:
    compact lots stay uncluttered, while spacious lots get trees, shrub
    islands, flower beds, seating/picnic spots, and subtle yard clutter."""
    bench_ready = _rule_ready("Bench")
    door_clear = fronts or set()

    roads = np.asarray(road_at, dtype=np.uint8).view(bool).reshape(h, w)

    def clear_neighbors(x: int, y: int) -> bool:
        return all(
            0 <= x + nx < w and 0 <= y + ny < h
            and tuple(veg[y + ny, x + nx]) == C.VEG_NOTHING
            for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )

    for row in rows:
        kind = row.get("kind", "")
        if kind in ("garage", "industrial", "hangar"):
            continue
        bx0, by0 = row["tile_x"], row["tile_y"]
        bw, bh = row["width"], row["height"]
        if bw < 3 or bh < 3:
            continue

        open_tiles: list[tuple[int, int, int]] = []
        y0 = max(0, by0 - 12)
        y1 = min(h, by0 + bh + 12)
        x0 = max(0, bx0 - 12)
        x1 = min(w, bx0 + bw + 12)
        area = np.s_[y0:y1, x0:x1]
        building = np.s_[max(0, by0 - y0):by0 + bh - y0,
                         max(0, bx0 - x0):bx0 + bw - x0]
        reachable = _connected_yard(ground[area], occupied[area], roads[area], building)

        def can_grass(x: int, y: int) -> bool:
            return (x0 <= x < x1 and y0 <= y < y1 and reachable[y - y0, x - x0]
                    and free(x, y) and (x, y) not in door_clear
                    and tuple(ground[y, x]) in CROSSABLE
                    and tuple(veg[y, x]) == C.VEG_NOTHING)

        for y in range(y0, y1):
            for x in range(x0, x1):
                dist = max(bx0 - x, x - (bx0 + bw - 1), by0 - y, y - (by0 + bh - 1), 0)
                if 2 <= dist <= 12 and can_grass(x, y):
                    open_tiles.append((x, y, dist))

        n_open = len(open_tiles)
        if n_open < 35:
            continue
        scale = min(1.0, (n_open - 35) / 220.0)
        yrng = random.Random((bx0 * 19349663) ^ (by0 * 73856093) ^ 0x55AA55AA)
        door_pts = [(bx0 + ox, by0 + oy) for ox, oy, _ix, _iy in door_lists.get(row["file"], [])]

        def clear_of_doors(x: int, y: int, radius: int = 3) -> bool:
            return not any(abs(x - dx_) + abs(y - dy_) <= radius for dx_, dy_ in door_pts)

        mid_spots = [(x, y) for x, y, d in open_tiles if 4 <= d <= 10 and clear_of_doors(x, y, 4)]
        yrng.shuffle(mid_spots)

        # 1. Orderly seating (facing chairs, spaced line, or parallel loungers) or bench.
        if scale >= 0.25 and mid_spots and yrng.random() < 0.35 + 0.45 * scale:
            placed_seat = False
            for tx, ty in mid_spots[:40]:
                if _place_orderly_seating(can_grass, clear_neighbors, veg, tx, ty, yrng,
                                          allow_loungers=(kind != "house")):
                    placed_seat = True
                    break
            if not placed_seat and bench_ready:
                for tx, ty in mid_spots[:30]:
                    if can_grass(tx, ty) and can_grass(tx + 1, ty) and clear_neighbors(tx, ty):
                        veg[ty, tx] = C.BENCH_X[0]
                        veg[ty, tx + 1] = C.BENCH_X[1]
                        break

        # 2. Woodpile / utility clutter or raised flower patch on spacious yards.
        if scale >= 0.20 and mid_spots:
            n_features = 1 if scale < 0.6 else 2
            feat_idx = 0
            for _ in range(n_features):
                while feat_idx < len(mid_spots):
                    fx, fy = mid_spots[feat_idx]
                    feat_idx += 1
                    if not (can_grass(fx, fy) and clear_neighbors(fx, fy)):
                        continue
                    if yrng.random() < 0.55:
                        prop = yrng.choice((C.WORKS_PALLET, C.WORKS_BARREL, C.WORKS_CRATE, C.WORKS_TIRES))
                        veg[fy, fx] = prop
                        if can_grass(fx + 1, fy):
                            veg[fy, fx + 1] = prop
                    else:
                        for ox_, oy_ in ((0, 0), (1, 0), (0, 1)):
                            if can_grass(fx + ox_, fy + oy_):
                                veg[fy + oy_, fx + ox_] = C.FLOWERS
                    break

        # 3. Organic shrub & flower islands across the open yard.
        n_islands = max(1, round(5 * scale))
        island_spots = [(x, y) for x, y, d in open_tiles if 3 <= d <= 11 and clear_of_doors(x, y, 3)]
        yrng.shuffle(island_spots)
        for ix, iy in island_spots[:n_islands]:
            if not can_grass(ix, iy):
                continue
            col = C.BUSHES if yrng.random() < 0.72 else C.FLOWERS
            veg[iy, ix] = col
            for ox_, oy_ in yrng.sample(((1, 0), (-1, 0), (0, 1), (0, -1)), 3):
                if can_grass(ix + ox_, iy + oy_) and yrng.random() < 0.65:
                    veg[iy + oy_, ix + ox_] = col

        # 4. Extra shade trees scaled to open yard space, spaced apart from each other.
        n_trees = max(1, round(5 * scale))
        tree_spots = [(x, y) for x, y, d in open_tiles if 4 <= d <= 12 and clear_of_doors(x, y, 4)]
        yrng.shuffle(tree_spots)
        placed_trees: list[tuple[int, int]] = []
        for tx, ty in tree_spots:
            if len(placed_trees) >= n_trees:
                break
            if any(abs(tx - px_) + abs(ty - py_) < 5 for px_, py_ in placed_trees):
                continue
            if can_grass(tx, ty) and clear_neighbors(tx, ty):
                veg[ty, tx] = C.TREE_SMALL if yrng.random() < 0.65 else C.TREES
                placed_trees.append((tx, ty))


def _paint_walk_and_stoop(walk: list, end: tuple[int, int],
                          sx: int, sy: int, px: int, py: int,
                          w: int, h: int, free, paint,
                          paved_at, road_at, drive_tiles: set,
                          add_stoop: bool = True) -> None:
    """Paint a front walk, smooth 90-degree corners, apron, and optional stoop."""
    for x, y in walk:
        paint(x, y, C.PAVING_STONE)
    full_walk = [end] + walk
    for i in range(1, len(full_walk) - 1):
        ax, ay = full_walk[i - 1]
        cx, cy = full_walk[i]
        bx, by = full_walk[i + 1]
        if ax != bx and ay != by:
            for kx, ky in ((ax, by), (bx, ay)):
                if free(kx, ky):
                    paint(kx, ky, C.PAVING_STONE)
                    break
    if walk and end not in drive_tiles:
        mx, my = walk[0]
        ex, ey = end
        tx, ty = ex - mx, ey - my
        lx, ly = -ty, tx
        for s in (-1, 1):
            slx, sly = s * lx, s * ly
            nx, ny = ex + slx, ey + sly
            dx_step, dy_step = ex + tx + slx, ey + ty + sly
            if free(nx, ny) and 0 <= dx_step < w and 0 <= dy_step < h \
                    and (paved_at[dy_step * w + dx_step] or road_at[dy_step * w + dx_step]):
                paint(nx, ny, C.PALE_CONCRETE)
                paved_at[ny * w + nx] = True
                if free(mx + slx, my + sly):
                    paint(mx + slx, my + sly, C.PAVING_STONE)
    if add_stoop:
        for k in (-1, 1):
            if free(sx + px * k, sy + py * k):
                paint(sx + px * k, sy + py * k, C.PAVING_STONE)


def _connect_merged_doors(doors: list[tuple[int, int, int, int]],
                          bx0: int, by0: int, w: int, h: int,
                          paved_at, road_at, free, paint,
                          drive_tiles: set, max_steps: int,
                          frng: random.Random,
                          skip_facing: tuple[int, int] | None = None
                          ) -> tuple[set[tuple[int, int, int, int]], list[tuple[int, int]]]:
    """Sometimes merge multiple same-side doorway walks into a shared center trunk."""
    by_dir: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for door in doors:
        ox, oy, ix, iy = door
        dd = (ox - ix, oy - iy)
        if dd == skip_facing:
            continue
        by_dir.setdefault(dd, []).append(door)

    connected: set[tuple[int, int, int, int]] = set()
    first_walk: list[tuple[int, int]] = []
    for (ddx, ddy), group in by_dir.items():
        if len(group) < 2:
            continue
        px, py = -ddy, ddx
        ordered = sorted(group, key=lambda d: (bx0 + d[0]) * px + (by0 + d[1]) * py)
        lo_pos = (bx0 + ordered[0][0]) * px + (by0 + ordered[0][1]) * py
        hi_pos = (bx0 + ordered[-1][0]) * px + (by0 + ordered[-1][1]) * py
        span = hi_pos - lo_pos
        if not (MERGE_DOOR_MIN_GAP <= span <= MERGE_DOOR_MAX_GAP):
            continue
        # Every door in the cluster should sit on the same front offset along (ddx, ddy).
        offsets = {(bx0 + d[0]) * ddx + (by0 + d[1]) * ddy for d in ordered}
        if len(offsets) != 1 or frng.random() >= MERGE_DOOR_SHARE:
            continue
        # Measure straight clearance out from each door so the cross-bar stays clear of the street.
        dists = []
        for d in ordered:
            dsx, dsy = bx0 + d[0], by0 + d[1]
            t = 0
            while t < max_steps:
                tx, ty = dsx + ddx * t, dsy + ddy * t
                if not (0 <= tx < w and 0 <= ty < h) or paved_at[ty * w + tx] or not free(tx, ty):
                    break
                t += 1
            dists.append(t)
        min_dist = min(dists)
        if min_dist < 4:
            continue
        stem = 2 if min_dist >= 5 else 1
        spurs = {(bx0 + d[0] + ddx * t, by0 + d[1] + ddy * t)
                 for d in ordered for t in range(stem + 1)}
        ax0, ay0 = bx0 + ordered[0][0] + ddx * stem, by0 + ordered[0][1] + ddy * stem
        bar = [(ax0 + px * k, ay0 + py * k) for k in range(span + 1)]
        branch_tiles = spurs | set(bar)
        if not all(free(x, y) for x, y in branch_tiles):
            continue
        mid_x, mid_y = bar[span // 2]
        trunk_sx, trunk_sy = mid_x + ddx, mid_y + ddy

        def free_for_trunk(x: int, y: int) -> bool:
            return (x, y) not in branch_tiles and free(x, y)

        trunk, end = _find_walk(trunk_sx, trunk_sy, ddx, ddy, w, h,
                                paved_at, free_for_trunk, drive_tiles,
                                max_steps=max_steps)
        if end is None:
            continue
        for x, y in branch_tiles:
            paint(x, y, C.PAVING_STONE)
        for d in ordered:
            dsx, dsy = bx0 + d[0], by0 + d[1]
            for k in (-1, 1):
                if free(dsx + px * k, dsy + py * k):
                    paint(dsx + px * k, dsy + py * k, C.PAVING_STONE)
        _paint_walk_and_stoop(trunk, end, trunk_sx, trunk_sy, px, py, w, h,
                              free, paint, paved_at, road_at, drive_tiles,
                              add_stoop=False)
        connected.update(ordered)
        if not first_walk:
            first_walk = trunk
    return connected, first_walk


def _pave_building_apron(bx0: int, by0: int, bw: int, bh: int,
                         occupied, w: int, h: int, free, paint) -> None:
    """Paint a modest concrete skirt hugging a non-house building's exterior walls."""
    r = BUILDING_APRON_MAX if min(bw, bh) >= 16 else BUILDING_APRON_MIN
    x0, y0 = max(0, bx0 - r), max(0, by0 - r)
    x1, y1 = min(w, bx0 + bw + r), min(h, by0 + bh + r)
    if x1 <= x0 or y1 <= y0:
        return
    base = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    ix0, iy0 = max(0, bx0), max(0, by0)
    ix1, iy1 = min(w, bx0 + bw), min(h, by0 + bh)
    if ix1 > ix0 and iy1 > iy0:
        base[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = occupied[iy0:iy1, ix0:ix1]
    dilated = np.zeros_like(base)
    bh_loc, bw_loc = base.shape
    for dy in range(-r, r + 1):
        sy0, sy1 = max(0, -dy), min(bh_loc, bh_loc - dy)
        ty0, ty1 = max(0, dy), min(bh_loc, bh_loc + dy)
        for dx in range(-r, r + 1):
            sx0, sx1 = max(0, -dx), min(bw_loc, bw_loc - dx)
            tx0, tx1 = max(0, dx), min(bw_loc, bw_loc + dx)
            dilated[ty0:ty1, tx0:tx1] |= base[sy0:sy1, sx0:sx1]
    ys, xs = np.nonzero(dilated & ~base)
    for dy, dx in zip(ys.tolist(), xs.tolist()):
        gx, gy = x0 + dx, y0 + dy
        if free(gx, gy):
            paint(gx, gy, C.PALE_CONCRETE)


def paint_paths(out_dir: str, map_name: str, rows: list[dict], occupied,
                drives: list | None = None,
                lights: list | None = None,
                fronts: set | None = None) -> tuple[int, list]:
    """Dress houses and connect mapped garages. Return houses dressed and fences.

    Each drive's parking space, (x, y, width, height) at its house end, is
    added to `drives` when it is given: the car belongs there. Porch lights
    are added to `lights` the same way, as (x, y, level, layer, tile) for
    whoever writes them into a .tbx."""
    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    base = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    veg_base = os.path.join(out_dir, f"{map_name}_veg_base.bmp")
    if not os.path.exists(bmp):
        return 0, []
    from .bitmaps import _bmp_header
    occ_h, occ_w = occupied.shape[:2]

    def _dims(p):
        hdr = _bmp_header(p)
        return (hdr[0], hdr[1]) if hdr else None

    if not os.path.exists(base):
        shutil.copyfile(bmp, base)
    elif _dims(base) != (occ_w, occ_h) and _dims(bmp) == (occ_w, occ_h):
        shutil.copyfile(bmp, base)
    if os.path.exists(veg_path):
        if not os.path.exists(veg_base):
            shutil.copyfile(veg_path, veg_base)
        elif _dims(veg_base) != (occ_w, occ_h) and _dims(veg_path) == (occ_w, occ_h):
            shutil.copyfile(veg_path, veg_base)
    ground = read_rgb(base, crop=(occ_h, occ_w))
    veg = read_rgb(veg_base, crop=(occ_h, occ_w)) if os.path.exists(veg_base) else None
    h, w = ground.shape[:2]
    if veg is not None and veg.shape[:2] != (h, w):
        veg = veg[:h, :w] if veg.shape[0] >= h and veg.shape[1] >= w else None
    if (occ_h, occ_w) == (h, w):
        occ = occupied
    else:
        occ = np.zeros((h, w), dtype=bool)
        ch, cw = min(h, occ_h), min(w, occ_w)
        occ[:ch, :cw] = occupied[:ch, :cw]

    def match(colours):
        mask = np.zeros((h, w), dtype=bool)
        for c in colours:
            mask |= same_colour(ground, c)
        return mask

    paved = match(PAVED)
    road = match((C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                  C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE))
    crossable = match(CROSSABLE) & ~occ
    # Painted for some house already. One block of memory seen two ways: as an
    # array for the whole-map work, and as bytes for the tile-at-a-time loops
    # below, where reading a numpy element costs several times what a list
    # does. The masks that never change are read the same way, as flat lists
    # indexed y * w + x.
    claimed_bytes = bytearray(h * w)
    claimed = np.frombuffer(claimed_bytes, dtype=bool).reshape(h, w)
    crossable_at = bytearray(crossable.astype(np.uint8, copy=False).tobytes())
    paved_at = bytearray(paved.astype(np.uint8, copy=False).tobytes())
    occupied_at = bytearray(np.asarray(occ, dtype=np.uint8).tobytes())
    road_at = bytearray(road.astype(np.uint8, copy=False).tobytes())
    walkable_at = bytearray(((crossable | paved | road) & ~occ).astype(np.uint8, copy=False).tobytes())
    del paved, road
    crossable = np.frombuffer(crossable_at, dtype=bool).reshape(h, w)
    # Drives the terrain laid already, read before any are painted here.
    laid = same_colour(ground, C.DARK_ASPHALT)

    def drive_there(bx0, by0, bw, bh):
        """Tiles of a drive already reaching this house, nearest first, or []."""
        r = DRIVE_THERE_TILES
        x0, y0 = max(0, bx0 - r), max(0, by0 - r)
        x1, y1 = min(w, bx0 + bw + r), min(h, by0 + bh + r)
        ys, xs = np.nonzero(laid[y0:y1, x0:x1])
        if not len(xs):
            return []
        xs, ys = xs + x0, ys + y0
        dx = np.maximum(0, np.maximum(bx0 - xs, xs - (bx0 + bw - 1)))
        dy = np.maximum(0, np.maximum(by0 - ys, ys - (by0 + bh - 1)))
        order = np.argsort(dx + dy, kind="stable")
        return [(int(xs[i]), int(ys[i])) for i in order]

    def free(x, y):
        return (0 <= x < w and 0 <= y < h and crossable_at[y * w + x]
                and not claimed_bytes[y * w + x])

    def paint(x, y, colour):
        ground[y, x] = colour
        claimed_bytes[y * w + x] = 1
        if veg is not None:
            veg[y, x] = 0

    def put(x, y, colour):
        if veg is not None and free(x, y):
            veg[y, x] = colour
            claimed_bytes[y * w + x] = 1

    dressed = 0
    fences = []
    apron_boxes = []
    rng = random.Random(0xB17E)
    # Reading a thousand freshly written .tbx files is mostly waiting on the
    # disk, so it is done on threads up front; the loop below still runs in
    # order, which keeps the random choices the same.
    from concurrent.futures import ThreadPoolExecutor
    house_files = [r["file"] for r in rows if r.get("kind") in FRONT_PATH_KINDS]
    homes = {r["file"] for r in rows if r.get("kind") == "house"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        door_lists = dict(zip(house_files, pool.map(
            lambda f: _outside_doors(os.path.join(out_dir, "buildings", f), f in homes),
            house_files)))
    for row in rows:
        if row.get("kind") not in FRONT_PATH_KINDS:
            continue
        home = row["kind"] == "house"
        bx0, by0 = row["tile_x"], row["tile_y"]
        bw, bh = row["width"], row["height"]
        if not home:
            apron_boxes.append((bx0, by0, bw, bh))
        doors = door_lists[row["file"]]
        if not doors:
            continue
        max_steps = WALK_MAX_TILES if home else NON_HOME_WALK_MAX_TILES
        # Pick the first outside door that can actually reach the street/paving
        # so a blocked back/side door at doors[0] never strands the building.
        primary = doors[0]
        for cand in doors:
            cox, coy, cix, ciy = cand
            w_cand, _ = _find_walk(bx0 + cox, by0 + coy, cox - cix, coy - ciy,
                                   w, h, paved_at, free, set(),
                                   max_steps=max_steps)
            if w_cand is not None:
                primary = cand
                break
        ox, oy, ix, iy = primary
        sx, sy = bx0 + ox, by0 + oy
        dx, dy = ox - ix, oy - iy          # out of the door, towards the street
        px, py = -dy, dx                   # along the front of the house

        # A light on the wall beside the door. It goes outside the building,
        # past the edge of the house's own .tbx, so it is written as a loose
        # tile. Ahead of the path and the stoop because it does not depend on
        # either: a house with nowhere to run a path still has a front light.
        side = _SIDE.get((-dx, -dy))
        if lights is not None and side and rng.random() < PORCH_LIGHT_SHARE:
            style = rng.choice(PORCH_LIGHTS)
            for k in (1, -1):
                lx, ly = sx + px * k, sy + py * k
                if not (0 <= lx < w and 0 <= ly < h) or occupied_at[ly * w + lx]:
                    continue
                # Only where the house really is behind it: beside a door in a
                # corner, one of the two faces open ground.
                wx, wy = lx - dx, ly - dy
                if not (0 <= wx < w and 0 <= wy < h and occupied_at[wy * w + wx]):
                    continue
                lights.append((lx, ly, 0, PORCH_LIGHT_LAYER, style[side]))
                break

        tbx_file = os.path.join(out_dir, "buildings", row["file"])
        window_tiles = (
            {(bx0 + wx, by0 + wy) for wx, wy in _outside_windows(tbx_file)}
            if os.path.isfile(tbx_file) else set()
        )

        # The drive: beside the house, from the street past the front wall.
        # Ahead of the path, so that a house far back from the street can walk
        # to its own drive.
        there = drive_there(bx0, by0, bw, bh) if (home and free(sx, sy)) else []
        if not home or not free(sx, sy):
            lanes = []
        elif there:
            # The terrain's drive reaches it already: the car parks at its
            # top, and the path below walks to it.
            lanes = []
            if drives is not None:
                top = there[:DRIVE_WIDTH * 5]
                xs, ys = [p[0] for p in top], [p[1] for p in top]
                drives.append((min(xs), min(ys), max(xs) - min(xs) + 1,
                               max(ys) - min(ys) + 1))
        elif dx:   # street to the east or west; the front runs north-south
            front = bx0 + (bw if dx > 0 else -1)
            lanes = [(by0 + bh + 1, 1), (by0 - DRIVE_WIDTH - 1, 1)]
        else:
            front = by0 + (bh if dy > 0 else -1)
            lanes = [(bx0 + bw + 1, 1), (bx0 - DRIVE_WIDTH - 1, 1)]
        drive_tiles = set()
        for start, _ in lanes:
            strip = []
            # From DRIVE_EXTRA tiles back along the house to the pavement.
            t = -DRIVE_EXTRA
            while t < PATH_MAX_TILES:
                line = []
                for k in range(DRIVE_WIDTH):
                    if dx:
                        x, y = front + dx * t, start + k
                    else:
                        x, y = start + k, front + dy * t
                    line.append((x, y))
                if t > 0 and all(0 <= x < w and 0 <= y < h and paved_at[y * w + x]
                                 for x, y in line):
                    break
                if not all(free(x, y) for x, y in line):
                    strip = None
                    break
                strip.extend(line)
                t += 1
            if strip and t < PATH_MAX_TILES:
                for x, y in strip:
                    paint(x, y, C.DARK_ASPHALT)
                    paved_at[y * w + x] = True
                drive_tiles.update(strip)
                if drives is not None:
                    # The strip starts beside the house: its first five rows.
                    top = strip[:DRIVE_WIDTH * 5]
                    xs, ys = [p[0] for p in top], [p[1] for p in top]
                    drives.append((min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
                # The dustbin at the top of the drive, on the lawn beside it.
                bx, by = strip[0]
                if (bx - px, by - py) not in window_tiles:
                    put(bx - px, by - py, C.BIN)
                break

        frng = random.Random((bx0 * 2654435761) ^ (by0 * 2246822519) ^ 0x517CC1B7)
        merged, merged_walk = _connect_merged_doors(
            doors, bx0, by0, w, h, paved_at, road_at, free, paint,
            drive_tiles, max_steps, frng,
            skip_facing=(-dx, -dy) if home else None)

        # The path, shortest way to the pavement or the drive, straight out of
        # the door first. It never crosses ground already painted for another
        # building: a neighbour's stoop, patio or vegetable bed.
        walk, end = None, None
        if primary not in merged and free(sx, sy):
            walk, end = _find_walk(sx, sy, dx, dy, w, h, paved_at, free,
                                   drive_tiles, max_steps=max_steps)
            if end is not None:
                _paint_walk_and_stoop(walk, end, sx, sy, px, py, w, h,
                                      free, paint, paved_at, road_at, drive_tiles)
        elif primary in merged:
            walk = merged_walk

        # Connect any additional doors (e.g. multi-entrance infill
        # shops/schools/apartments or corner-lot houses) to the pavement too.
        any_connected = bool(merged) or end is not None
        for extra in doors:
            if extra == primary or extra in merged:
                continue
            eox, eoy, eix, eiy = extra
            esx, esy = bx0 + eox, by0 + eoy
            if not free(esx, esy):
                continue
            edx, edy = eox - eix, eoy - eiy
            if home and (edx, edy) == (-dx, -dy):
                continue  # back door facing away from the street
            ewalk, eend = _find_walk(esx, esy, edx, edy, w, h, paved_at, free,
                                     drive_tiles, max_steps=max_steps)
            if eend is not None:
                _paint_walk_and_stoop(ewalk, eend, esx, esy, -edy, edx, w, h,
                                      free, paint, paved_at, road_at, drive_tiles)
                any_connected = True

        if not any_connected:
            continue
        # Front-yard flower/shrub beds flanking the stoop and an occasional kerbside
        # bin opposite the mailbox so street fronts read as lived-in homes.
        if home and veg is not None and frng.random() < 0.80:
            bed_colour = C.FLOWERS if frng.random() < 0.55 else C.BUSHES
            for k in (-2, 2, -3, 3):
                fx, fy = sx + px * k, sy + py * k
                if (free(fx, fy) and tuple(ground[fy, fx]) not in LAWNLESS
                        and not (bed_colour == C.BUSHES and (fx, fy) in window_tiles)):
                    put(fx, fy, bed_colour)
        # The mailbox, beside the path where it reaches the street.
        if home and walk and (end is not None and end not in drive_tiles or primary in merged):
            mx, my = walk[0]
            mb_side = None
            for k in (1, -1):
                if free(mx + px * k, my + py * k):
                    put(mx + px * k, my + py * k, C.MAILBOX)
                    mb_side = k
                    break
            if mb_side is not None and veg is not None and frng.random() < 0.35:
                bx_, by_ = mx - px * mb_side, my - py * mb_side
                if free(bx_, by_) and tuple(ground[by_, bx_]) not in LAWNLESS:
                    put(bx_, by_, C.BIN)
        if not home:
            dressed += 1
            continue

        # The back yard. Knox County's are lived in: a patio by the back door
        # with a grill and a table, a washing line, a vegetable bed, all
        # inside a fence that meets the house with a gap for the gate. A
        # fenced square of empty lawn standing off the house was no use.
        bdx, bdy = -dx, -dy                          # away from the street
        ax, ay = (1, 0) if dy else (0, 1)            # along the back wall
        back = (by0 - 1 if dy > 0 else by0 + bh) if dy else (bx0 - 1 if dx > 0 else bx0 + bw)
        # As wide as the house and a little over, narrower where the
        # neighbours are close; as deep as there is room for, up to a depth
        # this house's own yard takes. Every yard used to be nine deep.
        want_depth = max(YARD_MIN_DEPTH,
                         YARD_DEPTH - random.Random((bx0 * 31 + by0) ^ 0xA5A5)
                         .choice((0, 0, 1, 1, 2, 3)))
        base_u0 = bx0 if dy else by0
        base_w = bw if dy else bh
        candidates = [(base_u0 - side, base_w + 2 * side) for side in (YARD_SIDE, 1, 0)]
        if base_w >= 5:
            candidates += [(base_u0 + 1, base_w - 1), (base_u0, base_w - 1),
                           (base_u0 + 1, base_w - 2)]
        for u0, width in candidates:
            if width < 3:
                continue

            def at(u, v, u0=u0):
                """World tile u along the back wall, v rows back from it."""
                return ((u0 + u, back + bdy * v) if dy else (back + bdx * v, u0 + u))

            depth = 0
            for v in range(want_depth):
                if not all(free(*at(u, v)) for u in range(width)):
                    break
                depth = v + 1
            if depth >= YARD_MIN_DEPTH:
                break
        if depth >= YARD_MIN_DEPTH:
            # Which yard this is, and whether it is fenced at all: stable per
            # house, so a rebuild is the same map, but a street is not all the
            # same back yard. The fence style used to be a function of the
            # coordinates alone, which is why whole rows matched.
            style, fenced, archetype = yard_plan(bx0, by0)
            yrng = random.Random((bx0 * 73856093) ^ (by0 * 19349663) ^ 0x5DEECE66D)

            # Fence corners as tile-corner coordinates, far side of row depth-1.
            if dy:
                # Edges between rows: the house's back wall, and past the last
                # yard row.
                wall_y = back + (0 if bdy > 0 else 1)
                far_y = back + bdy * depth + (0 if bdy > 0 else 1)
                a, b = u0, u0 + width
                house_a, house_b = bx0, bx0 + bw
                fence = ([(house_a, wall_y), (a, wall_y), (a, far_y), (b, far_y),
                          (b, wall_y), (house_b, wall_y)], style,
                         [(house_b, wall_y)])
                if fenced:
                    fences.append(fence)
            else:
                wall_x = back + (0 if bdx > 0 else 1)
                far_x = back + bdx * depth + (0 if bdx > 0 else 1)
                a, b = u0, u0 + width
                house_a, house_b = by0, by0 + bh
                fence = ([(wall_x, house_a), (wall_x, a), (far_x, a), (far_x, b),
                          (wall_x, b), (wall_x, house_b)], style,
                         [(wall_x, house_b)])
                if fenced:
                    fences.append(fence)
            # The gate is beside the house, at the end of the last stretch.

            taken = set()

            def place(u, v, colour, ground_colour=None):
                x, y = at(u, v)
                if (x, y) in taken or not free(x, y):
                    return False
                taken.add((x, y))
                if ground_colour is not None:
                    paint(x, y, ground_colour)
                if colour is not None and veg is not None:
                    veg[y, x] = colour
                claimed_bytes[y * w + x] = 1
                return True

            def place_first(colour, order):
                """The first square in `order` that will take the prop.

                A fixed square was silently skipped when the patio, a bed or a
                path already stood there; the yard simply went without. This
                walks the candidates - lawn only, since these props stand on
                grass - and takes the first that is free.
                """
                for u, v in order:
                    x, y = at(u, v)
                    if tuple(ground[y, x]) in LAWNLESS:
                        continue
                    if place(u, v, colour):
                        return True
                return False

            def place_pair(first, second):
                """Both halves of one two-tile sprite, or neither: a half
                alone is half a deck chair."""
                for u, v, _c in (first, second):
                    x, y = at(u, v)
                    if (x, y) in taken or not free(x, y):
                        return False
                return place(*first) and place(*second)

            # What this yard is: a family yard with the table out, a barbecue,
            # washing, a garden, or a bare one with a bin. Knox County's yards
            # are not one script, and every generated one used to be.
            mid = width // 2
            for bxo, byo, _bxi, _byi in doors[1:]:
                wx, wy = bx0 + bxo, by0 + byo
                u, v = ((wx - u0, (wy - back) * bdy) if dy else (wy - u0, (wx - back) * bdx))
                if v == 0 and 2 <= u < width - 3:
                    mid = u
                    break

            # Patio: stone or gravel, 3 or 5 wide, as deep as the yard allows.
            patio_w = min(3 if (width < 9 or yrng.random() < 0.5) else 5,
                          max(1, width - 2))
            patio_d = max(1, min(yrng.choice((2, 3, 3, 4)), depth - 1))
            patio_colour = yrng.choice((C.PAVING_STONE, C.PAVING_STONE, C.LIGHT_ASPHALT))
            patio_tiles = []
            left = max(1, min(width - 2 - patio_w, mid - patio_w // 2))
            mid = left + patio_w // 2
            if archetype != "bare":
                for v in range(patio_d):
                    for u in range(left, left + patio_w):
                        patio_tiles.extend(_pave_patio(
                            ground, veg, crossable, claimed, (at(u, v),), patio_colour))

            # Furniture: not every yard sets the same table.
            if archetype == "family":
                place(left, 1, C.GRILL)
                if dy:
                    place_pair((mid, 1, C.TABLE_X0), (mid + 1, 1, C.TABLE_X1))
                    place(mid, 0, C.CHAIR_N); place(mid + 1, 2, C.CHAIR_S)
                else:
                    # The deck chair's halves run along u (north to south here),
                    # as in the other branch; along v they stood side by side.
                    place_pair((mid, 1, C.TABLE_Y0), (mid + 1, 1, C.TABLE_Y1))
                    place(mid - 1, 1, C.CHAIR_W); place(mid + 1, 2, C.CHAIR_E)
            elif archetype == "grill":
                place(left, 1, C.GRILL)
                place(mid, 1, C.CHAIR_N if dy else C.CHAIR_W)
            elif archetype == "laundry":
                place(1, depth - 2, C.BIN)
            else:
                place(width - 2, depth - 2, C.BIN)

            # Yard storytelling: the dog's house against one fence, a swing
            # for the kids against the other. Both want lawn, so they are
            # offered a square each and skipped where there is no room.
            lawn = [(u, v) for v in range(depth) for u in range(width)]
            # The catalogue's dog house comes in orient N only - its door faces
            # north - so it goes against the far fence, at v = depth - 2, and
            # looks back up the yard rather than into the boards. The side
            # fences are the fallback. The swing wants open lawn to run up to.
            against_a_fence = [(u, v) for u, v in lawn if v == depth - 2]
            against_a_fence += [(u, v) for u, v in lawn if u in (1, width - 2)]
            if _rule_ready("Dog house") and yrng.random() < DOG_HOUSE_SHARE:
                place_first(C.DOG_HOUSE, against_a_fence + lawn)
            # No swing: location_community_park_01_010 is the top crossbar of
            # a three-tile set that stands on two levels (011/012/013 under it,
            # 014 above), and a yard colours a single ground bitmap. Placed
            # alone the crossbar hangs in the air, which is worse than no swing.

            # Claimed only now: the furniture stands on the patio, and `place`
            # refuses a claimed tile.
            for x, y in patio_tiles:
                claimed_bytes[y * w + x] = 1

            # Washing line along the back fence: the family and laundry yards,
            # on whichever side it was put.
            v_line = depth - 2
            if archetype in ("family", "laundry") and width >= 9 and v_line >= 3:
                ends = (C.LINE_X0, C.LINE_XM, C.LINE_X1) if dy else (C.LINE_Y0, C.LINE_YM, C.LINE_Y1)
                start = width - 6 if yrng.random() < 0.5 else 1
                for k in range(5):
                    place(start + k, v_line, ends[0] if k == 0 else ends[2] if k == 4 else ends[1])

            # A raised vegetable bed, soil to plant in. Its frame pieces go by
            # map direction (the editor's 3x3 planter, stretched): west column,
            # middle, east column; north row, middle, south row.
            def veg_bed(u_start):
                bd_ = min(4, depth - 3)
                if bd_ < 3:
                    return
                cells = [at(u_start + i, depth - 1 - j) for i in range(3) for j in range(bd_)]
                if not all(free(x, y) for x, y in cells):
                    return
                xs_ = sorted({x for x, _ in cells}); ys_ = sorted({y for _, y in cells})
                frame = {("W", "N"): C.BED_NW, ("W", "M"): C.BED_W, ("W", "S"): C.BED_SW,
                         ("M", "N"): C.BED_N, ("M", "M"): C.BED_SOIL, ("M", "S"): C.BED_S,
                         ("E", "N"): C.BED_NE, ("E", "M"): C.BED_E, ("E", "S"): C.BED_SE}
                for x, y in cells:
                    col = "W" if x == xs_[0] else "E" if x == xs_[-1] else "M"
                    row = "N" if y == ys_[0] else "S" if y == ys_[-1] else "M"
                    paint(x, y, C.DIRT)
                    if veg is not None:
                        veg[y, x] = frame[(col, row)]

            if archetype == "garden":
                veg_bed(1)
                if width >= 12:
                    veg_bed(width - 4)
            elif archetype == "family" and yrng.random() < 0.6:
                veg_bed(1)

            # A few bushes, or flowers in the corners: a yard is not mown bare.
            # Skipped where a bed or a tree already stands.
            if veg is not None and archetype != "bare":
                for u in range(1, width - 1, 2):
                    x, y = at(u, depth - 1)
                    if (0 <= x < w and 0 <= y < h
                            and tuple(veg[y, x]) == C.VEG_NOTHING
                            and yrng.random() < 0.22):
                        place(u, depth - 1, C.BUSHES)
            if veg is not None and archetype in ("garden", "bare") and yrng.random() < 0.5:
                place(width - 2, 0, C.FLOWERS)
            # Behind the fence: no later path or drive runs through it.
            for u in range(width):
                for v in range(depth):
                    x, y = at(u, v)
                    claimed_bytes[y * w + x] = 1
        # Side/front foundation shrubs, side-wall clutter, and a front shade tree
        # added after the back yard so back-yard patios and props stay intact.
        if veg is not None:
            side_wall = [
                (x, y)
                for y in range(max(0, by0 - 1), min(h, by0 + bh + 1))
                for x in range(max(0, bx0 - 1), min(w, bx0 + bw + 1))
                if (x in (bx0 - 1, bx0 + bw) or y in (by0 - 1, by0 + bh))
                and not (sx - 2 <= x <= sx + 2 and sy - 2 <= y <= sy + 2)
                and free(x, y) and tuple(ground[y, x]) in CROSSABLE
                and tuple(veg[y, x]) == C.VEG_NOTHING
                and (x, y) not in window_tiles
            ]
            if side_wall:
                import math
                cx_h, cy_h = bx0 + bw / 2, by0 + bh / 2
                side_wall.sort(key=lambda p: math.atan2(p[1] - cy_h, p[0] - cx_h))
                si = frng.randrange(3)
                while si < len(side_wall):
                    rlen = frng.randint(1, 3)
                    col = C.BUSHES if frng.random() < 0.78 else C.FLOWERS
                    for sx_, sy_ in side_wall[si:si + rlen]:
                        put(sx_, sy_, col)
                    si += rlen + frng.randint(2, 5)
                if frng.random() < 0.60:
                    bx_w, by_w = frng.choice(side_wall)
                    put(bx_w, by_w, C.BIN)
                if frng.random() < 0.45:
                    cx_w, cy_w = frng.choice(side_wall)
                    put(cx_w, cy_w, frng.choice((C.WORKS_PALLET, C.WORKS_BARREL, C.WORKS_CRATE)))
            if frng.random() < 0.65:
                front_corners = [
                    (sx + px * frng.randint(4, 6) + dx * frng.randint(4, 5),
                     sy + py * frng.randint(4, 6) + dy * frng.randint(4, 5)),
                    (sx - px * frng.randint(4, 6) + dx * frng.randint(4, 5),
                     sy - py * frng.randint(4, 6) + dy * frng.randint(4, 5)),
                ]
                for tx_, ty_ in front_corners:
                    if (0 <= tx_ < w and 0 <= ty_ < h and free(tx_, ty_)
                            and tuple(ground[ty_, tx_]) in CROSSABLE
                            and tuple(veg[ty_, tx_]) == C.VEG_NOTHING
                            and all(
                                0 <= tx_ + nx < w and 0 <= ty_ + ny < h
                                and tuple(veg[ty_ + ny, tx_ + nx]) == C.VEG_NOTHING
                                for nx, ny in ((1, 0), (-1, 0), (0, 1), (0, -1))
                            )):
                        put(tx_, ty_, C.TREE_SMALL if frng.random() < 0.7 else C.TREES)
                        break
        dressed += 1

    for row in rows:
        path = os.path.join(out_dir, "buildings", row["file"])
        if (row.get("building") not in ("garage", "garages")
                and row.get("kind") != "garage"):
            # A house with a garage built into it gets its drive from the
            # garage door, not from the front door.
            if row.get("kind") != "house":
                continue
            doors = _outside_garage_doors(path)
        else:
            doors = _outside_doors(path)
        if not doors:
            continue
        ox, oy, _ix, _iy = doors[0]
        start = (row["tile_x"] + ox, row["tile_y"] + oy)
        sx, sy = start
        if not (0 <= sx < w and 0 <= sy < h) or occupied_at[sy * w + sx]:
            continue
        if road_at[sy * w + sx]:
            continue

        previous = {start: None}
        queue = deque([(sx, sy, 0)])
        end = None
        while queue:
            x, y, distance = queue.popleft()
            if road_at[y * w + x]:
                end = (x, y)
                break
            if distance >= GARAGE_DRIVE_MAX_TILES:
                continue
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if (0 <= nx < w and 0 <= ny < h and (nx, ny) not in previous
                        and walkable_at[ny * w + nx] and not claimed_bytes[ny * w + nx]):
                    previous[(nx, ny)] = (x, y)
                    queue.append((nx, ny, distance + 1))
        if end is None:
            continue

        route = []
        step = end
        while step is not None:
            route.append(step)
            step = previous[step]
        route.reverse()
        painted = []
        for index, (x, y) in enumerate(route):
            before = route[max(0, index - 1)]
            after = route[min(len(route) - 1, index + 1)]
            if before[0] != after[0]:
                across = ((x, y - 1), (x, y), (x, y + 1))
            else:
                across = ((x - 1, y), (x, y), (x + 1, y))
            for px, py in across:
                if (0 <= px < w and 0 <= py < h and not road_at[py * w + px]
                        and not occupied_at[py * w + px]
                        and not claimed_bytes[py * w + px]
                        and (crossable_at[py * w + px] or paved_at[py * w + px])):
                    paint(px, py, C.DARK_ASPHALT)
                    painted.append((px, py))
        if drives is not None and painted:
            near_garage = painted[:min(len(painted), DRIVE_WIDTH * 5)]
            xs, ys = [point[0] for point in near_garage], [point[1] for point in near_garage]
            drives.append((min(xs), min(ys), max(xs) - min(xs) + 1,
                           max(ys) - min(ys) + 1))

    # The works: a tarmac yard round each, and what stands in it.
    from types import SimpleNamespace

    from .works import WORKS_KINDS, dress_works
    works_files = [r["file"] for r in rows if r.get("kind") in WORKS_KINDS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        works_doors = dict(zip(works_files, pool.map(
            lambda f: _outside_doors(os.path.join(out_dir, "buildings", f)), works_files)))
    canvas = SimpleNamespace(ground=ground, veg=veg, w=w, h=h, free=free, paint=paint,
                             paved_at=paved_at, occupied_at=occupied_at)
    dress_works(rows, works_doors, canvas, drives, random.Random(0x3077))

    # Give non-home buildings a modest concrete apron hugging their walls
    # after all doorway walks and industrial tarmac yards are placed.
    for bx0, by0, bw, bh in apron_boxes:
        _pave_building_apron(bx0, by0, bw, bh, occ, w, h, free, paint)

    if veg is not None:
        _dress_non_home_surroundings(
            rows, door_lists, out_dir, ground, veg, w, h,
            occ, road_at, paved_at, free, fronts,
        )
        _dress_open_yards(
            rows, door_lists, ground, veg, w, h,
            occ, road_at, free, fronts,
        )

    if veg is not None and fronts:
        # No tree or bush grows in a doorway.
        for x, y in fronts:
            if 0 <= x < w and 0 <= y < h:
                veg[y, x] = C.VEG_NOTHING
    # The credit for KnoxMap, in the ground near the first spawn house.
    from . import credit_ground
    clear = (match(CROSSABLE) & ~occ
             & ~np.frombuffer(claimed_bytes, dtype=bool).reshape(h, w))
    where = credit_ground.paint(ground, veg, clear, rows)
    print(f"credit lettering     : " + (f"at tile {where[0]},{where[1]}" if where else "no clear patch"))
    import knoxfiles
    knoxfiles.save(Image.fromarray(ground), bmp, format="BMP")
    if veg is not None:
        knoxfiles.save(Image.fromarray(veg), veg_path, format="BMP")
    return dressed, fences
