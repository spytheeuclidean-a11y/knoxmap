"""The checks that catch a floor plan that cannot work in game.

Run over a building once it is laid out: by Build, on every building it makes,
and by tools/audit_layouts.py over hundreds of made-up ones. What they look for
is what a player notices first - a room with no way in, a door between two
people's flats, a flat with no front door or several, a flight of stairs with a
wall across it, a building with no way in from outside, a window or a door with
furniture across it, and roofs hanging over open ground.

Counted, not raised. Build reports the totals beside the map, so a town that
came out wrong is known before it is compiled; the tool fails a change when the
rate of any of them rises.
"""
from __future__ import annotations

from collections import Counter

from .layout import (ELEVATOR_FROM_LEVELS, ELEVATOR_MIN_SIDE, STAIR_RUN,
                     roof_rects)

def door_pair(storey, door):
    x, y, d = door
    if d == "W" and 0 < x < storey.width:
        return storey.grid[y][x - 1], storey.grid[y][x]
    if d == "N" and 0 < y < storey.height:
        return storey.grid[y - 1][x], storey.grid[y][x]
    return None


def audit(building, kind):
    problems = Counter()
    for lvl, s in enumerate(building.storeys):
        n = len(s.rooms)
        adj = {i: set() for i in range(1, n + 1)}
        fronts = Counter()
        # A gap in a wall is a way through as much as a door is: a mall unit
        # stands open to the concourse, which is how Knox County's does it -
        # 584 boundary squares between its units and the hall and not one door
        # among them.
        for x, y, d in getattr(s, "open_edge", ()):
            pair = door_pair(s, (x, y, d))
            if pair and all(pair) and pair[0] != pair[1]:
                adj[pair[0]].add(pair[1])
                adj[pair[1]].add(pair[0])
        for door in s.doors:
            pair = door_pair(s, door)
            if not pair or not all(pair) or pair[0] == pair[1]:
                continue
            a, b = pair
            adj[a].add(b)
            adj[b].add(a)
            ua, ub = s.rooms[a - 1].unit, s.rooms[b - 1].unit
            if ua and ub and ua != ub:
                problems["door between two flats"] += 1
            elif ua != ub:
                fronts[ua or ub] += 1
        # A tile carrying both a west and a north wall is drawn as one corner
        # piece, and a door on one comes out as neither door nor wall - which
        # is what a player reads as a door that will not open.
        from .layout import _facade_runs, _room_edges
        edges = {(x, y, d) for _side, wall in _facade_runs(s.grid)
                 for x, y, d, _ix, _iy in wall} | _room_edges(s.grid)
        on_corner = {(x, y) for x, y, d in edges
                     if (x, y, "N" if d == "W" else "W") in edges}
        # Counted, not failed one at a time: a door only stays on a corner
        # when every clean wall it could move to would shut a room off, and a
        # shut room is worse. The rate is what has to stay down.
        problems["stat:doors"] += len(s.doors)
        problems["stat:on a corner"] += sum(1 for door in s.doors
                                            if (door[0], door[1]) in on_corner)
        # What blocks the floor, then the checks that read it.
        from .layout import _blocks, _tiles_under, _under_a_window
        solid = {}
        for role, fx, fy, o in s.furniture:
            if _blocks(role):
                for t in _tiles_under(role, fx, fy, o):
                    solid[t] = role

        def room_at(x, y):
            return s.grid[y][x] if 0 <= x < s.width and 0 <= y < s.height else 0

        # A window with a wardrobe or a bookcase across it cannot be opened,
        # climbed through or seen out of (a bed or a bath may stand there).
        for x, y, d in s.windows:
            for t in (((x - 1, y) if d == "W" else (x, y - 1)), (x, y)):
                role = solid.get(t)
                if role and room_at(*t) and not _under_a_window(role):
                    problems["window blocked by furniture"] += 1
        # A door with nowhere to step: both free neighbours of the tile in
        # front of it, inside its own room, are taken.
        for x, y, d in s.doors:
            front = (x - 1, y) if d == "W" else (x, y - 1)
            for tile in (front, (x, y)):
                r = room_at(*tile)
                if not r:
                    continue
                problems["stat:door fronts"] += 1
                onward = [(tile[0] + dx, tile[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                          if (tile[0] + dx, tile[1] + dy) not in (front, (x, y))]
                if not any(room_at(*n) == r and n not in solid for n in onward):
                    problems["stat:door boxed in"] += 1
        # A room you can only get to through a bathroom.
        links: dict = {}
        for x, y, d in s.doors:
            a, b = ((room_at(x - 1, y) if d == "W" else room_at(x, y - 1)), room_at(x, y))
            if a and b and a != b:
                links.setdefault(a, set()).add(b)
                links.setdefault(b, set()).add(a)
        baths = {i for i, rm in enumerate(s.rooms, 1) if rm.kind == "bathroom"}
        for i, rm in enumerate(s.rooms, 1):
            if i not in baths and not rm.is_shaft:
                problems["stat:rooms"] += 1
                if links.get(i) and links[i] <= baths:
                    problems["stat:room through a bathroom"] += 1
        lit = {s.grid[fy][fx] for role, fx, fy, _o in s.furniture if role == "switch"}
        shafts = {i for i, r in enumerate(s.rooms, 1) if r.is_shaft}
        if any(i not in lit and i not in shafts for i in range(1, n + 1)):
            problems["room with no light switch"] += 1
        # A lift shaft is a sealed box: a doorway into it is a hole to fall down.
        for door in s.doors:
            pair = door_pair(s, door)
            if pair and any(p in shafts for p in pair):
                problems["doorway into the lift shaft"] += 1
        if n:
            start = next((i for i in range(1, n + 1) if i not in shafts), 1)
            seen, stack = {start} | shafts, [start]
            while stack:
                cur = stack.pop()
                for nx in adj[cur] - seen:
                    seen.add(nx)
                    stack.append(nx)
            if len(seen) != n:
                problems["room with no way in"] += 1
        if kind == "apartment" and any(r.unit == 0 for r in s.rooms):
            for unit in {r.unit for r in s.rooms if r.unit}:
                if fronts[unit] == 0:
                    problems["flat with no front door"] += 1
                elif fronts[unit] > 1:
                    problems["flat with several front doors"] += 1
        if lvl == 0:
            outside = [d for d in s.doors if door_pair(s, d) is None or
                       0 in (door_pair(s, d) or (0,))]
            if not outside:
                problems["no way in from outside"] += 1
        if lvl > 0 and any(0 in (door_pair(s, d) or (0,)) for d in s.doors):
            problems["outside door on an upper floor"] += 1
        # Roof: covers exactly the top storey's footprint, no more.
        if lvl == len(building.storeys) - 1:
            covered = set()
            for x0, y0, rw, rh, _caps in roof_rects(s.grid):
                for y in range(y0, y0 + rh):
                    for x in range(x0, x0 + rw):
                        if (x, y) in covered:
                            problems["roofs overlapping"] += 1
                        covered.add((x, y))
            inside = {(x, y) for y in range(s.height) for x in range(s.width)
                      if s.grid[y][x]}
            if covered - inside:
                problems["roof over open ground"] += 1
            if inside - covered:
                problems["building with a hole in its roof"] += 1
    # Lifts: the mod finds a shaft by its doors at the same square on every
    # floor, so every storey needs the same shaft and a door hung on it.
    shafts = [[r for r, _d in s.shafts] for s in building.storeys]
    if any(shafts):
        if len({tuple(x) for x in shafts}) != 1:
            problems["lift shaft moves between floors"] += 1
        for s in building.storeys:
            doors = [f for f in s.furniture if f[0] == "elevator_door"]
            if len(doors) != len(s.shafts):
                problems["floor without lift doors"] += 1
                continue
            for _r, lx, ly, ld in doors:
                for i in range(2):
                    ax, ay = (lx, ly + i) if ld == "W" else (lx + i, ly)
                    bx, by = (ax - 1, ay) if ld == "W" else (ax, ay - 1)
                    sides = {s.grid[ay][ax] if 0 <= ax < s.width and 0 <= ay < s.height else 0,
                             s.grid[by][bx] if 0 <= bx < s.width and 0 <= by < s.height else 0}
                    kinds = {s.rooms[v - 1].is_shaft for v in sides if v}
                    if 0 in sides or kinds != {True, False}:
                        problems["lift doors not between shaft and landing"] += 1
                        break
    elif len(building.storeys) >= ELEVATOR_FROM_LEVELS and \
            min(building.width, building.height) >= ELEVATOR_MIN_SIDE:
        problems["tall building without a lift"] += 1
    for lvl, (x, y, d) in enumerate(building.stairs):
        dx, dy = (0, 1) if d == "N" else (1, 0)
        run = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
        for s in (building.storeys[lvl], building.storeys[lvl + 1]):
            rooms = {s.grid[ry][rx] if 0 <= rx < s.width and 0 <= ry < s.height
                     else 0 for rx, ry in run}
            if len(rooms) != 1 or 0 in rooms:
                problems["stairs crossing a wall"] += 1
                break
        blocked = {(x + dx * i, y + dy * i) for i in range(STAIR_RUN)}
        # The steps between the two landings cannot be walked across, so a
        # door that opens onto one cannot be used.
        steps = set(run[1:-1])
        for s in (building.storeys[lvl], building.storeys[lvl + 1]):
            for door in s.doors:
                pair = door_pair(s, door)
                spots = ((door[0] - 1, door[1]) if door[2] == "W" else (door[0], door[1] - 1),
                         (door[0], door[1]))
                if pair and any(sp in steps for sp in spots):
                    problems["door opening onto the stairs"] += 1
        for s in (building.storeys[lvl], building.storeys[lvl + 1]):
            for role, fx, fy, _o in s.furniture:
                if (fx, fy) in blocked:
                    problems["furniture on the stairs"] += 1
    return problems


def basement_unreached(basement) -> tuple[int, int]:
    """(rooms a player coming down the stairs cannot walk to, rooms), over
    every level of a basement (knoxbuild/basements.py)."""
    unreached = total = 0
    for s in basement.building.storeys:
        n = len(s.rooms)
        total += n
        adj = {i: set() for i in range(1, n + 1)}
        for edge in list(s.doors) + list(getattr(s, "open_edge", ())):
            pair = door_pair(s, edge)
            if pair and all(pair) and pair[0] != pair[1]:
                adj[pair[0]].add(pair[1])
                adj[pair[1]].add(pair[0])
        sx, sy, _d = basement.building.stairs[0]
        start = s.grid[sy][sx] or next((i for i in range(1, n + 1)), 0)
        seen, stack = {start}, [start]
        while stack:
            for nx in adj.get(stack.pop(), set()) - seen:
                seen.add(nx)
                stack.append(nx)
        unreached += n - len(seen - {0})
    return unreached, total
