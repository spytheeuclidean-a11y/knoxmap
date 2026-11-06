"""Which way the street grid runs, so a town can be turned square to the map."""
from __future__ import annotations

import math
from typing import Iterable

from ..osm import OSMFeature, classify
from .geometry import _is_polygon
from .projection import Projector


# Roads that count towards a town's street grid. Paths wander, and a motorway
# slicing through at its own angle should not turn the town around it.
GRID_ROADS = {"road_minor", "road_medium", "road_service", "pedestrian"}
# How strongly the streets must agree on a direction before the map is turned
# to it: 1 is a perfect grid, 0 no preference. This is measured against *all*
# road in the box, so a town with a second phase, or rural lanes round it,
# scores low even when its winning district is a perfectly good grid: measured
# maps whose roads were left staircased scored 0.135 (a clear -38.9 degree
# grid), 0.223 and 0.234, while a single-phase town scored 0.281. The old 0.25
# cut-off turned none of the first three, so every street stayed at its
# real-world angle. The district clustering already rejects a town with no
# grid; this only has to reject a stray lane.
ALIGN_MIN_STRENGTH = 0.12
# Per-district street grid (dominant_road_angle). The map is one tile grid and
# is turned by one angle, but the angle is chosen *per neighbourhood* now: the
# bbox is cut into cells of this many metres, each cell measures its own local
# grid, and the cells vote. Averaging a town that grew in two or three phases
# used to land the rotation halfway between them - a compromise angle that
# straightens none of the districts - and a long avenue at its own angle used
# to sway the whole town because it carried more length than it deserved.
# 400 m is a few blocks: small enough that two grids a street apart are told
# apart, big enough that a local grid can be measured inside one cell.
DISTRICT_CELL_M = 400.0
# A cell with less road than this in it has nothing to vote with - a park
# edge, a stub - and abstains rather than letting one corner decide the turn.
DISTRICT_MIN_ROAD_M = 60.0
# Two local grids whose angles are this close (degrees, ignoring the
# 90-degree period of a grid) are the same district and vote together.
DISTRICT_CLUSTER_DEG = 12.0


def _grid_delta(a: float, b: float) -> float:
    """How far two grid angles are apart in degrees, ignoring the 90-degree
    period: 44 degrees and -44 degrees are the same grid, two degrees off."""
    d = abs(a - b) % 90.0
    return min(d, 90.0 - d)


def dominant_road_angle(features: Iterable[OSMFeature], south: float, west: float,
                        north: float, east: float) -> tuple[float, float]:
    """The main direction of a town's streets, and how strongly they share it.

    Tiles are square, so a street at 20 degrees becomes a staircase with a step
    every few tiles - kerbs zigzagging along it and blends failing at every
    corner. Most towns have a grid, even a loose one; turning the whole map so
    that grid runs along the tiles straightens every street on it. Buildings,
    fences and the paper map are projected the same way, so nothing is
    misaligned - only north is no longer straight up.

    The angle is measured per district, not once over the whole town. Each
    DISTRICT_CELL_M cell of the bbox measures its own local grid (directions
    averaged with a 90-degree period, segments weighed by length, as before),
    and cells whose local grid is within DISTRICT_CLUSTER_DEG of one another
    vote together as one district. The district holding the most street wins,
    and the rotation is its angle.

    This matters where a town grew in phases: an old core on one grid and an
    extension on another used to average into an angle that belonged to
    neither, so both districts stayed staircases. Now the district with the
    most street runs straight. The rotation is still one angle for the whole
    map - the game's tile grid is global - so streets on the losing grid keep
    their offset; "Knox County roads" is the setting that bends those.

    Returns (angle, strength): the angle in degrees in (-45, 45], counter-
    clockwise from east, and the strength in [0, 1] - how much of the town's
    grid road the winning district's straightened direction accounts for. A
    town with no district big enough to vote falls back to the plain
    town-wide mean, which is what it always did.
    """
    proj = Projector.build(south, west, north, east, 1.0)
    # (sin sum, cos sum, length) per district cell, plus the town-wide totals.
    cells: dict[tuple[int, int], list[float]] = {}
    sin_sum = cos_sum = total = 0.0
    for feat in features:
        if feat.kind != "way" or classify(feat.tags, _is_polygon(feat)) not in GRID_ROADS:
            continue
        pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, ay - by      # tile y grows south; flip to north-up
            length = math.hypot(dx, dy)
            if length < 1:
                continue
            # Only the street that is on the map has a say. The features include
            # what was fetched beyond it (a turned map downloads a margin all the
            # way round, and a long way is whole however far it runs), and a
            # bigger grid in that margin used to decide how the map was turned.
            mid_x, mid_y = (ax + bx) / 2, (ay + by) / 2
            if not (0 <= mid_x < proj.width and 0 <= mid_y < proj.height):
                continue
            a = 4 * math.atan2(dy, dx)
            s, c = length * math.sin(a), length * math.cos(a)
            sin_sum += s
            cos_sum += c
            total += length
            key = (math.floor(mid_x / DISTRICT_CELL_M),
                   math.floor(mid_y / DISTRICT_CELL_M))
            slot = cells.get(key)
            if slot is None:
                cells[key] = [s, c, length]
            else:
                slot[0] += s
                slot[1] += c
                slot[2] += length
    if total == 0:
        return 0.0, 0.0

    # Every cell with enough road in it is one district's vote: its local
    # angle, weighted by how much street stands behind it and how well those
    # streets agree (a cell of crossed lanes has little to say).
    votes: list[tuple[float, float, float, float]] = []   # angle, weight, sin, cos
    for s, c, length in cells.values():
        if length < DISTRICT_MIN_ROAD_M:
            continue
        agree = math.hypot(s, c) / length
        weight = length * agree
        if weight <= 0:
            continue
        votes.append((math.degrees(math.atan2(s, c) / 4), weight, s, c))
    if not votes:
        # Only stubs and scattered lanes: no district to ask, so the town as a
        # whole answers, exactly as it did before districts were measured.
        return (math.degrees(math.atan2(sin_sum, cos_sum) / 4),
                math.hypot(sin_sum, cos_sum) / total)

    # Cluster the votes greedily from the strongest district outwards. Each
    # cell joins the strongest unassigned seed it is within DISTRICT_CLUSTER_DEG
    # of, so one grid can gather its own phase and the next seed starts a new
    # one; the cluster with the most street wins.
    votes.sort(key=lambda v: (-v[1], v[0]))
    assigned = [False] * len(votes)
    best: tuple[float, float, float] | None = None     # magnitude, sin, cos
    for i, (seed_angle, _weight, _s, _c) in enumerate(votes):
        if assigned[i]:
            continue
        assigned[i] = True
        members = [i]
        for j in range(i + 1, len(votes)):
            if not assigned[j] and _grid_delta(seed_angle, votes[j][0]) <= DISTRICT_CLUSTER_DEG:
                assigned[j] = True
                members.append(j)
        m_sin = sum(votes[m][2] for m in members)
        m_cos = sum(votes[m][3] for m in members)
        magnitude = math.hypot(m_sin, m_cos)
        if best is None or magnitude > best[0]:
            best = (magnitude, m_sin, m_cos)
    _magnitude, m_sin, m_cos = best
    angle = math.degrees(math.atan2(m_sin, m_cos) / 4)
    # How much of the town's grid road the winning district accounts for: a
    # second phase on the far side of the map lowers it, as disagreement did
    # before, but no longer drags the angle off the grid it belongs to.
    return angle, _magnitude / total
