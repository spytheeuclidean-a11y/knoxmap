"""Front paths: from each house's front door to the pavement or the road.

Knox County's houses all have one; generated houses stood in unbroken lawn
with the front door opening onto grass. The door is only known once the
building is laid out, after the terrain was drawn, so the paths are painted
into the terrain bitmap here, from the renderer's untouched copy of it
(<map>_ground_base.bmp) so that building again does not keep old paths.
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
# What a path may end on: pavement or tarmac.
PAVED = (C.PALE_CONCRETE, C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
# What a path may cross: grass and dirt, not water or anything built.
CROSSABLE = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DIRT)


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


def paint_paths(out_dir: str, map_name: str, rows: list[dict], occupied) -> int:
    """Paint a path for every house in `rows` (the placements). Returns count."""
    bmp = os.path.join(out_dir, f"{map_name}.bmp")
    base = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    veg_path = os.path.join(out_dir, f"{map_name}_veg.bmp")
    if not os.path.exists(bmp):
        return 0
    if not os.path.exists(base):
        shutil.copyfile(bmp, base)
    ground = np.array(Image.open(base).convert("RGB"))
    veg = np.array(Image.open(veg_path).convert("RGB")) if os.path.exists(veg_path) else None
    h, w = ground.shape[:2]

    def match(colours):
        mask = np.zeros((h, w), dtype=bool)
        for c in colours:
            mask |= np.all(ground == c, axis=2)
        return mask

    paved = match(PAVED)
    crossable = match(CROSSABLE) & ~occupied
    painted = 0
    for row in rows:
        if row.get("kind") != "house":
            continue
        door = _front_door(os.path.join(out_dir, "buildings", row["file"]))
        if door is None:
            continue
        ox, oy, ix, iy = door
        sx, sy = row["tile_x"] + ox, row["tile_y"] + oy
        dx, dy = ox - ix, oy - iy          # straight out of the door first
        if not (0 <= sx < w and 0 <= sy < h) or not crossable[sy, sx]:
            continue
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
        step = prev[end]
        while step is not None:
            ground[step[1], step[0]] = C.PALE_CONCRETE
            if veg is not None:
                veg[step[1], step[0]] = 0
            step = prev[step]
        painted += 1
    Image.fromarray(ground).save(bmp, format="BMP")
    if veg is not None:
        Image.fromarray(veg).save(veg_path, format="BMP")
    return painted
