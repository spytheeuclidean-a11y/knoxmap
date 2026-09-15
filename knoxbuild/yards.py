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

        # The back yard fence: out from the back corners, round the yard.
        style = YARD_FENCE_STYLES[(bx0 * 7 + by0 * 13) % len(YARD_FENCE_STYLES)]
        if dx:
            back = bx0 - 1 if dx > 0 else bx0 + bw
            ys = (by0 - YARD_SIDE, by0 + bh + YARD_SIDE)
            depth = 0
            for d in range(1, YARD_DEPTH + 1):
                x = back - dx * d
                if not all(free(x, y) for y in range(ys[0], ys[1])):
                    break
                depth = d
            if depth >= YARD_MIN_DEPTH:
                xb = back - dx * depth
                xf = back + (1 if dx > 0 else 0)
                fences.append(([(xf, ys[0]), (xb, ys[0]), (xb, ys[1]), (xf, ys[1])], style))
        else:
            back = by0 - 1 if dy > 0 else by0 + bh
            xs = (bx0 - YARD_SIDE, bx0 + bw + YARD_SIDE)
            depth = 0
            for d in range(1, YARD_DEPTH + 1):
                y = back - dy * d
                if not all(free(x, y) for x in range(xs[0], xs[1])):
                    break
                depth = d
            if depth >= YARD_MIN_DEPTH:
                yb = back - dy * depth
                yf = back + (1 if dy > 0 else 0)
                fences.append(([(xs[0], yf), (xs[0], yb), (xs[1], yb), (xs[1], yf)], style))
        dressed += 1

    Image.fromarray(ground).save(bmp, format="BMP")
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return dressed, fences
