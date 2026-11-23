"""Constraints from mapped door points on the placed building outline."""
from __future__ import annotations

from dataclasses import dataclass

Edge = tuple[int, int, str]
SNAP_DISTANCE = 2.0


def closed_entrance(tags: dict) -> bool:
    return (tags.get("access") == "no" or tags.get("entrance") == "no"
            or tags.get("locked") == "yes" or tags.get("foot") == "no")


def ground_entrance(tags: dict) -> bool:
    level = str(tags.get("level") or tags.get("min_level") or "0")
    return (tags.get("location") != "underground"
            and bool({"0", "ground"} & {s.strip().lower() for s in level.split(";")}))


def residential_entrance(tags: dict) -> bool:
    return tags.get("entrance") == "staircase" or (
        tags.get("entrance") == "main" and bool(tags.get("addr:flats")))


def _distance(edge: Edge, x: float, y: float) -> float:
    ex, ey, direction = edge
    dx, dy = abs(x - ex), abs(y - ey)
    if direction == "N":
        dx = max(ex - x, x - ex - 1, 0)
    else:
        dy = max(ey - y, y - ey - 1, 0)
    return dx * dx + dy * dy


@dataclass(frozen=True)
class FacadeDoor:
    side: str
    edges: tuple[Edge, ...]     # nearest first, all on the same stretch of wall


def bind_facade(runs, x: float, y: float) -> FacadeDoor | None:
    """Bind before filtering obstacles, so a blocked wall cannot change the facade."""
    def rank(edge):
        ex, ey, direction = edge
        return (_distance(edge, x, y), (ex - x) ** 2 + (ey - y) ** 2, direction, ex, ey)

    choices = []
    for side, run in runs:
        edges = [tuple(e[:3]) for e in run]
        nearby = tuple(sorted((e for e in edges if _distance(e, x, y) <= SNAP_DISTANCE ** 2),
                              key=rank))
        if nearby:
            choices.append((rank(nearby[0])[:2], -len(edges), side, nearby))
    if not choices:
        return None
    _, _, side, edges = min(choices)
    return FacadeDoor(side, edges)


def closed_edges(runs, entrances) -> set[Edge]:
    return {bound.edges[0] for x, y, tags in entrances
            if ground_entrance(tags) and closed_entrance(tags)
            and (bound := entrance_facade(runs, x, y, tags)) is not None}


def entrance_facade(runs, x: float, y: float, tags: dict) -> FacadeDoor | None:
    # Sections can supply a binding made against the whole building, before
    # the internal section walls became edges of the section's own mask.
    bound = tags.get("_knox_entrance_facade")
    return bound if isinstance(bound, FacadeDoor) else bind_facade(runs, x, y)
