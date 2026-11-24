"""Reserve a rectangular balcony strip and its indoor frontage together."""
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby

from .furnishing import _facade_runs


@dataclass(frozen=True)
class Balcony:
    tiles: frozenset
    frontage: frozenset
    railing: frozenset
    door: tuple


def balcony_strips(plan):
    """Find strips of one dwelling on a straight, exposed section of facade."""
    grid = plan.grid
    owners = {i: r.unit for i, r in enumerate(plan.rooms, 1)}
    proposals = defaultdict(list)
    inward = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}

    def room_at(x, y):
        return grid[y][x] if 0 <= x < plan.width and 0 <= y < plan.height else 0

    def unit_at(edge):
        x, y = edge[3:]
        return owners[grid[y][x]] if edge[:3] not in plan.party else 0

    for side, edges in _facade_runs(grid):
        dx, dy = inward[side]
        for unit, segment in groupby(edges, unit_at):
            if not unit:
                continue
            run = list(segment)
            if len(run) < 3:
                continue
            # Use end bays first, so the balcony reads as a strip along a
            # room and its end can line up with the neighbouring partition.
            for width in range(min(6, len(run)), 2, -1):
                for start in dict.fromkeys((0, len(run) - width)):
                    face = tuple(e[3:] for e in run[start:start + width])
                    for depth in (2, 1):
                        deck = frozenset((x + dx * i, y + dy * i)
                                         for x, y in face for i in range(depth))
                        front = frozenset((x + dx * depth, y + dy * depth) for x, y in face)
                        if any(owners.get(room_at(x, y)) != unit for x, y in deck | front):
                            continue
                        rails = set()
                        for x, y in deck:
                            for ox, oy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                                if not room_at(ox, oy):
                                    rails.add((max(x, ox), max(y, oy), "W" if x != ox else "N"))
                        if rails & plan.party:
                            continue
                        x, y = face[width // 2]
                        door = (x + dx * (depth - int(dx < 0)),
                                y + dy * (depth - int(dy < 0)), "W" if dx else "N")
                        proposals[unit].append(Balcony(deck, front, frozenset(rails), door))
    return proposals
