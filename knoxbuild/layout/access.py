"""Shared, furnished routes through the plan of an apartment building."""
from __future__ import annotations

from collections import deque

from .core import STAIR_RUN
from .openings import ApartmentAccessError, _room_at


def door_sides(edge):
    x, y, direction = edge
    return ((x - 1, y) if direction == "W" else (x, y - 1)), (x, y)


def stair_tiles(flight):
    x, y, direction = flight
    dx, dy = (0, 1) if direction == "N" else (1, 0)
    return [(x + dx * i, y + dy * i) for i in range(-1, STAIR_RUN)]


def shared_paths(plan, from_below=(), to_above=(), *, ground=False):
    """Return the clear routes from each entrance/landing to its public doors.

    Tile coordinates, not just the room graph, matter around a stair opening.
    A sealed lift shaft is an endpoint on the corridor side of its doors.
    """
    public = {i for i, r in enumerate(plan.rooms, 1) if r.is_core}
    if not public:
        return set()
    cells = {}
    for y, row in enumerate(plan.grid):
        for x, value in enumerate(row):
            if value in public:
                cells[x, y] = value
    if not cells:
        return set()
    starts, targets = set(), set(plan.clear_access)
    for door in plan.doors:
        a, b = door_sides(door)
        for p, other in ((a, b), (b, a)):
            if p not in cells:
                continue
            i = _room_at(plan, *other)
            if not i and ground:
                starts.add(p)
            elif i and plan.rooms[i - 1].unit:
                targets.add(p)
    outside_entries = set(starts)
    for flight in from_below:
        top, landing = stair_tiles(flight)[:2]
        starts.add(landing)
        targets.add(top)
    stair_feet = {stair_tiles(flight)[-1] for flight in to_above}
    targets.update(stair_feet)
    for rect, (x, y, direction) in plan.shafts:
        length = rect[3] - rect[1] + 1 if direction == "W" else rect[2] - rect[0] + 1
        for i in range(length):
            a, b = door_sides((x, y + i, "W") if direction == "W" else (x + i, y, "N"))
            approach = {a, b} & cells.keys()
            if not approach:
                raise ApartmentAccessError(f"Lift has no shared approach at {(x, y)}")
            targets.update(approach)

    unavailable = set(plan.holes)
    for flight in (*from_below, *to_above):
        unavailable.update(stair_tiles(flight)[2:-1])
    for p in unavailable:
        cells.pop(p, None)
    openings = set(plan.doors) | plan.open_edge
    boundaries = plan.railing | plan.party
    def reserve(roots, ends):
        parents = dict.fromkeys(roots & cells.keys())
        frontier = deque(sorted(parents))
        while frontier:
            x, y = p = frontier.popleft()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                q = nx, ny
                if q in parents or q not in cells:
                    continue
                edge = (max(x, nx), max(y, ny), "W" if x != nx else "N")
                if edge in boundaries or (cells[p] != cells[q] and edge not in openings):
                    continue
                parents[q] = p
                frontier.append(q)

        missing = (ends | roots) - parents.keys()
        if missing:
            raise ApartmentAccessError(f"Disconnected apartment approach at {min(missing)}")
        route = set(roots)
        for p in sorted(ends):
            while p is not None and p not in route:
                route.add(p)
                p = parents[p]
        return route

    path = reserve(starts, targets)
    # A search from all doors can end every route at the same door. Also keep
    # the way from the stairs to each door clear, including secondary entries.
    if len(outside_entries) > 1 and stair_feet:
        path.update(reserve(stair_feet, outside_entries))
    return path
