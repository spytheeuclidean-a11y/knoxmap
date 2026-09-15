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
import re
import shutil
from collections import deque

import numpy as np
from PIL import Image

from generator import pz_colors as C

PATH_MAX_TILES = 40
DRIVE_WIDTH = 3
DRIVE_EXTRA = 5          # how far the drive runs past the front of the house
YARD_DEPTH = 9           # back yard, from the back wall to the back fence
YARD_MIN_DEPTH = 4
YARD_SIDE = 2            # how far the fence stands out past the house's sides
PAVED = (C.PALE_CONCRETE, C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
CROSSABLE = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DIRT)
YARD_FENCE_STYLES = ("tall_wooden", "short_wooden", "white_picket", "short_chainlink")


def _front_door(tbx_path: str) -> tuple[int, int, int, int] | None:
    """(outside x, y, inside x, y) of the ground floor's first outside door."""
    text = open(tbx_path, encoding="utf-8").read()
    first = text.split("<floor>", 2)
    if len(first) < 2:
        return None
    floor = first[1]
    grid_text = re.search(r"<rooms>(.*?)</rooms>", floor, re.S)
    if not grid_text:
        return None
    grid = [[int(v) for v in row.strip().strip(",").split(",")]
            for row in grid_text.group(1).strip().splitlines() if row.strip()]
    h, w = len(grid), len(grid[0])

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and grid[y][x] != 0

    for m in re.finditer(r'type="door"[^>]*? x="(\d+)" y="(\d+)" dir="([NW])"', floor):
        x, y, d = int(m.group(1)), int(m.group(2)), m.group(3)
        a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
        if inside(*a) != inside(*b):
            out, into = (a, b) if inside(*b) else (b, a)
            return out[0], out[1], into[0], into[1]
    return None


def paint_paths(out_dir: str, map_name: str, rows: list[dict], occupied) -> tuple[int, list]:
    """Dress every house in `rows`. Returns (houses dressed, back-yard fence lines)."""
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
    ground = np.array(Image.open(base).convert("RGB"))
    veg = np.array(Image.open(veg_base).convert("RGB")) if os.path.exists(veg_base) else None
    h, w = ground.shape[:2]

    def match(colours):
        mask = np.zeros((h, w), dtype=bool)
        for c in colours:
            mask |= np.all(ground == c, axis=2)
        return mask

    paved = match(PAVED)
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
    for row in rows:
        if row.get("kind") != "house":
            continue
        door = _front_door(os.path.join(out_dir, "buildings", row["file"]))
        if door is None:
            continue
        ox, oy, ix, iy = door
        bx0, by0 = row["tile_x"], row["tile_y"]
        bw, bh = row["width"], row["height"]
        sx, sy = bx0 + ox, by0 + oy
        dx, dy = ox - ix, oy - iy          # out of the door, towards the street
        px, py = -dy, dx                   # along the front of the house
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
        if dy:
            back = by0 - 1 if dy > 0 else by0 + bh  # first row behind the house
            u0 = bx0 - YARD_SIDE
            width = bw + 2 * YARD_SIDE
        else:
            back = bx0 - 1 if dx > 0 else bx0 + bw
            u0 = by0 - YARD_SIDE
            width = bh + 2 * YARD_SIDE

        def at(u, v):
            """World tile u along the back wall, v rows back from it."""
            return ((u0 + u, back + bdy * v) if dy else (back + bdx * v, u0 + u))

        depth = 0
        for v in range(YARD_DEPTH):
            if not all(free(*at(u, v)) for u in range(width)):
                break
            depth = v + 1
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
                                (b, wall_y), (house_b + 1, wall_y)], style))
            else:
                wall_x = back + (0 if bdx > 0 else 1)
                far_x = back + bdx * depth + (0 if bdx > 0 else 1)
                a, b = u0, u0 + width
                house_a, house_b = by0, by0 + bh
                fences.append(([(wall_x, house_a), (wall_x, a), (far_x, a), (far_x, b),
                                (wall_x, b), (wall_x, house_b + 1)], style))
            # (The last stretch stops a tile short of the house: the gate.)

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

            # Patio: stone behind the middle of the house, three deep.
            mid = width // 2
            for v in range(min(3, depth - 1)):
                for u in range(mid - 2, mid + 3):
                    x, y = at(u, v)
                    if free(x, y):
                        paint(x, y, C.PAVING_STONE)
                        claimed[y, x] = False       # furniture may stand on it
            place(mid - 2, 1, C.GRILL)
            if dy:
                place(mid, 1, C.TABLE_X0); place(mid + 1, 1, C.TABLE_X1)
                place(mid, 0, C.CHAIR_N); place(mid + 1, 2, C.CHAIR_S)
            else:
                place(mid, 1, C.TABLE_Y0); place(mid, 2, C.TABLE_Y1)
                place(mid - 1, 1, C.CHAIR_W); place(mid + 1, 2, C.CHAIR_E)

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

    Image.fromarray(ground).save(bmp, format="BMP")
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return dressed, fences
