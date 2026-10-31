"""Buildings for the gaps along a street that has buildings either side of them.

OpenStreetMap is traced by hand, so a high street can have its first six shops
drawn, the seventh missing and the next four drawn again. The generated map
then has a hole in the row where anyone can see a building belongs. This fills
those holes, and only those: it looks at what stands along each street, finds
a stretch of frontage with nothing on it between buildings that are there, and
puts buildings in it that are built like their neighbours.

What "like their neighbours" means is measured, not assumed, from the
buildings on either side of the gap:

    width      how much street each one takes up
    depth      how far back it goes
    set back   how far its front wall stands from the edge of the pavement
    kind       house, shop, flats ... and how many storeys

A street wall (shops standing on the pavement) is filled wall to wall; a row
of houses with gardens is filled with houses with a gap between. A lot is
dropped rather than squeezed in wherever it would touch a building, a road,
water, a park, a wood or the edge of the drawn map, and a stretch with a
building on neither side is left alone: this extends a street that is there, it
does not found a town. `houses_from_addresses` (buildings.py) and Overture
(generator/overture.py) are the other two ways a map gets buildings OSM does
not have; this one needs no data from anywhere.
"""
from __future__ import annotations

import statistics
from collections import Counter

from ..osm import OSMFeature, classify
from .buildings import ADDRESS_AVOIDS_ROADS
from .geometry import _feature_coords_px, _is_polygon
from .landcover import WATERWAY_WIDTH_M
from .projection import Projector
from .widths import _sidewalk_width_m, _way_width_m

# Streets that get frontage looked at. Service lanes and drives do not: a
# building beside one is a shed or a back door, not a street front.
FRONTAGE_ROADS = ("road_major", "road_medium", "road_minor")

STEP_M = 2.0               # how often the frontage is looked at
REACH_BUILDING_M = 20.0    # a building this close behind the pavement fronts the street
REACH_M = 40.0             # how far back the probe looks for anything at all
MIN_DEPTH_M = 7.0          # less room than this and nothing fits
REAR_CLEAR_M = 2.5         # kept clear behind a new building

MIN_NEIGHBOUR_M2 = 40.0    # sheds and garages say nothing about the street
MIN_LOT_M = 5.0            # narrowest new building
MAX_LOT_M = 28.0           # widest; a longer gap is cut into more lots
SIDE_GAP_M = 3.0           # between detached houses
STREET_WALL_M = 3.5        # set back less than this and the row is a street wall
MAX_GAP_BOTH_M = 140.0     # longest gap filled with a building on both sides
MAX_GAP_ONE_M = 45.0       # and with one: the row is carried a little further
MAX_PER_GAP = 12
MAX_INFILL = 20000
FIRST_ID = -2_000_000_000  # below Overture's (generator/overture.py)

# What may be copied from a neighbour. Anything else beside the gap - a church,
# a school, a warehouse, a garage - does not say what stands next to it.
FILL_KINDS = {"yes", "house", "detached", "semidetached_house", "terrace",
              "residential", "apartments", "retail", "commercial", "office",
              "hotel", "dormitory", "mixed_use"}

# Ground that is not for building on, drawn as areas.
BLOCKING_AREAS = {"water", "pool", "park", "sports", "playground", "cemetery",
                  "wetland", "track", "parking", "plaza", "sand", "orchard",
                  "farmland", "pier", "military", "schoolyard", "worship_grounds",
                  "hospital_grounds", "pedestrian"}
BLOCKING_VEGETATION = {"forest", "scrub"}


def _polys(feat: OSMFeature, proj: Projector, scale: float):
    """A feature's outlines as shapely polygons in metres."""
    from shapely.geometry import Polygon

    out = []
    for ring in _feature_coords_px(feat, proj):
        if len(ring) < 3:
            continue
        poly = Polygon([(x * scale, y * scale) for x, y in ring])
        if not poly.is_valid:
            poly = poly.buffer(0)
        for part in getattr(poly, "geoms", [poly]):
            if part.geom_type == "Polygon" and part.area > 0:
                out.append(part)
    return out


CHOP_M = 200.0


def _chopped(geoms):
    """The same ground in pieces no bigger than CHOP_M across.

    A wood or a lake can have a thousand vertices and the extent of the map,
    and every probe that lands in its bounding box is tested against all of
    them: minutes on a county. In squares each test is against a few.
    """
    import numpy as np
    import shapely
    from shapely.geometry import box

    out = []
    for g in shapely.simplify(np.array(geoms, dtype=object), 0.5):
        x0, y0, x1, y1 = g.bounds
        if (x1 - x0 <= CHOP_M and y1 - y0 <= CHOP_M) or g.geom_type != "Polygon":
            out.append(g)
            continue
        shapely.prepare(g)
        for cx in range(int(x0 // CHOP_M), int(x1 // CHOP_M) + 1):
            for cy in range(int(y0 // CHOP_M), int(y1 // CHOP_M) + 1):
                square = box(cx * CHOP_M, cy * CHOP_M,
                             (cx + 1) * CHOP_M, (cy + 1) * CHOP_M)
                if not g.intersects(square):
                    continue
                piece = g.intersection(square)
                out.extend(p for p in getattr(piece, "geoms", [piece])
                           if p.geom_type == "Polygon" and not p.is_empty)
    return np.array(out, dtype=object)


class _Grid:
    """New lots, found again by where they are, so a lot is only checked
    against the ones near it."""
    CELL = 40.0

    def __init__(self):
        self.cells: dict[tuple[int, int], list] = {}

    def near(self, poly):
        x0, y0, x1, y1 = poly.bounds
        seen, out = set(), []
        for cx in range(int(x0 // self.CELL), int(x1 // self.CELL) + 1):
            for cy in range(int(y0 // self.CELL), int(y1 // self.CELL) + 1):
                for p in self.cells.get((cx, cy), ()):
                    if id(p) not in seen:
                        seen.add(id(p))
                        out.append(p)
        return out

    def add(self, poly):
        x0, y0, x1, y1 = poly.bounds
        for cx in range(int(x0 // self.CELL), int(x1 // self.CELL) + 1):
            for cy in range(int(y0 // self.CELL), int(y1 // self.CELL) + 1):
                self.cells.setdefault((cx, cy), []).append(poly)


def _side_scan(line, half_edge, sign, buildings, b_tree, hard_geoms, hard_tree):
    """Look along one side of a street, every STEP_M.

    Returns the stations (position, tangent, normal) and, for each, its state:
    ("B", building index, distance) where a building stands in front of it,
    ("E", free depth) where nothing does, and ("X",) where it is blocked.
    """
    import numpy as np
    import shapely

    length = line.length
    s = np.arange(STEP_M / 2, length, STEP_M)
    if len(s) < 3:
        return None
    pts = shapely.line_interpolate_point(line, s)
    ahead = shapely.line_interpolate_point(line, np.minimum(s + 1.0, length))
    behind = shapely.line_interpolate_point(line, np.maximum(s - 1.0, 0.0))
    px, py = shapely.get_x(pts), shapely.get_y(pts)
    tx = shapely.get_x(ahead) - shapely.get_x(behind)
    ty = shapely.get_y(ahead) - shapely.get_y(behind)
    norm = np.hypot(tx, ty)
    norm[norm == 0] = 1.0
    tx, ty = tx / norm, ty / norm
    nx, ny = -ty * sign, tx * sign            # out from the road, on this side
    ax, ay = px + nx * half_edge, py + ny * half_edge
    anchors = shapely.points(ax, ay)
    probes = shapely.linestrings(np.stack(
        [np.stack([ax, ay], axis=1),
         np.stack([ax + nx * REACH_M, ay + ny * REACH_M], axis=1)], axis=1))

    n = len(s)
    hard = np.full(n, REACH_M)
    if hard_tree is not None:
        pi, gi = hard_tree.query(probes, predicate="intersects")
        if len(pi):
            d = shapely.distance(anchors[pi], hard_geoms[gi])
            np.minimum.at(hard, pi, d)
    near_b = np.full(n, np.inf)
    which = np.full(n, -1)
    if b_tree is not None:
        pi, gi = b_tree.query(probes, predicate="intersects")
        if len(pi):
            d = shapely.distance(anchors[pi], buildings[gi])
            order = np.lexsort((d, pi))
            pi, gi, d = pi[order], gi[order], d[order]
            first = np.unique(pi, return_index=True)[1]
            near_b[pi[first]] = d[first]
            which[pi[first]] = gi[first]
    return {"s": s, "x": px, "y": py, "tx": tx, "ty": ty, "nx": nx, "ny": ny,
            "ax": ax, "ay": ay, "hard": hard, "near_b": near_b, "which": which}


def _states(scan):
    """B (built on), E (free, with room), X (no room) for each station."""
    out = []
    for hard, nb in zip(scan["hard"], scan["near_b"]):
        if nb <= REACH_BUILDING_M and nb < hard:
            out.append("B")
        elif min(hard, nb) < MIN_DEPTH_M:
            out.append("X")
        else:
            out.append("E")
    return out


def _neighbours(scan, states, i, step, info, limit=3):
    """The buildings (up to `limit`) in the unbroken stretch of built frontage
    that starts next to station `i` and goes in direction `step`."""
    seen: list[int] = []
    j = i
    while 0 <= j < len(states) and states[j] == "B":
        b = int(scan["which"][j])
        if b not in seen:
            if len(seen) == limit:
                break
            seen.append(b)
        j += step
    return [info[b] for b in seen
            if info[b] and info[b]["area"] >= MIN_NEIGHBOUR_M2]


def _describe(scan, states, bi, poly, tags):
    """How one neighbouring building sits on the street: the metres of
    frontage it takes up, how deep it is, how far back it stands."""
    idx = [k for k, (st, w) in enumerate(zip(states, scan["which"]))
           if st == "B" and int(w) == bi]
    if not idx:
        return None
    width = (idx[-1] - idx[0] + 1) * STEP_M
    k = idx[len(idx) // 2]
    nx, ny = scan["nx"][k], scan["ny"][k]
    ox, oy = scan["ax"][k], scan["ay"][k]
    proj_d = [(x - ox) * nx + (y - oy) * ny for x, y in poly.exterior.coords]
    return {"width": width, "depth": max(proj_d) - min(proj_d),
            "setback": max(0.0, min(proj_d)), "area": poly.area,
            "kind": (tags.get("building") or "yes").lower(),
            "levels": tags.get("building:levels")}


def _modal_kind(near):
    kinds = Counter(n["kind"] for n in near)
    return max(kinds, key=lambda k: (kinds[k], k != "yes"))


def _levels(near):
    vals = []
    for n in near:
        try:
            v = int(float(str(n["levels"]).split(";")[0]))
        except (TypeError, ValueError):
            continue
        if 0 < v < 60:
            vals.append(v)
    return str(int(round(statistics.median(vals)))) if vals else None


def _lots_for_gap(scan, i0, i1, left, right, hard_free):
    """Footprints (as lists of four metre corners) for the free frontage
    between stations i0 and i1, built like the buildings beside it."""
    near = left + right
    # One side only is a row carried on, and a row is two buildings at least;
    # a lone house in the country does not found a street.
    if not near or (not (left and right) and len(near) < 2):
        return []
    kinds = {n["kind"] for n in near}
    if not kinds <= FILL_KINDS:
        return []
    width = statistics.median(n["width"] for n in near)
    depth = statistics.median(n["depth"] for n in near)
    setback = statistics.median(n["setback"] for n in near)
    wall = setback <= STREET_WALL_M
    gap = 0.0 if wall else SIDE_GAP_M

    length = (i1 - i0 + 1) * STEP_M
    both = bool(left and right)
    limit = min(MAX_GAP_BOTH_M, max(40.0, 10 * width)) if both else \
        min(MAX_GAP_ONE_M, max(20.0, 2.5 * width))
    if length > limit or length < MIN_LOT_M:
        return []

    # The pavement edge of the gap; ends against a neighbour keep a garden's
    # width from it, ends against a road or nothing keep a little less.
    inset_l = 0.4 if wall else (SIDE_GAP_M if left else 1.5)
    inset_r = 0.4 if wall else (SIDE_GAP_M if right else 1.5)
    start = i0 * STEP_M + inset_l
    end = (i1 + 1) * STEP_M - inset_r
    span = end - start
    if span < MIN_LOT_M:
        return []

    target = min(max(width, 6.0), MAX_LOT_M)
    # Room for a building about as wide as its neighbours or it is a yard, not
    # a gap: the garden between two houses is not a house that was not drawn.
    if span < 0.7 * target:
        return []
    n = max(1, int(round((span + gap) / (target + gap))))
    n = min(n, MAX_PER_GAP)
    while n > 1 and (span - (n - 1) * gap) / n < MIN_LOT_M:
        n -= 1
    while (span - (n - 1) * gap) / n > MAX_LOT_M and n < MAX_PER_GAP:
        n += 1
    bw = (span - (n - 1) * gap) / n
    if bw < MIN_LOT_M:
        return []

    out = []
    for k in range(n):
        a = start + k * (bw + gap)
        b = a + bw
        # which stations this lot spans, for the room behind it and the angle
        lo = max(i0, int(a // STEP_M))
        hi = min(i1, int(b // STEP_M))
        room = min(hard_free[lo:hi + 1])
        d = min(depth, room - setback - REAR_CLEAR_M)
        if d < MIN_DEPTH_M:
            continue
        mid = min(max(int(((a + b) / 2) // STEP_M), i0), i1)
        tx, ty = scan["tx"][mid], scan["ty"][mid]
        nx, ny = scan["nx"][mid], scan["ny"][mid]
        # the pavement point opposite the lot's middle
        off = (a + b) / 2 - scan["s"][mid]
        cx = scan["ax"][mid] + tx * off
        cy = scan["ay"][mid] + ty * off
        cx += nx * (max(setback, 0.3) + d / 2)
        cy += ny * (max(setback, 0.3) + d / 2)
        hw, hd = bw / 2, d / 2
        out.append([(cx - tx * hw - nx * hd, cy - ty * hw - ny * hd),
                    (cx + tx * hw - nx * hd, cy + ty * hw - ny * hd),
                    (cx + tx * hw + nx * hd, cy + ty * hw + ny * hd),
                    (cx - tx * hw + nx * hd, cy - ty * hw + ny * hd)])
    return out, _modal_kind(near), _levels(near)


def _infill_frontage(buckets: dict, vegetation_feats: list, building_feats: list,
                     proj: Projector, clip=None) -> list[OSMFeature]:
    """New buildings for the gaps along streets. See the module docstring."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString, Polygon
    from shapely.strtree import STRtree

    from .projection import _inside

    k = proj.meters_per_tile

    # Everything already standing.
    b_polys, b_tags = [], []
    for f in building_feats:
        for poly in _polys(f, proj, k):
            b_polys.append(poly)
            b_tags.append(f.tags)
    if not b_polys:
        return []
    b_geoms = np.array(b_polys, dtype=object)
    b_tree = STRtree(b_geoms)

    # Everything a building cannot stand on: the roads' own width and pavement
    # (every kind of street, not only the ones looked along), railways, water,
    # parks and woods.
    hard: list = []
    fronts = []
    for cat in ADDRESS_AVOIDS_ROADS | {"railway"}:
        for f in buckets.get(cat, []):
            if _is_polygon(f):
                continue
            half = _way_width_m(f, cat) / 2 + _sidewalk_width_m(f, cat)
            for ring in _feature_coords_px(f, proj):
                if len(ring) < 2:
                    continue
                line = LineString([(x * k, y * k) for x, y in ring])
                if line.length < 0.5:
                    continue
                hard.append(line.buffer(half, cap_style="flat"))
                if (cat in FRONTAGE_ROADS and line.length >= 3 * STEP_M
                        and not f.tags.get("bridge") and not f.tags.get("tunnel")
                        and f.tags.get("access") != "private"):
                    fronts.append((line, half))
    for cat in BLOCKING_AREAS:
        for f in buckets.get(cat, []):
            if _is_polygon(f):
                hard.extend(_polys(f, proj, k))
            elif cat == "water":
                reach = WATERWAY_WIDTH_M.get(f.tags.get("waterway"), 3.0) / 2 + 1
                for ring in _feature_coords_px(f, proj):
                    if len(ring) >= 2:
                        hard.append(LineString([(x * k, y * k) for x, y in ring]).buffer(reach))
    for f in vegetation_feats:
        if _is_polygon(f) and classify(f.tags, True) in BLOCKING_VEGETATION:
            hard.extend(_polys(f, proj, k))
    hard_geoms = _chopped(hard) if hard else None
    hard_tree = STRtree(hard_geoms) if hard else None
    if not fronts:
        return []

    width_m, height_m = proj.width * k, proj.height * k
    grid = _Grid()
    made: list[OSMFeature] = []
    ident = FIRST_ID

    for line, half in fronts:
        for sign in (1, -1):
            if len(made) >= MAX_INFILL:
                break
            scan = _side_scan(line, half + 0.3, sign, b_geoms, b_tree,
                              hard_geoms, hard_tree)
            if scan is None:
                continue
            states = _states(scan)
            if "E" not in states or "B" not in states:
                continue
            info: dict[int, dict | None] = {}
            for bi in {int(w) for st, w in zip(states, scan["which"]) if st == "B"}:
                info[bi] = _describe(scan, states, bi, b_polys[bi], b_tags[bi])
            free = [min(h, nb) for h, nb in zip(scan["hard"], scan["near_b"])]

            i = 0
            while i < len(states):
                if states[i] != "E":
                    i += 1
                    continue
                j = i
                while j + 1 < len(states) and states[j + 1] == "E":
                    j += 1
                left = _neighbours(scan, states, i - 1, -1, info) if i > 0 else []
                right = _neighbours(scan, states, j + 1, 1, info) if j + 1 < len(states) else []
                run = (i, j)
                i = j + 1
                if not (left or right):
                    continue
                got = _lots_for_gap(scan, run[0], run[1], left, right, free)
                if not got:
                    continue
                lots, kind, levels = got
                for corners in lots:
                    poly = Polygon(corners)
                    if not poly.is_valid or poly.is_empty:
                        continue
                    x0, y0, x1, y1 = poly.bounds
                    if x0 < 0 or y0 < 0 or x1 > width_m or y1 > height_m:
                        continue
                    core = poly.buffer(-0.4)
                    if core.is_empty:
                        continue
                    if b_tree.query(core, predicate="intersects").size:
                        continue
                    if hard_tree is not None and hard_tree.query(core, predicate="intersects").size:
                        continue
                    if any(core.intersects(p) for p in grid.near(poly)):
                        continue
                    tags = {"building": kind}
                    if levels:
                        tags["building:levels"] = levels
                    feat = OSMFeature(
                        osm_id=ident, kind="way", tags=tags,
                        geometry=[proj.to_latlon(x / k, y / k)
                                  for x, y in corners + [corners[0]]])
                    if clip is not None and not _inside(feat, proj, clip):
                        continue
                    grid.add(poly)
                    made.append(feat)
                    ident -= 1
    return made
