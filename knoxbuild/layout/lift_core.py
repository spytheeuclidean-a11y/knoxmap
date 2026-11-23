"""Fit a residential stairwell and lift lobby beside a clear corridor."""
from __future__ import annotations

from dataclasses import dataclass

from .core import Room, STAIR_RUN
from .furnishing import _stairs_in_core


def adjacent(p):
    x, y = p
    return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))


def edge(a, b):
    return max(a[0], b[0]), max(a[1], b[1]), "W" if a[0] != b[0] else "N"


def bounds(cells):
    xs, ys = zip(*cells)
    return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class LiftCore:
    stairs: tuple
    flight: tuple
    shaft: tuple
    lobby: frozenset
    balcony: frozenset
    openings: tuple
    doors: tuple
    railing: frozenset

    def place(self, plan, spine, *, ground):
        """Set aside rooms and fixed doorways before apartment doors are chosen."""
        x0, y0, x1, y1 = self.stairs
        stairwell = {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}
        for cells, role in ((stairwell, "stairs"), (self.lobby, "lift_lobby"),
                            (self.balcony, "vestibule" if ground else "balcony")):
            if cells:
                plan.rooms.append(Room(*bounds(cells), is_core=True, fixed=True, access_role=role))
                for x, y in cells:
                    plan.grid[y][x] = len(plan.rooms)
        plan.doors.extend(self.doors)
        plan.open_edge.update(self.openings)
        if not ground:
            plan.railing.update(self.railing)
        plan.clear_access.update(spine | self.lobby | self.balcony)


def candidates(spine, floor, reserved, party, axis, *, compact, balcony=False):
    """Fit a shared lobby or a stair door opening directly onto the spine."""
    if not spine:
        return iter(())
    free = floor - spine - reserved
    length = STAIR_RUN + 2
    cx, cy = (sum(p[i] for p in spine) / len(spine) for i in (0, 1))
    options = []
    # A detached stair door borders the spine. Only the shared lobby can
    # be set back from it, including when it leads to an outdoor passage.
    links = [(False, gap) for gap in range(5 if balcony else 3)]
    if not balcony:
        links.append((True, 0))
    for along in ((1, 0), (0, 1)):
        ax, ay = along
        alignment = abs(ax * axis[0] + ay * axis[1])
        for side in (1, -1):
            nx, ny = side * ay, side * ax
            for reverse in (1, -1):
                dx, dy = reverse * ax, reverse * ay
                lift_x = length + 2 * balcony
                first = length if balcony else length - 2
                for px, py in sorted(spine):
                    near = px + nx, py + ny
                    if near not in free:
                        continue
                    for separate, link in links:
                        def tile(u, v):
                            return (px + (u - first) * dx + (v + 1 + link) * nx,
                                    py + (u - first) * dy + (v + 1 + link) * ny)

                        stair_front = 0 if separate else 2
                        stairs = {tile(u, v) for u in range(length)
                                  for v in (stair_front, stair_front + 1)}
                        shaft = {tile(u, v) for u in (lift_x, lift_x + 1) for v in (2, 3)}
                        lobby_start = lift_x if separate else first
                        lobby = {tile(u, v) for u in range(lobby_start, lift_x + 2)
                                 for v in (0, 1)}
                        deck = {tile(u, v) for u in range(length, lift_x) for v in (2, 3)}
                        wing = stairs | shaft | lobby | deck
                        if not wing <= free:
                            continue
                        # Outside our section can mean the next apartment
                        # section rather than an exterior wall.
                        if any(edge(p, q) in party for p in shaft for q in adjacent(p)):
                            continue
                        outside = {edge(p, q) for p in deck for q in adjacent(p) if q not in floor}
                        if balcony and (len(outside) < 2 or outside & party):
                            continue
                        passage = {tile(u, v) for u in (first, first + 1)
                                   if tile(u, -link - 1) in spine for v in range(-link, 0)}
                        if not passage <= free:
                            continue
                        lobby |= passage
                        openings = tuple(sorted({edge(p, q) for p in lobby for q in adjacent(p)
                                                 if q in spine} - party))
                        if not openings:
                            continue
                        flight = _stairs_in_core(bounds(stairs), hug_wall=True, far_wall=side == 1)
                        stair_row = 2 if tile(0, 2)[ax] != flight[ax] else 3
                        if balcony:
                            doors = (edge(tile(length, 1), tile(length, 2)),
                                     edge(tile(length, stair_row), tile(length - 1, stair_row)))
                        elif separate:
                            door_columns = [u for u in range(length)
                                            if tile(u, -1) in spine
                                            and edge(tile(u, -1), tile(u, 0)) not in party]
                            if not door_columns:
                                continue
                            u = min(door_columns, key=lambda u: abs(2 * u - length + 1))
                            doors = (edge(tile(u, -1), tile(u, 0)),)
                        else:
                            # The stair's walkable lane should face the lobby.
                            doors = (edge(tile(first, 1), tile(first, 2)),)
                        lift_door = min(edge(tile(u, 1), tile(u, 2))
                                        for u in (lift_x, lift_x + 1))
                        if party.intersection((*doors, lift_door)):
                            continue
                        slivers = sum(tile(u, 4) in floor and tile(u, 6) not in floor
                                      for u in range(lift_x + 2) if tile(u, 3) in wing)
                        exposed = sum(q in floor and q not in wing and q not in spine
                                      for p in shaft for q in adjacent(p))
                        layout_cost = 8 * (separate == compact) if not balcony else 0
                        score = (abs(px - cx) + abs(py - cy) + 6 * (1 - alignment)
                                 + layout_cost + exposed + link + 2 * (len(openings) == 1)
                                 + slivers)
                        options.append((score, LiftCore(bounds(stairs), flight,
                                                       (bounds(shaft), lift_door),
                                                       frozenset(lobby), frozenset(deck),
                                                       openings, doors, frozenset(outside))))
    return (core for _, core in sorted(options, key=lambda item: item[0]))
