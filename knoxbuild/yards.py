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

PATH_MAX_TILES = 40
DRIVE_WIDTH = 3
DRIVE_EXTRA = 5          # how far the drive runs past the front of the house
YARD_DEPTH = 9           # back yard, from the back wall to the back fence
YARD_MIN_DEPTH = 4
YARD_SIDE = 2            # how far the fence stands out past the house's sides
PAVED = (C.PALE_CONCRETE, C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
CROSSABLE = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DIRT)
YARD_FENCE_STYLES = ("tall_wooden", "short_wooden", "white_picket", "short_chainlink")

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


def _outside_doors(tbx_path: str) -> list[tuple[int, int, int, int]]:
    """(outside x, y, inside x, y) of each ground-floor outside door, front first."""
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


def _pave_patio(ground, veg, crossable, claimed, cells):
    """Pave only unclaimed lawn so one home's patio cannot overwrite a neighbor's path."""
    h, w = crossable.shape
    paved = []
    for x, y in cells:
        if not (0 <= x < w and 0 <= y < h) or not crossable[y, x] or claimed[y, x]:
            continue
        ground[y, x] = C.PAVING_STONE
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
    claimed = np.zeros((h, w), dtype=bool)     # painted for some house already

    def free(x, y):
        return 0 <= x < w and 0 <= y < h and crossable[y, x] and not claimed[y, x]

    def paint(x, y, colour):
        ground[y, x] = colour
        claimed[y, x] = True
        if veg is not None:
            veg[y, x] = 0

    def put(x, y, colour):
        if veg is not None and free(x, y):
            veg[y, x] = colour
            claimed[y, x] = True

    dressed = 0
    fences = []
    rng = random.Random(0xB17E)
    # Reading a thousand freshly written .tbx files is mostly waiting on the
    # disk, so it is done on threads up front; the loop below still runs in
    # order, which keeps the random choices the same.
    from concurrent.futures import ThreadPoolExecutor
    house_files = [r["file"] for r in rows if r.get("kind") == "house"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        door_lists = dict(zip(house_files, pool.map(
            lambda f: _outside_doors(os.path.join(out_dir, "buildings", f)),
            house_files)))
    for row in rows:
        if row.get("kind") != "house":
            continue
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
                if not (0 <= lx < w and 0 <= ly < h) or occupied[ly, lx]:
                    continue
                # Only where the house really is behind it: beside a door in a
                # corner, one of the two faces open ground.
                wx, wy = lx - dx, ly - dy
                if not (0 <= wx < w and 0 <= wy < h and occupied[wy, wx]):
                    continue
                lights.append((lx, ly, 0, PORCH_LIGHT_LAYER, style[side]))
                break

        if not free(sx, sy):
            continue

        # The path, shortest way to the pavement, straight out of the door first.
        prev = {(sx, sy): None}
        queue = deque([(sx, sy, 0)])
        end = None
        order = [(dx, dy)] + [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if d != (dx, dy)]
        while queue:
            x, y, n = queue.popleft()
            if paved[y, x]:
                end = (x, y)
                break
            if n >= PATH_MAX_TILES:
                continue
            for ddx, ddy in order:
                nx, ny = x + ddx, y + ddy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in prev \
                        and (crossable[ny, nx] or paved[ny, nx]):
                    prev[(nx, ny)] = (x, y)
                    queue.append((nx, ny, n + 1))
        if end is None:
            continue
        walk = []
        step = prev[end]
        while step is not None:
            walk.append(step)
            step = prev[step]
        for x, y in walk:
            paint(x, y, C.PAVING_STONE)
        # A stoop: the slab either side of the door step as well.
        for k in (-1, 1):
            if free(sx + px * k, sy + py * k):
                paint(sx + px * k, sy + py * k, C.PAVING_STONE)
        # The mailbox, beside the path where it reaches the pavement.
        if walk:
            mx, my = walk[0]
            for k in (1, -1):
                if free(mx + px * k, my + py * k):
                    put(mx + px * k, my + py * k, C.MAILBOX)
                    break

        # The drive: beside the house, from the street past the front wall.
        if dx:   # street to the east or west; the front runs north-south
            front = bx0 + (bw if dx > 0 else -1)
            lanes = [(by0 + bh + 1, 1), (by0 - DRIVE_WIDTH - 1, 1)]
        else:
            front = by0 + (bh if dy > 0 else -1)
            lanes = [(bx0 + bw + 1, 1), (bx0 - DRIVE_WIDTH - 1, 1)]
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
                if all(0 <= x < w and 0 <= y < h and paved[y, x] for x, y in line) and t > 0:
                    break
                if not all(free(x, y) for x, y in line):
                    strip = None
                    break
                strip.extend(line)
                t += 1
            if strip and t < PATH_MAX_TILES:
                for x, y in strip:
                    paint(x, y, C.DARK_ASPHALT)
                if drives is not None:
                    # The strip starts beside the house: its first five rows.
                    top = strip[:DRIVE_WIDTH * 5]
                    xs, ys = [p[0] for p in top], [p[1] for p in top]
                    drives.append((min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
                # The dustbin at the top of the drive, on the lawn beside it.
                bx, by = strip[0]
                put(bx - px, by - py, C.BIN)
                break

        # The back yard. Knox County's are lived in: a patio by the back door
        # with a grill and a table, a washing line, a vegetable bed, all
        # inside a fence that meets the house with a gap for the gate. A
        # fenced square of empty lawn standing off the house was no use.
        bdx, bdy = -dx, -dy                          # away from the street
        ax, ay = (1, 0) if dy else (0, 1)            # along the back wall
        back = (by0 - 1 if dy > 0 else by0 + bh) if dy else (bx0 - 1 if dx > 0 else bx0 + bw)
        # As wide as the house and a little over, narrower where the
        # neighbours are close; as deep as there is room for.
        for side in (YARD_SIDE, 1, 0):
            u0 = (bx0 if dy else by0) - side
            width = (bw if dy else bh) + 2 * side

            def at(u, v, u0=u0):
                """World tile u along the back wall, v rows back from it."""
                return ((u0 + u, back + bdy * v) if dy else (back + bdx * v, u0 + u))

            depth = 0
            for v in range(YARD_DEPTH):
                if not all(free(*at(u, v)) for u in range(width)):
                    break
                depth = v + 1
            if depth >= YARD_MIN_DEPTH:
                break
        if depth >= YARD_MIN_DEPTH:
            style = YARD_FENCE_STYLES[(bx0 * 7 + by0 * 13) % len(YARD_FENCE_STYLES)]

            # Fence corners as tile-corner coordinates, far side of row depth-1.
            if dy:
                # Edges between rows: the house's back wall, and past the last
                # yard row.
                wall_y = back + (0 if bdy > 0 else 1)
                far_y = back + bdy * depth + (0 if bdy > 0 else 1)
                a, b = u0, u0 + width
                house_a, house_b = bx0, bx0 + bw
                fences.append(([(house_a, wall_y), (a, wall_y), (a, far_y), (b, far_y),
                                (b, wall_y), (house_b, wall_y)], style,
                               [(house_b, wall_y)]))
            else:
                wall_x = back + (0 if bdx > 0 else 1)
                far_x = back + bdx * depth + (0 if bdx > 0 else 1)
                a, b = u0, u0 + width
                house_a, house_b = by0, by0 + bh
                fences.append(([(wall_x, house_a), (wall_x, a), (far_x, a), (far_x, b),
                                (wall_x, b), (wall_x, house_b)], style,
                               [(wall_x, house_b)]))
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
                claimed[y, x] = True
                return True

            # Patio: stone outside the back door, three deep; behind the middle
            # of the house if the back door is not on the yard side.
            mid = width // 2
            for bxo, byo, _bxi, _byi in doors[1:]:
                wx, wy = bx0 + bxo, by0 + byo
                u, v = ((wx - u0, (wy - back) * bdy) if dy else (wy - u0, (wx - back) * bdx))
                if v == 0 and 2 <= u < width - 3:
                    mid = u
                    break
            patio_tiles = []
            for v in range(min(3, depth - 1)):
                for u in range(mid - 2, mid + 3):
                    patio_tiles.extend(_pave_patio(
                        ground, veg, crossable, claimed, (at(u, v),)))
            place(mid - 2, 1, C.GRILL)
            if dy:
                place(mid, 1, C.TABLE_X0); place(mid + 1, 1, C.TABLE_X1)
                place(mid, 0, C.CHAIR_N); place(mid + 1, 2, C.CHAIR_S)
            else:
                place(mid, 1, C.TABLE_Y0); place(mid, 2, C.TABLE_Y1)
                place(mid - 1, 1, C.CHAIR_W); place(mid + 1, 2, C.CHAIR_E)
            for x, y in patio_tiles:
                claimed[y, x] = True

            # Washing line along the back fence, if the yard is wide enough.
            v_line = depth - 2
            if width >= 9 and v_line >= 3:
                ends = (C.LINE_X0, C.LINE_XM, C.LINE_X1) if dy else (C.LINE_Y0, C.LINE_YM, C.LINE_Y1)
                for k in range(5):
                    place(width - 6 + k, v_line, ends[0] if k == 0 else ends[2] if k == 4 else ends[1])

            # A raised vegetable bed in the far corner, soil to plant in. Its
            # frame pieces go by map direction (the editor's 3x3 planter,
            # stretched): west column, middle, east column; north row, middle,
            # south row.
            bd_ = min(4, depth - 3)
            if bd_ >= 3:
                cells = [at(1 + i, depth - 1 - j) for i in range(3) for j in range(bd_)]
                if all(free(x, y) for x, y in cells):
                    xs_ = sorted({x for x, _ in cells}); ys_ = sorted({y for _, y in cells})
                    frame = {("W", "N"): C.BED_NW, ("W", "M"): C.BED_W, ("W", "S"): C.BED_SW,
                             ("M", "N"): C.BED_N, ("M", "M"): C.BED_SOIL, ("M", "S"): C.BED_S,
                             ("E", "N"): C.BED_NE, ("E", "M"): C.BED_E, ("E", "S"): C.BED_SE}
                    for x, y in cells:
                        col = "W" if x == xs_[0] else "E" if x == xs_[-1] else "M"
                        row = "N" if y == ys_[0] else "S" if y == ys_[-1] else "M"
                        paint(x, y, C.DIRT)
                        veg[y, x] = frame[(col, row)]
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
        if not (0 <= sx < w and 0 <= sy < h) or occupied[sy, sx]:
            continue
        if road[sy, sx]:
            continue

        traversable = (crossable | paved | road) & ~occupied & ~claimed
        previous = {start: None}
        queue = deque([(sx, sy, 0)])
        end = None
        while queue:
            x, y, distance = queue.popleft()
            if road[y, x]:
                end = (x, y)
                break
            if distance >= PATH_MAX_TILES:
                continue
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if (0 <= nx < w and 0 <= ny < h and (nx, ny) not in previous
                        and traversable[ny, nx]):
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
                if (0 <= px < w and 0 <= py < h and not road[py, px]
                        and not occupied[py, px] and not claimed[py, px]
                        and (crossable[py, px] or paved[py, px])):
                    paint(px, py, C.DARK_ASPHALT)
                    painted.append((px, py))
        if drives is not None and painted:
            near_garage = painted[:min(len(painted), DRIVE_WIDTH * 5)]
            xs, ys = [point[0] for point in near_garage], [point[1] for point in near_garage]
            drives.append((min(xs), min(ys), max(xs) - min(xs) + 1,
                           max(ys) - min(ys) + 1))

    if veg is not None and fronts:
        # No tree or bush grows in a doorway.
        for x, y in fronts:
            if 0 <= x < w and 0 <= y < h:
                veg[y, x] = C.VEG_NOTHING
    Image.fromarray(ground).save(bmp, format="BMP")
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return dressed, fences
