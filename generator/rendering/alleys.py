"""Back alleys between back-to-back terraces, for British maps.

A Victorian terrace street is two rows of houses with their backs to each
other: a yard behind each house and, down the middle of the block, a narrow
lane the bins and the coal came along. OpenStreetMap maps many of them as
highway=service service=alley, and those are drawn already. This finds the
ones it doesn't: rows whose rear walls face each other across a strip with
no way in it, and lays a lane down the middle of that strip, joined to the
streets at its ends. It adds ordinary service=alley ways, so everything
downstream draws them like mapped ones.

Only called for maps in Great Britain (docs/REGIONAL_PROFILES.md, GB step 6).
Everything here is in metres.
"""
from __future__ import annotations

import math

from ..osm import OSMFeature, classify
from .geometry import _feature_coords_px, _is_polygon

HOUSE_TAGS = {"house", "terrace", "terraced", "residential", "semidetached_house",
              "detached", "yes"}
HOUSE_M2 = (25.0, 250.0)          # a house's footprint, not a shed or a block
FRONT_MAX_M = 40.0                # a house this near a street fronts it
FACING = -0.85                    # back directions this opposite face each other
LATERAL_MAX_M = 6.0               # how far along the row a facing house may sit
REAR_GAP_M = (3.0, 30.0)          # rear wall to rear wall: two yards and a lane
JOIN_M = 12.0                     # midpoints this close belong to one lane
# A lane serves at least this many pairs of terraced houses (houses joined to
# a neighbour) and runs at least MIN_LANE_M. Without that, Cambourne's
# detached and semi-detached estate grew 12-25 m stubs in its back gardens.
MIN_PAIRS = 4
MIN_LANE_M = 30.0
TOUCH_M = 0.5                     # a house this near another is joined to it
END_PAD_M = 3.0                   # past the last pair's midpoint
REACH_M = 40.0                    # how far an end may run on to a street
# Kept off buildings, each side. Anfield's alleys narrow to 2.3 m between the
# end houses' outlines, which take in the rear extensions; 1.5 m closed them.
CLEAR_M = 0.9
MIN_PIECE_M = 12.0                # shorter than this is not a lane
MAPPED_NEAR_M = 3.0               # a mapped way this near is the lane already
MAPPED_SHARE = 0.5                # ...along this much of it
FIRST_ID = -2_100_000_000         # below the infill and the sheds
WIDTH_M = "2.5"

CAR_ROADS = {"road_major", "road_medium", "road_minor", "road_service", "pedestrian"}


def back_alleys(features, proj) -> list[OSMFeature]:
    """service=alley ways for the back-to-back rows that have none mapped."""
    import numpy as np
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points, unary_union
    from shapely.strtree import STRtree

    k = proj.meters_per_tile
    houses, buildings, streets, ways = [], [], [], []
    for f in features:
        if f.kind != "way" or not f.geometry:
            continue
        rings = _feature_coords_px(f, proj)
        pts = [(x * k, y * k) for x, y in rings[0]] if rings else []
        if len(pts) < 2:
            continue
        if f.tags.get("building") and _is_polygon(f) and len(pts) >= 4:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            buildings.append(poly)
            if ((f.tags.get("building") or "").lower() in HOUSE_TAGS
                    and HOUSE_M2[0] <= poly.area <= HOUSE_M2[1]):
                houses.append(poly)
        elif f.tags.get("highway") and not _is_polygon(f):
            line = LineString(pts)
            ways.append(line)
            if classify(f.tags, False) in CAR_ROADS:
                streets.append(line)
    if len(houses) < 2 * MIN_PAIRS or not streets:
        return []

    street_tree = STRtree(streets)
    street_union = unary_union(streets)
    house_tree = STRtree(houses)

    # Each terraced house's way back: away from the street it fronts.
    backs = []
    for n, poly in enumerate(houses):
        if not any(m != n for m in house_tree.query(poly.buffer(TOUCH_M),
                                                    predicate="intersects")):
            backs.append(None)          # detached: no terrace, no back alley
            continue
        c = poly.centroid
        at = nearest_points(streets[street_tree.nearest(c)], c)[0]
        dx, dy = c.x - at.x, c.y - at.y
        dist = math.hypot(dx, dy)
        if dist == 0 or dist > FRONT_MAX_M:
            backs.append(None)
            continue
        bx, by = dx / dist, dy / dist
        rear = max((x - c.x) * bx + (y - c.y) * by for x, y in poly.exterior.coords)
        backs.append((c.x, c.y, bx, by, rear))

    # Facing pairs give a point in the middle of the strip between them.
    centres = np.array([(b[0], b[1]) if b else (np.nan, np.nan) for b in backs])
    mids = []
    for i, a in enumerate(backs):
        if a is None:
            continue
        ax, ay, abx, aby, arear = a
        near = np.where(np.hypot(centres[:, 0] - ax, centres[:, 1] - ay)
                        <= 2 * (REAR_GAP_M[1] + 15.0))[0]
        for j in near:
            b = backs[j]
            if j <= i or b is None:
                continue
            bx_, by_, bbx, bby, brear = b
            if abx * bbx + aby * bby > FACING:
                continue
            dx, dy = bx_ - ax, by_ - ay
            along = dx * abx + dy * aby
            lateral = abs(-dx * aby + dy * abx)
            gap = along - arear - brear
            if lateral > LATERAL_MAX_M or not REAR_GAP_M[0] <= gap <= REAR_GAP_M[1]:
                continue
            ra = (ax + abx * arear, ay + aby * arear)
            rb = (bx_ + bbx * brear, by_ + bby * brear)
            mids.append(((ra[0] + rb[0]) / 2, (ra[1] + rb[1]) / 2, -aby, abx))

    # Midpoints in a line along one strip are one lane.
    parent = list(range(len(mids)))

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for i, (x1, y1, t1x, t1y) in enumerate(mids):
        for j in range(i + 1, len(mids)):
            x2, y2, t2x, t2y = mids[j]
            if math.hypot(x2 - x1, y2 - y1) > JOIN_M or abs(t1x * t2x + t1y * t2y) < 0.95:
                continue
            if abs(-(x2 - x1) * t1y + (y2 - y1) * t1x) > CLEAR_M:
                continue
            parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(mids)):
        groups.setdefault(find(i), []).append(mids[i])

    obstacles = unary_union(buildings).buffer(CLEAR_M) if buildings else None
    way_tree = STRtree(ways) if ways else None
    out: list[OSMFeature] = []
    for group in groups.values():
        if len(group) < MIN_PAIRS:
            continue
        tx, ty = group[0][2], group[0][3]
        sx = sum(m[2] if m[2] * tx + m[3] * ty >= 0 else -m[2] for m in group)
        sy = sum(m[3] if m[2] * tx + m[3] * ty >= 0 else -m[3] for m in group)
        n = math.hypot(sx, sy)
        tx, ty = sx / n, sy / n
        cx = sum(m[0] for m in group) / len(group)
        cy = sum(m[1] for m in group) / len(group)
        s = [(m[0] - cx) * tx + (m[1] - cy) * ty for m in group]
        a = (cx + tx * (min(s) - END_PAD_M), cy + ty * (min(s) - END_PAD_M))
        b = (cx + tx * (max(s) + END_PAD_M), cy + ty * (max(s) + END_PAD_M))
        head = _run_on(a[0], a[1], -tx, -ty, street_union, obstacles, Point)
        tail = _run_on(b[0], b[1], tx, ty, street_union, obstacles, Point)
        line = LineString(list(reversed(head)) + [a, b] + tail)
        if obstacles is not None:
            line = line.difference(obstacles)
        if line.length < MIN_LANE_M:
            continue
        pieces = [g for g in getattr(line, "geoms", [line])
                  if isinstance(g, LineString) and g.length >= MIN_PIECE_M]
        for piece in pieces:
            if way_tree is not None:
                close = [ways[i] for i in way_tree.query(piece.buffer(MAPPED_NEAR_M),
                                                          predicate="intersects")]
                if close and piece.intersection(
                        unary_union(close).buffer(MAPPED_NEAR_M)).length \
                        >= MAPPED_SHARE * piece.length:
                    continue
            out.append(OSMFeature(
                osm_id=FIRST_ID - len(out), kind="way",
                tags={"highway": "service", "service": "alley", "width": WIDTH_M,
                      "knoxmap": "back_alley"},
                geometry=[proj.to_latlon(x / k, y / k) for x, y in piece.coords]))
            for link in _cross_links(piece, tx, ty, street_union, obstacles, ways,
                                     way_tree, Point, LineString, unary_union):
                out.append(OSMFeature(
                    osm_id=FIRST_ID - len(out), kind="way",
                    tags={"highway": "service", "service": "alley", "width": WIDTH_M,
                          "knoxmap": "alley_link"},
                    geometry=[proj.to_latlon(x / k, y / k) for x, y in link.coords]))
    return out


# Cross-links: OpenStreetMap maps back alleys as networks, the lane behind the
# houses joined to the street in front by short passages through the gaps
# between terraces (Anfield). A passage is laid where a line square off the lane
# gets through the row to a street within REACH_M, clear of every building by
# CLEAR_M, at most one per gap and LINK_SPACING_M apart on each side. Not from
# the lane's own run-on to a street at its ends (LINK_END_CLEAR_M).
# Only through a gap LINK_GAP_M wide (clear of CLEAR_M each side), measured
# along the lane: on Anfield every mapped passage had 1.25-3.5 m, and every gap
# over 4 m was a missing house or open ground with no passage mapped.
LINK_STEP_M = 0.5
LINK_GAP_M = (1.0, 4.0)
LINK_SPACING_M = 40.0
LINK_END_CLEAR_M = 8.0


def _cross_links(piece, tx, ty, streets, obstacles, ways, way_tree,
                 Point, LineString, unary_union) -> list:
    """Short lanes from `piece` (a back alley, direction tx, ty) out through
    gaps in the rows either side of it to the street they front."""
    links = []
    steps = int(piece.length // LINK_STEP_M)
    for nx, ny in ((-ty, tx), (ty, -tx)):
        runs, run = [], []
        for i in range(steps + 1):
            p = piece.interpolate(i * LINK_STEP_M)
            hit = None
            if streets.distance(p) > LINK_END_CLEAR_M:
                reached, end = _straight(p.x, p.y, nx, ny, streets, obstacles, Point)
                if reached:
                    hit = ((p.x, p.y), end)
            if hit:
                run.append((i, hit))
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        last = None
        for run in runs:
            if not LINK_GAP_M[0] <= len(run) * LINK_STEP_M <= LINK_GAP_M[1]:
                continue
            i, (start, end) = run[len(run) // 2]         # the middle of the gap
            if last is not None and (i - last) * LINK_STEP_M < LINK_SPACING_M:
                continue
            line = LineString([start, end])
            if way_tree is not None:
                close = [ways[j] for j in way_tree.query(line.buffer(MAPPED_NEAR_M),
                                                          predicate="intersects")]
                if close and line.intersection(
                        unary_union(close).buffer(MAPPED_NEAR_M)).length \
                        >= MAPPED_SHARE * line.length:
                    continue                             # mapped there already
            links.append(line)
            last = i
    return links


def _straight(x, y, dx, dy, streets, obstacles, Point):
    """(reached a street, last clear point) running from (x, y) for REACH_M."""
    last = (x, y)
    for step in range(int(REACH_M) + 1):
        px, py = x + dx * step, y + dy * step
        here = Point(px, py)
        if step and obstacles is not None and obstacles.contains(here):
            return False, last
        last = (px, py)
        if streets.distance(here) <= 1.0:
            return True, last
    return False, last


# The lane's line is the average of its pairs' midpoints, and twenty metres on
# a degree off misses the gap between the two end houses, which is all the
# room the lane has (Anfield). So the run on is tried shifted sideways too.
SHIFTS_M = (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0)


def _run_on(x, y, dx, dy, streets, obstacles, Point) -> list:
    """Where a lane's end gets to, as the points past (x, y): straight on to the
    street ahead within REACH_M, through the gap between the end houses, or
    nowhere."""
    for shift in SHIFTS_M:
        sx, sy = x - dy * shift, y + dx * shift
        if shift and obstacles is not None and obstacles.contains(Point(sx, sy)):
            continue
        reached, end = _straight(sx, sy, dx, dy, streets, obstacles, Point)
        if reached:
            return [(sx, sy), end] if shift else [end]
    return []
