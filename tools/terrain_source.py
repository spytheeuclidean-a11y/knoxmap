"""Cell sources for the ground of a map, for `knoxlots compile`.

    python tools/terrain_source.py <map folder> <out folder> [--seed N] [--workers N]
                                   [--worlded-seams]

Reads <name>.bmp and <name>_veg.bmp from the map folder, applies Rules.txt and the edge
blends of Blends.txt, and writes one cell_<x>_<y>.kcell per 256-tile cell plus source.txt.
Ground only: no buildings yet. `--worlded-seams` breaks the blends at every 300-tile
line the way WorldEd does (to compare with it); by default they run across the map.

The pictures are read a strip at a time (one row of cells and a margin), never whole, so
the size of the map does not decide the memory used; rows of cells run in separate
processes. The result does not depend on how many.
"""
from __future__ import annotations

import concurrent.futures
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knoxpaths  # noqa: E402
from knoxbuild import bitmaps  # noqa: E402
from knoxbuild.blends import blend_layers, load_blends  # noqa: E402
from knoxbuild.kcell import SIDE, cell_source  # noqa: E402
from knoxbuild.rules import load_rules  # noqa: E402
from knoxbuild.terrain import Palette, ground_layers, stack_order  # noqa: E402

ORIGIN_X = 70 * 300       # the world's west edge in lot-file tiles (worldOrigin 70,0)


def rules_path() -> str:
    tools = knoxpaths.tools_dir() if hasattr(knoxpaths, "tools_dir") else None
    for base in (tools, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "vendor", "PZMappingTools")):
        if base and os.path.exists(os.path.join(base, "config", "Rules.txt")):
            return os.path.join(base, "config", "Rules.txt")
    raise FileNotFoundError("Rules.txt not found")


_LOADED: dict = {}


def _rules_and_blends(rules_file: str):
    """The rules, read once in each process however many rows it is given."""
    if rules_file not in _LOADED:
        _LOADED[rules_file] = (load_rules(rules_file),
                               load_blends(os.path.join(os.path.dirname(rules_file), "Blends.txt")))
    return _LOADED[rules_file]


def _one_row(job: tuple) -> int:
    """All the cells in one row of cells; returns how many were written."""
    land_path, veg_path, out, cy, w, h, seed, rules_file, seams = job
    rules, blends = _rules_and_blends(rules_file)
    pal = Palette()
    wy0 = cy * SIDE
    y_lo, y_hi = max(wy0 - 1, 0), min(wy0 + SIDE + 1, h)
    # the whole width of the strip once; cells are cut from it
    land_strip = bitmaps.read_rgb_rows(land_path, y_lo, y_hi, w)
    veg_strip = bitmaps.read_rgb_rows(veg_path, y_lo, y_hi, w)
    n = 0
    for cx in range(ORIGIN_X // SIDE, (ORIGIN_X + w - 1) // SIDE + 1):
        wx0 = cx * SIDE - ORIGIN_X          # the cell's west edge in picture pixels
        win = SIDE + 2                      # the cell and one square all round it
        lw = np.zeros((win, win, 3), np.uint8)
        vg = np.zeros((win, win, 3), np.uint8)
        inside = np.zeros((win, win), bool)
        x_lo, x_hi = max(wx0 - 1, 0), min(wx0 + SIDE + 1, w)
        if x_lo < x_hi and y_lo < y_hi:
            sx, sy = x_lo - (wx0 - 1), y_lo - (wy0 - 1)
            rows, cols = slice(sy, sy + y_hi - y_lo), slice(sx, sx + x_hi - x_lo)
            lw[rows, cols] = land_strip[:, x_lo:x_hi]
            vg[rows, cols] = veg_strip[:, x_lo:x_hi]
            inside[rows, cols] = True
        layers = ground_layers(lw, vg, rules, pal, seed, x0=wx0 - 1, y0=wy0 - 1)
        layers = {k: np.where(inside, v, 0) for k, v in layers.items()}
        if "0_Floor" in layers:
            layers.update(blend_layers(layers["0_Floor"], rules, blends, pal, seed,
                                       x0=wx0 - 1, y0=wy0 - 1, seam=300 if seams else None))
        layers = {k: v[1:-1, 1:-1] for k, v in layers.items()}        # back to the cell itself
        order = stack_order(layers)
        arrays = [layers[k] for k in order] or [np.zeros((SIDE, SIDE), np.int64)]
        # Only the names this cell uses, so each file stays small.
        used = np.unique(np.concatenate([a.ravel() for a in arrays]))
        used = used[used > 0]
        remap = np.zeros(len(pal.names), np.int64)
        remap[used] = np.arange(1, len(used) + 1)
        data = cell_source(cx, cy, [pal.names[i] for i in used], [[remap[a] for a in arrays]])
        with open(os.path.join(out, f"cell_{cx}_{cy}.kcell"), "wb") as f:
            f.write(data)
        n += 1
    return n


def make_sources(project: str, out: str, seed: int = 1, rules_file: str | None = None,
                 seams: bool = False, workers: int | None = None, progress=None) -> int:
    name = os.path.basename(os.path.normpath(project))
    land_path = os.path.join(project, f"{name}.bmp")
    veg_path = os.path.join(project, f"{name}_veg.bmp")
    head = bitmaps._bmp_header(land_path)
    if head is None:
        raise ValueError(f"{land_path} is not a plain BMP")
    w, h = head[0], head[1]
    rules_file = rules_file or rules_path()
    os.makedirs(out, exist_ok=True)
    jobs = [(land_path, veg_path, out, cy, w, h, seed, rules_file, seams)
            for cy in range((h + SIDE - 1) // SIDE)]
    workers = workers if workers is not None else max(1, min((os.cpu_count() or 2) - 1, 8))
    n = 0
    if workers <= 1 or len(jobs) == 1:
        for j in jobs:
            n += _one_row(j)
            if progress:
                progress(n)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            for count in pool.map(_one_row, jobs):
                n += count
                if progress:
                    progress(n)
    spawn = f"{name}_ZombieSpawnMap.bmp"
    lines = ["format = knoxlots-source 1", f"origin_x = {ORIGIN_X}", "origin_y = 0"]
    if os.path.exists(os.path.join(project, spawn)):
        shutil.copy2(os.path.join(project, spawn), os.path.join(out, "spawn.bmp"))
        lines.append("spawn_map = spawn.bmp")
    with open(os.path.join(out, "source.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return n


def main(argv: list[str]) -> int:
    def value(flag):
        return argv[argv.index(flag) + 1] if flag in argv else None

    args = [a for a in argv if not a.startswith("--")]
    for flag in ("--seed", "--workers"):
        if value(flag) in args:
            args.remove(value(flag))
    if len(args) != 2:
        print(__doc__)
        return 2
    workers = int(value("--workers")) if value("--workers") else None
    n = make_sources(args[0], args[1], int(value("--seed") or 1), seams="--worlded-seams" in argv,
                     workers=workers)
    print(f"{n} cell sources written to {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
