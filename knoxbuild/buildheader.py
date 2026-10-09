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
    The result has one item per building group, at the north-west corner of its first part."""
    order = sorted(range(len(lots)), key=lambda i: (lots[i][2] // 300, lots[i][1] // 300, i))
    owner: dict[tuple[int, int, int], tuple[int, int]] = {}
    for i in order:
        b, tx, ty, base = lots[i]
        for z, floor in enumerate(b.floors):
            for y, row in enumerate(floor.rooms):
                for x, v in enumerate(row):
                    if v > 0:
                        owner[(tx + x, ty + y, base + z)] = (i, v)
    squares: dict[tuple[int, int, int], set] = {}
    for (x, y, z), (i, rid) in owner.items():
        squares.setdefault((i, z, rid), set()).add((x, y))
    # parts: (lot, level, room number) with squares left; group parts that touch
    parts = sorted(squares, key=lambda k: (order.index(k[0]), k[1], k[2]))
    parent = {k: k for k in parts}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    at: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for k in parts:
        for (x, y) in squares[k]:
            at[(x, y, k[1])] = k
    lot_parent = list(range(len(lots)))

    def lfind(i):
        while lot_parent[i] != i:
            lot_parent[i] = lot_parent[lot_parent[i]]
            i = lot_parent[i]
        return i

    for k in parts:
        for (x, y) in squares[k]:
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):     # touching includes corners
                for dz in (0,):
                    n = at.get((x + dx, y + dy, k[1] + dz))
                    if n and n[0] != k[0]:
                        lot_parent[lfind(n[0])] = lfind(k[0])
    # a building group: the lots that touch; its corner is that of its first part
    groups: dict[int, list[int]] = {}
    for i in order:
        groups.setdefault(lfind(i), []).append(i)
    out = []
    for members in groups.values():
        first = members[0]
        entries = []
        merged: dict[tuple, dict] = {}
        for k in parts:
            if k[0] not in members:
                continue
            root = find(k)
            if root not in merged:
                merged[root] = {"name": lots[k[0]][0].rooms[k[2] - 1].get("Name", ""), "z": k[1], "squares": set()}
                entries.append(merged[root])
            merged[root]["squares"] |= squares[k]
        for e in entries:
            e["rects"] = room_rects(e.pop("squares"))
        out.append((lots[first][1], lots[first][2], entries))
    return out


def cell_tables(cell_x: int, cell_y: int, placed: list[tuple[int, int, list[dict]]]) -> tuple[list[dict], list[list[int]]]:
    """(rooms, buildings) of one cell. `placed` holds, for each building in project order,
    (x, y, room entries): the world tile of its north-west corner and its rooms in world
    coordinates (from building_rooms). A building is listed in the cell that holds its
    north-west corner, with every rectangle whole, even where it runs past the cell's edge."""
    x0, y0 = cell_x * CELL - ORIGIN_X, cell_y * CELL
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
