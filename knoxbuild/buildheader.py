"""The room and building tables of a lot header, from the buildings placed in a cell.

Worked out from WorldEd's headers for hand-made buildings, a real house and a map of 113
real buildings:

- A building contributes one room entry for every room number that has squares on a floor,
  floor by floor from the bottom, and by room number within a floor. The entry is named after
  the room definition (`Name`), sits on that level, and covers exactly the room's squares.
- The squares are cut into rectangles by a scan: take the first free square in row order,
  extend right as far as the room goes, then extend down while the row below has a run of
  exactly that width starting at the same column.
- A building entry lists the indexes of its rooms. A building is listed in the one cell that
  holds its north-west corner, with its rectangles whole even where they run past the cell's edge.
- Entries come by the 300-tile source cell the building is placed in, row by row (across, then
  down), and in project order within a source cell.

Not done: room objects (a few scattered markers in a minority of buildings; they follow no rule
the data shows). The tables are written without them.
"""
from __future__ import annotations

CELL = 256
ORIGIN_X = 21000          # the world's west edge in lot-file tiles (70 x 300)


def room_rects(squares: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Rectangles (x, y, w, h) covering exactly `squares`, by the scan described above."""
    free = set(squares)
    out = []
    for y, x in sorted((y, x) for x, y in squares):
        if (x, y) not in free:
            continue
        w = 1
        while (x + w, y) in free:
            w += 1
        h = 1
        while True:
            row = y + h
            if not all((x + i, row) in free for i in range(w)):
                break
            # the run in that row must be exactly this wide: no free square either side
            if (x - 1, row) in free or (x + w, row) in free:
                break
            h += 1
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                free.discard((xx, yy))
        out.append((x, y, w, h))
    return out


def building_rooms(b, tx: int, ty: int, base: int = 0) -> list[dict]:
    """Room entries of a building placed at world tile (tx, ty), in world coordinates:
    {"name", "z", "rects": [(x, y, w, h)]}. `b` is a parsed Building."""
    rooms = []
    for z, floor in enumerate(b.floors):
        by_id: dict[int, set] = {}
        for y, row in enumerate(floor.rooms):
            for x, v in enumerate(row):
                if v > 0:
                    by_id.setdefault(v, set()).add((x, y))
        for rid in sorted(by_id):
            rects = [(tx + x, ty + y, w, h) for x, y, w, h in room_rects(by_id[rid])]
            rooms.append({"name": b.rooms[rid - 1].get("Name", ""), "z": base + z, "rects": rects})
    return rooms


def placed_rooms(lots) -> list[tuple[int, int, list[dict]]]:
    """Room entries for buildings placed in project order, as cell_tables wants them.

    `lots` is [(building, tx, ty, base level)]. WorldEd builds the tables from the composed map:

    - Buildings are taken by 300-tile source cell, row by row, then in project order, and where a
      later building has a room on a square the square leaves the earlier building's room.
    - Buildings that touch (corners count) are one building: a large building KnoxMap cut into parts is a single
      entry. (Touching rooms of one name stay separate rooms; WorldEd joins two such pairs in
      the 113-building map, out of 75, for no reason the data shows.)
    The result has one item per building group, at the north-west corner of its first part.

    Worked one level at a time over arrays of the squares' owners: a dict keyed by every
    square of every floor ran a 230,000-building map out of memory (MemoryError)."""
    import numpy as np

    order = sorted(range(len(lots)), key=lambda i: (lots[i][2] // 300, lots[i][1] // 300, i))
    rank = {lot: n for n, lot in enumerate(order)}
    # (lot, floor, height, width) by level, each floor sized by its own room grid
    by_level: dict[int, list[tuple[int, int, int, int]]] = {}
    for i in order:
        b, _tx, _ty, base = lots[i]
        for z, floor in enumerate(b.floors):
            h = len(floor.rooms)
            w = len(floor.rooms[0]) if h else 0
            if h and w:
                by_level.setdefault(base + z, []).append((i, z, h, w))
    lot_parent = list(range(len(lots)))

    def lfind(i):
        while lot_parent[i] != i:
            lot_parent[i] = lot_parent[lot_parent[i]]
            i = lot_parent[i]
        return i

    # (lot, level, room number) -> rectangles of the squares it keeps
    rects_of: dict[tuple[int, int, int], list] = {}
    for level in sorted(by_level):
        here = by_level[level]
        x0 = min(lots[i][1] for i, _z, _h, _w in here)
        y0 = min(lots[i][2] for i, _z, _h, _w in here)
        W = max(lots[i][1] + w for i, _z, _h, w in here) - x0
        H = max(lots[i][2] + h for i, _z, h, _w in here) - y0
        owner = np.full((H, W), -1, np.int32)
        rid = np.zeros((H, W), np.int32)
        # in order, so a later building's room takes the square from an earlier one
        for i, z, h, w in here:
            b, tx, ty, _base = lots[i]
            grid = np.asarray(b.floors[z].rooms, dtype=np.int32).reshape(h, w)
            m = grid > 0
            if not m.any():
                continue
            ys, xs = ty - y0, tx - x0
            owner[ys:ys + h, xs:xs + w][m] = i
            rid[ys:ys + h, xs:xs + w][m] = grid[m]
        # lots with squares that touch on this level, corners included
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            a = owner[max(0, -dy):H - max(0, dy), max(0, -dx):W - max(0, dx)]
            n = owner[max(0, dy):H - max(0, -dy), max(0, dx):W - max(0, -dx)]
            sel = (a >= 0) & (n >= 0) & (a != n)
            if not sel.any():
                continue
            pairs = np.unique(a[sel].astype(np.int64) * len(lots) + n[sel])
            for p in pairs.tolist():
                k, other = divmod(p, len(lots))
                lot_parent[lfind(other)] = lfind(k)
        # each (lot, room number) part's squares, in world tiles
        flat = np.flatnonzero(owner.ravel() >= 0)
        if not flat.size:
            continue
        keys = owner.ravel()[flat].astype(np.int64) << 32 | rid.ravel()[flat]
        del owner, rid
        sort = np.argsort(keys, kind="stable")
        keys, flat = keys[sort], flat[sort]
        starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
        ends = np.r_[starts[1:], keys.size]
        sx, sy = flat % W + x0, flat // W + y0
        del flat, sort
        for s, e, key in zip(starts.tolist(), ends.tolist(), keys[starts].tolist()):
            rects_of[(key >> 32, level, key & 0xFFFFFFFF)] = room_rects(
                set(zip(sx[s:e].tolist(), sy[s:e].tolist())))
        del keys, sx, sy
    # A basement stays a building of its own, as in every map the game ships:
    # joined to the house above, the game took a player beside the house for
    # one inside it and took its roof off (knoxbuild/basements.py).
    # a building group: the lots that touch; its corner is that of its first part
    groups: dict[int, list[int]] = {}
    for i in order:
        groups.setdefault(lfind(i), []).append(i)
    # Each lot's parts in order, so a group reads only its own.
    parts_of: dict[int, list] = {}
    for k in sorted(rects_of, key=lambda k: (rank[k[0]], k[1], k[2])):
        parts_of.setdefault(k[0], []).append(k)
    out = []
    for members in groups.values():
        first = members[0]
        entries = [{"name": lots[k[0]][0].rooms[k[2] - 1].get("Name", ""), "z": k[1],
                    "rects": rects_of.pop(k)}
                   for lot in members for k in parts_of.get(lot, ())]
        out.append((lots[first][1], lots[first][2], entries))
    return out


def cell_tables(cell_x: int, cell_y: int, placed: list[tuple[int, int, list[dict]]],
                origin: tuple[int, int] = (ORIGIN_X, 0)) -> tuple[list[dict], list[list[int]]]:
    """(rooms, buildings) of one cell. `placed` holds, for each building in project order,
    (x, y, room entries): the world tile of its north-west corner and its rooms in world
    coordinates (from building_rooms). A building is listed in the cell that holds its
    north-west corner, with every rectangle whole, even where it runs past the cell's edge."""
    x0, y0 = cell_x * CELL - origin[0], cell_y * CELL - origin[1]
    rooms: list[dict] = []
    buildings: list[list[int]] = []
    # By source cell, row by row (the project file lists them column by column), then in the
    # order the project gives within a source cell.
    for tx, ty, entries in sorted(placed, key=lambda p: (p[1] // 300, p[0] // 300)):
        if not entries:
            continue
        # The cell of the north-west corner of its rooms: the first lot's corner, unless a later
        # part of a large building reaches further north or west (a rect must not be negative).
        # ponytail: matches WorldEd on 16 of 25 cells of a 1500 m map; the rule WorldEd uses for
        # such buildings is not found.
        tx = min(tx, min(r[0] for e in entries for r in e["rects"]))
        ty = min(ty, min(r[1] for e in entries for r in e["rects"]))
        if not (x0 <= tx < x0 + CELL and y0 <= ty < y0 + CELL):
            continue
        buildings.append(list(range(len(rooms), len(rooms) + len(entries))))
        for e in entries:
            rooms.append({"name": e["name"], "z": e["z"],
                          "rects": [(x - x0, y - y0, w, h) for x, y, w, h in e["rects"]]})
    return rooms, buildings
