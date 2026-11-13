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
GARAGE_DRIVE_MAX_TILES = 40
# A house the terrain already gave a drive to (generator/rendering/homesteads.py:
# a house in the woods) gets no second one beside it: tarmac this near its walls.
DRIVE_THERE_TILES = 3
# Who gets a front path, a stoop and a porch light. Only houses get the drive
# and the yard: flats and public buildings have lots of their own. On Piqua
# 91% of the flats had no way to the street before this.
FRONT_PATH_KINDS = ("house", "apartment", "church", "civic", "medical", "library")
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


def _outside_doors(tbx_path: str) -> list[tuple[int, int, int, int]]:
    """(outside x, y, inside x, y) of each ground-floor outside door, front first."""
    try:
        key = (tbx_path, os.stat(tbx_path).st_mtime_ns)
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
    for m in re.finditer(r'type="door"[^>]*? x="(\d+)" y="(\d+)" dir="([NW])"', floor):
        x, y, d = int(m.group(1)), int(m.group(2)), m.group(3)
        a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
        if inside(*a) != inside(*b):
            out, into = (a, b) if inside(*b) else (b, a)
            found.append((out[0], out[1], into[0], into[1]))
    if key is not None:
        _OUTSIDE_DOORS_CACHE[key] = found
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
    if not os.path.exists(base):
        shutil.copyfile(bmp, base)
    if os.path.exists(veg_path) and not os.path.exists(veg_base):
        shutil.copyfile(veg_path, veg_base)
    ground = read_rgb(base)
    veg = read_rgb(veg_base) if os.path.exists(veg_base) else None
    h, w = ground.shape[:2]

    def match(colours):
        mask = np.zeros((h, w), dtype=bool)
        for c in colours:
            mask |= same_colour(ground, c)
        return mask

    paved = match(PAVED)
    road = match((C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                  C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE))
    crossable = match(CROSSABLE) & ~occupied
    # Painted for some house already. One block of memory seen two ways: as an
    # array for the whole-map work, and as bytes for the tile-at-a-time loops
    # below, where reading a numpy element costs several times what a list
    # does. The masks that never change are read the same way, as flat lists
    # indexed y * w + x.
    claimed_bytes = bytearray(h * w)
    claimed = np.frombuffer(claimed_bytes, dtype=bool).reshape(h, w)
    crossable_at = crossable.ravel().tolist()
    paved_at = paved.ravel().tolist()
    occupied_at = np.asarray(occupied, dtype=bool).ravel().tolist()
    road_at = road.ravel().tolist()
    walkable_at = ((crossable | paved | road) & ~occupied).ravel().tolist()
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
    rng = random.Random(0xB17E)
    # Reading a thousand freshly written .tbx files is mostly waiting on the
    # disk, so it is done on threads up front; the loop below still runs in
    # order, which keeps the random choices the same.
    from concurrent.futures import ThreadPoolExecutor
    house_files = [r["file"] for r in rows if r.get("kind") in FRONT_PATH_KINDS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        door_lists = dict(zip(house_files, pool.map(
            lambda f: _outside_doors(os.path.join(out_dir, "buildings", f)),
            house_files)))
    for row in rows:
        if row.get("kind") not in FRONT_PATH_KINDS:
            continue
        home = row["kind"] == "house"
        doors = door_lists[row["file"]]
        if not doors:
            continue
        ox, oy, ix, iy = doors[0]
        bx0, by0 = row["tile_x"], row["tile_y"]
        bw, bh = row["width"], row["height"]
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

        if not free(sx, sy):
            continue

        # The drive: beside the house, from the street past the front wall.
        # Ahead of the path, so that a house far back from the street can walk
        # to its own drive.
        there = drive_there(bx0, by0, bw, bh) if home else []
        if not home:
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
                put(bx - px, by - py, C.BIN)
                break

        # The path, shortest way to the pavement or the drive, straight out of
        # the door first. It never crosses ground already painted for another
        # building: a neighbour's stoop, patio or vegetable bed.
        prev = {(sx, sy): None}
        queue = deque([(sx, sy, 0)])
        end = None
        order = [(dx, dy)] + [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if d != (dx, dy)]
        while queue:
            x, y, n = queue.popleft()
            if paved_at[y * w + x]:
                end = (x, y)
                break
            if n >= PATH_MAX_TILES:
                continue
            for ddx, ddy in order:
                nx, ny = x + ddx, y + ddy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in prev \
                        and (paved_at[ny * w + nx] or free(nx, ny)):
                    prev[(nx, ny)] = (x, y)
                    queue.append((nx, ny, n + 1))
        if end is None:
            continue
        walk = []
        step = prev[end]
        while step is not None:
            walk.append(step)
            step = prev[step]
        # If a straight path out of the door reaches the sidewalk or drive within
        # a few steps of the BFS route, prefer the straight line over an L-dogleg.
        if walk and end not in drive_tiles:
            straight_walk = []
            for t in range(max(len(walk) + 4, 1)):
                if t >= PATH_MAX_TILES:
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
        for x, y in walk:
            paint(x, y, C.PAVING_STONE)
        # Fill 90-degree path corners and diagonal sidewalk pockets so grass
        # edge-blends never cut across the walk or where it meets the pavement.
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
        # A stoop: the slab either side of the door step as well.
        for k in (-1, 1):
            if free(sx + px * k, sy + py * k):
                paint(sx + px * k, sy + py * k, C.PAVING_STONE)
        # The mailbox, beside the path where it reaches the street.
        if home and walk and end not in drive_tiles:
            mx, my = walk[0]
            for k in (1, -1):
                if free(mx + px * k, my + py * k):
                    put(mx + px * k, my + py * k, C.MAILBOX)
                    break
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
        for side in (YARD_SIDE, 1, 0):
            u0 = (bx0 if dy else by0) - side
            width = (bw if dy else bh) + 2 * side

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
        dressed += 1

    for row in rows:
        if (row.get("building") not in ("garage", "garages")
                and row.get("kind") != "garage"):
            continue
        doors = _outside_doors(os.path.join(out_dir, "buildings", row["file"]))
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

    if veg is not None and fronts:
        # No tree or bush grows in a doorway.
        for x, y in fronts:
            if 0 <= x < w and 0 <= y < h:
                veg[y, x] = C.VEG_NOTHING
    # The credit for KnoxMap, in the ground near the first spawn house.
    from . import credit_ground
    clear = (match(CROSSABLE) & ~occupied
             & ~np.frombuffer(claimed_bytes, dtype=bool).reshape(h, w))
    where = credit_ground.paint(ground, veg, clear, rows)
    print(f"credit lettering     : " + (f"at tile {where[0]},{where[1]}" if where else "no clear patch"))
    import knoxfiles
    knoxfiles.save(Image.fromarray(ground), bmp, format="BMP")
    if veg is not None:
        knoxfiles.save(Image.fromarray(veg), veg_path, format="BMP")
    return dressed, fences
