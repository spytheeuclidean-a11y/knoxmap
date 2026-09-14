"""Measure a folder of generated .tbx files the way a player would see them.

    python tools/tbx_stats.py output/<map>/buildings

Reads the files themselves rather than the generator's in-memory plans, so it
checks what actually ships: windows per building, roofs hanging over open
ground, and staircases with a wall across the flight.
"""
from __future__ import annotations

import glob
import os
import sys
import xml.etree.ElementTree as ET

STAIR_RUN = 5


def grid_of(floor, w, h):
    vals = [int(v) for v in (floor.find("rooms").text or "").replace("\n", ",").split(",")
            if v.strip()]
    return [vals[y * w:(y + 1) * w] for y in range(h)]


def main(argv):
    folder = argv[1]
    files = sorted(glob.glob(os.path.join(folder, "*.tbx")))
    buildings = windows = wall_tiles = 0
    roof_over = roof_tiles = 0
    flights = blocked = 0
    for path in files:
        root = ET.parse(path).getroot()
        w, h = int(root.get("width")), int(root.get("height"))
        floors = root.findall("floor")
        # The last <floor> is the empty roof floor over the top storey; only
        # the storeys below it have rooms, walls and windows.
        if len(floors) > 1 and not any(v for row in grid_of(floors[-1], w, h) for v in row):
            floors = floors[:-1]
        grids = [grid_of(f, w, h) for f in floors]
        buildings += 1
        for fl, g in zip(floors, grids):
            windows += len(fl.findall("./object[@type='window']"))
            for y in range(h):
                for x in range(w):
                    if not g[y][x]:
                        continue
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if not (0 <= nx < w and 0 <= ny < h and g[ny][nx]):
                            wall_tiles += 1
        top = grids[-1]
        for roof in floors[-1].findall("./object[@type='roof']"):
            rx, ry = int(roof.get("x")), int(roof.get("y"))
            rw, rh = int(roof.get("width")), int(roof.get("height"))
            for y in range(ry, ry + rh):
                for x in range(rx, rx + rw):
                    roof_tiles += 1
                    if not (0 <= x < w and 0 <= y < h and top[y][x]):
                        roof_over += 1
        for lvl, fl in enumerate(floors[:-1]):
            st = fl.find("./object[@type='stairs']")
            if st is None:
                continue
            flights += 1
            x, y, d = int(st.get("x")), int(st.get("y")), st.get("dir")
            dx, dy = (0, 1) if d == "N" else (1, 0)
            run = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
            for g in (grids[lvl], grids[lvl + 1]):
                rooms = {g[ry][rx] if 0 <= rx < w and 0 <= ry < h else 0
                         for rx, ry in run}
                if len(rooms) != 1 or 0 in rooms:
                    blocked += 1
                    break
    print(f"buildings                 : {buildings}")
    print(f"windows per 10 tiles wall : {10 * windows / max(1, wall_tiles):.2f}")
    print(f"roof tiles over open ground: {roof_over} of {roof_tiles} "
          f"({100 * roof_over / max(1, roof_tiles):.1f}%)")
    print(f"flights with a wall across: {blocked} of {flights} "
          f"({100 * blocked / max(1, flights):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
