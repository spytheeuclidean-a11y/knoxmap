"""A facade-aligned coordinate frame over the game's square tiles."""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from .core import Room

Tile = tuple[int, int]
Axis = tuple[float, float]


@dataclass(frozen=True)
class OrientedHall:
    axis: Axis
    centre: float
    tiles: frozenset[Tile]


def project(tile: Tile, axis: Axis) -> tuple[float, float]:
    x, y = tile
    dx, dy = axis
    return x * dx + y * dy, y * dx - x * dy


def footprint_axis(mask) -> Axis | None:
    """Use the long direction of the part of the footprint actually placed."""
    if mask is None or sum(map(sum, mask)) >= .9 * len(mask) * len(mask[0]):
        return None
    limits = []
    for y, row in enumerate(mask):
        xs = [x for x, kept in enumerate(row) if kept]
        if xs:
            limits.extend(((xs[0], y), (xs[-1], y)))
    from shapely.geometry import MultiPoint

    rect = MultiPoint(limits).minimum_rotated_rectangle
    if not hasattr(rect, "exterior"):
        return None
    a, b, c = list(rect.exterior.coords)[:3]
    dx, dy = max(((b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])),
                 key=lambda side: hypot(*side))
    length = hypot(dx, dy)
    if min(abs(dx), abs(dy)) < .2 * length:
        return None
    sign = -1 if dx < 0 else 1
    return sign * dx / length, sign * dy / length


def apartment_shells(plan, hall: OrientedHall, target_area: int):
    """Slice the available wings across the local hall, including private ends."""
    wings: tuple[dict[int, set[Tile]], dict[int, set[Tile]]] = ({}, {})
    for y, row in enumerate(plan.mask):
        for x, present in enumerate(row):
            if present:
                u, v = project((x, y), hall.axis)
                wings[int(v >= hall.centre)].setdefault(round(u), set()).add((x, y))
    shells = []
    for columns in wings:
        remaining = sum(map(len, columns.values()))
        count = max(1, round(remaining / target_area))
        if not hall.tiles:
            count = min(count, 2)
        target = remaining / count
        shell = set()
        for u in sorted(columns):
            shell.update(columns[u])
            remaining -= len(columns[u])
            if len(shell) >= target and remaining >= target / 2:
                shells.append(shell)
                shell = set()
        if shell:
            shells.append(shell)
    for unit, cells in enumerate(shells, 1):
        xs, ys = zip(*cells)
        plan.rooms.append(Room(min(xs), min(ys), max(xs), max(ys), kind="openplan",
                               unit=unit, fixed=True))
    return shells
