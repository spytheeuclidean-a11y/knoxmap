"""A whole map as cell sources for `knoxlots compile`: ground, edge blends, buildings, tables.

    python tools/map_source.py <map folder> <out folder> [--seed N] [--worlded-seams]

The map folder is what KnoxMap writes: <name>.bmp, <name>_veg.bmp, <name>.pzw, buildings/*.tbx
and <name>_ZombieSpawnMap.bmp. For every 256-tile cell this makes the terrain tiles (Rules.txt,
Blends.txt), puts the buildings on them, and writes the room and building tables of the header.

How buildings go onto the ground (see merge_stack): a square with a room has the building's
tiles and none of the ground's; any other square keeps its ground and gets the building's tiles
on top (an outer wall stands on grass).
"""
from __future__ import annotations

import os
import re
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knoxstop  # noqa: E402
from knoxbuild import bitmaps  # noqa: E402
from knoxbuild.blends import blend_layers, load_blends  # noqa: E402
from knoxbuild.buildheader import cell_tables, placed_rooms  # noqa: E402
from knoxbuild.buildtiles import compose_lots, parse_tbx, parse_tbx_rooms, tile_name  # noqa: E402
from knoxbuild.kcell import SIDE, cell_source  # noqa: E402
from knoxbuild.rules import load_rules  # noqa: E402
from knoxbuild.terrain import Palette, ground_layers, stack_order  # noqa: E402
from tools.terrain_source import ORIGIN_X, project_origin, rules_path  # noqa: E402


def read_lots(project: str):
    """[(name, tx, ty, base level, width, height)] in project order, with world tile positions."""
    name = os.path.basename(os.path.normpath(project))
    lots, cell = [], None
    for line in open(os.path.join(project, f"{name}.pzw"), encoding="utf-8"):
        m = re.match(r'\s*<cell x="(\d+)" y="(\d+)"', line)
        if m:
            cell = (int(m[1]), int(m[2]))
        m = re.search(r'<lot x="(\d+)" y="(\d+)" level="(-?\d+)" width="(\d+)" height="(\d+)" '
                      r'map="buildings/([^"]+)\.tbx"', line)
        if m and cell:
            lots.append((m[6], cell[0] * 300 + int(m[1]), cell[1] * 300 + int(m[2]), int(m[3]),
                         int(m[4]), int(m[5])))
    return lots


def merge_stack(ground: list[str], building: list[str], has_room: bool) -> list[str]:
    """One square's tiles from its ground and its building's."""
    return building if has_room else ground + building


def _free_gb() -> float:
    from tools.compile_map import _free_memory_gb
    return _free_memory_gb() or 8.0      # unknown: assume enough for a few


# A row worker peaked near 600 MB on a 418-cell town (West_Union, 196 lots in its widest row).
GB_PER_ROW_WORKER = 1


MARGIN = 8     # tiles a building's output can reach past the lot the project gives it


def _row(project: str, out: str, cy: int, band: list[tuple], placed, seed: int, seams: bool,
         size: tuple[int, int]) -> int:
    """Write the cell sources of one row of cells. `band` holds the lots that reach the row,
    (name, tx, ty, base level), in project order: a square's tiles depend only on the lots
    covering it, so these are all the row needs."""
    name = os.path.basename(os.path.normpath(project))
    land_path = os.path.join(project, f"{name}.bmp")
    veg_path = os.path.join(project, f"{name}_veg.bmp")
    w, h = size
    origin = project_origin(project)
    ox, oy = origin
    rules_file = rules_path()
    rules = load_rules(rules_file)
    blends = load_blends(os.path.join(os.path.dirname(rules_file), "Blends.txt"))
    parsed = [(parse_tbx(open(os.path.join(project, "buildings", f"{t}.tbx"), encoding="utf-8").read()),
               tx, ty, lv) for t, tx, ty, lv in band]
    world = compose_lots(parsed)
    room_squares = set()
    for b, tx, ty, base in parsed:
        for z, floor in enumerate(b.floors):
            for y, row in enumerate(floor.rooms):
                for x, v in enumerate(row):
                    if v > 0:
                        room_squares.add((tx + x, ty + y, base + z))
    del parsed
    pal = Palette()
    written = 0
    wy0 = cy * SIDE - oy
    y_lo, y_hi = max(wy0 - 1, 0), min(wy0 + SIDE + 1, h)
    land_strip = bitmaps.read_rgb_rows(land_path, y_lo, y_hi, w)
    veg_strip = bitmaps.read_rgb_rows(veg_path, y_lo, y_hi, w)
    for cx in range(ox // SIDE, (ox + w - 1) // SIDE + 1):
        wx0 = cx * SIDE - ox
        win = SIDE + 2
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
        layers = {k: v[1:-1, 1:-1] for k, v in layers.items()}
        inside = inside[1:-1, 1:-1]
        order = stack_order(layers)

        # the stacks of the cell: level 0 is ground and buildings, above and below it
        # (basements) buildings only
        stacks: dict[tuple[int, int, int], list[str]] = {}
        for yy in range(SIDE):
            for xx in range(SIDE):
                wx, wy = wx0 + xx, wy0 + yy
                g = []
                bt = world.get((wx, wy, 0), [])
                if inside[yy, xx]:
                    # a fence clears the ground's furniture (a garden bed under it); walls do not
                    fenced = any(t.startswith("fencing_") for t in bt)
                    g = [tile_name(pal.names[layers[k][yy, xx]]) for k in order
                         if layers[k][yy, xx] and not (fenced and k == "0_Furniture")]
                st = merge_stack(g, bt, (wx, wy, 0) in room_squares)
                if st:
                    stacks[(xx, yy, 0)] = st
        for (wx, wy, z), bt in world.items():
            if z != 0 and wx0 <= wx < wx0 + SIDE and wy0 <= wy < wy0 + SIDE:
                stacks[(wx - wx0, wy - wy0, z)] = bt
        # A building's rooms are listed in the cell of its north-west corner,
        # which need not hold a square of its basement: the cell's levels
        # cover what its room table names as well as its squares.
        rooms, buildings = cell_tables(cx, cy, placed, origin)
        levels_used = [z for _, _, z in stacks] + [r["z"] for r in rooms]
        min_z = min(min(levels_used, default=0), 0)
        nlev = max(levels_used, default=0) + 1 - min_z
        depth = max((len(st) for st in stacks.values()), default=1)
        names: list[str] = []
        index: dict[str, int] = {}
        arrays = [[np.zeros((SIDE, SIDE), np.int64) for _ in range(depth)] for _ in range(nlev)]
        for (xx, yy, z), st in stacks.items():
            for k, t in enumerate(st):
                i = index.get(t)
                if i is None:
                    i = index[t] = len(names) + 1
                    names.append(t)
                arrays[z - min_z][k][yy, xx] = i
        room_tuples = [(r["name"], r["z"], [tuple(x) for x in r["rects"]], []) for r in rooms]
        data = cell_source(cx, cy, names, arrays, min_z=min_z, rooms=room_tuples,
                           buildings=buildings)
        with open(os.path.join(out, f"cell_{cx}_{cy}.kcell"), "wb") as f:
            f.write(data)
        written += 1
    return written


# Below this many buildings the pool costs more to start than it saves.
PARALLEL_READ_FROM = 300


def _read_rooms(project: str, names: list[str]) -> list:
    """The room tables' view of each building (knoxbuild.buildtiles.parse_tbx_rooms),
    each floor's room numbers as one small array. As lists of lists, the rooms of a
    232,000-building map held about 10 GB until the room tables were made."""
    out = []
    for n in names:
        with open(os.path.join(project, "buildings", f"{n}.tbx"), encoding="utf-8") as f:
            b = parse_tbx_rooms(f.read())
        for floor in b.floors:
            floor.rooms = np.asarray(floor.rooms, dtype=np.int32).reshape(b.height, b.width)
        out.append(b)
    return out


def _gather(pool, pending: dict, should_stop, take) -> None:
    """Hand each job of `pool` to `take(job, key)` as it finishes, looking at
    `should_stop` at least once a second, then shut the pool.

    On a stop - or anything else going wrong - the workers are ended rather
    than waited for. Waiting meant a Stop pressed while a city was being read,
    or its rows of cells made, did nothing for minutes: each worker finished
    the big piece it was on first. What they leave half done is not kept: a
    row is only marked finished here, once its worker has returned."""
    from concurrent.futures import FIRST_COMPLETED, wait
    try:
        while pending:
            finished, _ = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for fut in finished:
                take(fut, pending.pop(fut))
            knoxstop.check(should_stop, "the compile")
    except BaseException:
        end = getattr(pool, "terminate_workers", None)      # Python 3.14+
        if end is not None:
            end()
        else:
            pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()


# Buildings read per job: small, so a stop or the last few jobs wait seconds.
READ_BATCH = 500


def read_buildings(project: str, names: list[str], workers: int | None = None, should_stop=None) -> list:
    """Every building the lots name, in order, parsed for the room tables - across
    processes once there are enough of them, since reading is where a big map
    spent minutes before a single cell was built."""
    from concurrent import futures
    workers = workers or os.cpu_count() or 1
    if len(names) < PARALLEL_READ_FROM or workers < 2:
        return _read_rooms(project, names)
    size = max(50, min(READ_BATCH, len(names) // (workers * 4)))
    parts: dict = {}
    pool = futures.ProcessPoolExecutor(max_workers=workers)
    pending = {pool.submit(_read_rooms, project, names[s:s + size]): s
               for s in range(0, len(names), size)}
    _gather(pool, pending, should_stop, lambda fut, s: parts.__setitem__(s, fut.result()))
    # in order: the result is the lots' order
    return [b for s in sorted(parts) for b in parts[s]]


def _row_done(out: str, cy: int) -> str:
    return os.path.join(out, f"row_{cy}.done")


def make_map_source(project: str, out: str, seed: int = 1, seams: bool = False,
                    workers: int | None = None, should_stop=None, on_row=None, on_start=None,
                    resume: bool = False) -> int:
    """Write the cell sources of a map into `out`, one process per row of cells.

    Each finished row is marked in `out`. With `resume`, the rows a stopped or
    failed run already finished are kept rather than made again - and when that
    is all of them, the buildings are not even read. The caller decides whether
    what is in `out` is still from the same map (compile_map.compile_rust)."""
    from concurrent import futures
    name = os.path.basename(os.path.normpath(project))
    head = bitmaps._bmp_header(os.path.join(project, f"{name}.bmp"))
    w, h = head[0], head[1]
    origin = project_origin(project)
    cys = list(range(origin[1] // SIDE, (origin[1] + h - 1) // SIDE + 1))
    rows = len(cys)
    os.makedirs(out, exist_ok=True)
    done = [cy for cy in cys if resume and os.path.exists(_row_done(out, cy))]
    todo = [cy for cy in cys if cy not in done]

    written = 0
    if todo:
        lots = read_lots(project)
        # Room tables need every building at once (they touch, and a later lot takes
        # squares). Only the rooms are kept; the parsed buildings go.
        parsed = [(b, tx, ty, lv) for b, (_t, tx, ty, lv, _w, _h) in zip(
            read_buildings(project, [t for t, *_ in lots], workers, should_stop), lots)]
        kept = [(t, (b, tx, ty, lv)) for (t, *_), (b, tx, ty, lv) in zip(lots, parsed) if b.floors]
        placed = placed_rooms([lot for _t, lot in kept])
        reach = [(b.width, b.height) for b, *_ in parsed]
        del parsed, kept

        if on_start:
            on_start()
        bands = {}
        for cy in todo:
            lo = cy * SIDE - origin[1] - MARGIN
            hi = cy * SIDE - origin[1] + SIDE + MARGIN
            bands[cy] = [(t, tx, ty, lv) for (t, tx, ty, lv, _w, _h), (_bw, bh) in zip(lots, reach)
                         if ty - MARGIN < hi and ty + bh + MARGIN > lo]

        def finished(cy: int, n: int) -> None:
            with open(_row_done(out, cy), "w", encoding="utf-8"):
                pass
            if on_row:
                on_row(len(done) + n, rows)

        if workers is None:
            workers = max(1, min(os.cpu_count() or 1, int(_free_gb() // GB_PER_ROW_WORKER) or 1))
        if workers == 1:
            for n, cy in enumerate(todo, 1):
                if should_stop and should_stop():
                    raise knoxstop.Stopped("the compile")
                written += _row(project, out, cy, bands[cy], placed, seed, seams, (w, h))
                finished(cy, n)
        else:
            pool = futures.ProcessPoolExecutor(max_workers=workers)
            jobs = {pool.submit(_row, project, out, cy, bands[cy], placed, seed, seams, (w, h)): cy
                    for cy in todo}

            def take(fut, cy: int) -> None:
                nonlocal written
                written += fut.result()
                finished(cy, len(todo) - len(jobs))

            _gather(pool, jobs, should_stop, take)
    name = os.path.basename(os.path.normpath(project))
    spawn = f"{name}_ZombieSpawnMap.bmp"
    lines = ["format = knoxlots-source 1", f"origin_x = {origin[0]}",
             f"origin_y = {origin[1]}"]
    if os.path.exists(os.path.join(project, spawn)):
        shutil.copy2(os.path.join(project, spawn), os.path.join(out, "spawn.bmp"))
        lines.append("spawn_map = spawn.bmp")
    with open(os.path.join(out, "source.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return written


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 1
    if "--seed" in argv:
        args.remove(argv[argv.index("--seed") + 1])
    if len(args) != 2:
        print(__doc__)
        return 2
    n = make_map_source(args[0], args[1], seed, seams="--worlded-seams" in argv)
    print(f"{n} cell sources written to {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
