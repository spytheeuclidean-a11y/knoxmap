"""Crosswalks and stop lines where streets meet.

Build 42 ships kerbs and lane lines but no zebra crossing, so a crossing here
is laid out of the white lane-line tiles the road rules already place
(street_trafficlines_01). A line along the street on the near edge of every
tile across the carriageway, two tiles deep, reads from above as a row of
stripes - which is what a painted crossing looks like on a map.

Where one goes is decided from the streets themselves, not from the tarmac. A
junction is a point where three or more street ends meet, or where one street
ends on the length of another. Two street ends in line are one street carrying
on - OpenStreetMap splits a way at every change of lanes or name - and get
nothing; counting the ways near a point would paint a crossing into the middle
of every long road.

The crossing sits just outside the junction box, across the street being
approached, with a stop line a little further back on the approach side.
Diagonal streets are left alone: their stripes cannot be laid on the tile grid
without a zigzag, and the lane lines skip them for the same reason.
"""
from __future__ import annotations

import math

from .. import pz_colors as C
from .geometry import _feature_coords_px, _is_polygon
from .widths import _way_width_m

CROSSWALK_TILES = 2        # how deep along the street the stripes run
CROSSWALK_MIN_TILES = 4.5  # a lane narrower than this is not painted
JUNCTION_REACH = 1.5       # tiles: how near another street counts as meeting
STOP_LINE_GAP = 2          # tiles between the crossing and the stop line
MAX_JUNCTIONS = 4000       # a guard on pathological data
CELL = 4.0                 # tiles: the grid the segment index is kept on

# Tiles the crossing is allowed to paint over: the lane lines run down the
# middle of the street a crossing crosses, and a line through the stripes is a
# line nobody paints in a real one.
_LINE_TILES = (C.LINE_WHITE_N, C.LINE_WHITE_W, C.LINE_YELLOW_N, C.LINE_YELLOW_W,
               C.EDGE_LINE_N, C.EDGE_LINE_S, C.EDGE_LINE_W, C.EDGE_LINE_E)
# Straight kerbs, the ones a crossing can cut through. A dropped kerb is just
# no kerb: the pavement under it shows through.
_KERB_TILES = (C.KERB_N, C.KERB_S, C.KERB_E, C.KERB_W)


def _street_ways(buckets, proj) -> list[tuple[list[tuple[float, float]], float]]:
    """(ring in pixels, width in tiles) for every street worth a crossing."""
    ways = []
    for cat in ("road_major", "road_medium", "road_minor"):
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            tags = feat.tags
            if any(str(tags.get(key, "")).lower() in ("yes", "true", "1")
                   for key in ("tunnel", "covered")):
                continue
            # A bridge crosses what is under it, not what it meets.
            if str(tags.get("bridge", "")).lower() in ("yes", "true", "1"):
                continue
            if str(tags.get("layer", "0")).strip() not in ("", "0"):
                continue
            width = _way_width_m(feat, cat) / proj.meters_per_tile
            if width < CROSSWALK_MIN_TILES:
                continue
            for ring in _feature_coords_px(feat, proj):
                if len(ring) >= 2:
                    ways.append(([(float(x), float(y)) for x, y in ring], width))
    return ways


def _segments(ways) -> list[list[tuple[float, float, float, float]]]:
    """(x0, y0, x1, y1) for each piece of each street, street by street."""
    return [[(a[0], a[1], b[0], b[1]) for a, b in zip(ring, ring[1:]) if a != b]
            for ring, _width in ways]


def _near_point(px, py, segment) -> tuple[float, float, float]:
    """Closest point on a segment to (px, py), and its squared distance."""
    x0, y0, x1, y1 = segment
    dx, dy = x1 - x0, y1 - y0
    length = dx * dx + dy * dy
    t = 0.0 if not length else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length))
    nx, ny = x0 + dx * t, y0 + dy * t
    return nx, ny, (px - nx) ** 2 + (py - ny) ** 2


class _SegmentIndex:
    """The streets, bucketed by where they run, so a point asks only its own
    neighbourhood - a shapely tree over a county's worth of ways spent most of
    its time building a geometry per query."""

    def __init__(self, segments):
        self.segments = segments
        self.cells: dict[tuple[int, int], list[int]] = {}
        for index, (x0, y0, x1, y1) in enumerate(segments):
            steps = max(1, int(math.hypot(x1 - x0, y1 - y0) / (CELL / 2)) + 1)
            last = None
            for step in range(steps + 1):
                t = step / steps
                key = (int(math.floor((x0 + (x1 - x0) * t) / CELL)),
                       int(math.floor((y0 + (y1 - y0) * t) / CELL)))
                if key != last:
                    self.cells.setdefault(key, []).append(index)
                    last = key

    def near(self, x: float, y: float):
        """The segments in the nine cells around a point, nearest first is not
        needed: the callers measure the distance themselves."""
        cx, cy = int(math.floor(x / CELL)), int(math.floor(y / CELL))
        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in self.cells.get((cx + dx, cy + dy), ()):
                    if index in seen:
                        continue
                    seen.add(index)
                    yield index


def _unique(points, cell: float = 3.0) -> list[tuple[float, float]]:
    seen, out = set(), []
    for x, y in points:
        key = (int(math.floor(x / cell)), int(math.floor(y / cell)))
        if key in seen:
            continue
        seen.add(key)
        out.append((x, y))
    return out


def _tile(value: float) -> int:
    """The tile a coordinate falls in, rounding a half up rather than to even.

    round() takes 26.5 to 26 and 13.5 to 14, so a crossing whose offset landed
    on a half tile put both of its stripe rows on the same square and came out
    one tile deep.
    """
    return int(math.floor(value + 0.5))


def junction_points(ways) -> list[tuple[float, float]]:
    """Tile points where three or more street arms meet."""
    flat = [segment for own in _segments(ways) for segment in own]
    if not flat:
        return []
    index = _SegmentIndex(flat)
    # Two street ends meeting at a shared node are one street carrying on;
    # three or more is a junction.
    ends: dict[tuple[int, int], int] = {}
    for x0, y0, x1, y1 in flat:
        for key in ((round(x0), round(y0)), (round(x1), round(y1))):
            ends[key] = ends.get(key, 0) + 1
    points = [(float(key[0]), float(key[1])) for key, count in ends.items()
              if count >= 3]
    # A side street ending on the length of another has only its own end at
    # that point, so the count above never sees it.
    reach2 = JUNCTION_REACH ** 2
    for position, (x0, y0, x1, y1) in enumerate(flat):
        for x, y in ((x0, y0), (x1, y1)):
            joined = False
            for other in index.near(x, y):
                if other == position:
                    continue
                ox0, oy0, ox1, oy1 = flat[other]
                _nx, _ny, distance2 = _near_point(x, y, flat[other])
                if distance2 > reach2:
                    continue
                if min(math.hypot(x - ox0, y - oy0),
                       math.hypot(x - ox1, y - oy1)) <= JUNCTION_REACH:
                    continue        # a street carrying on, not joining
                joined = True
                break
            if joined:
                points.append((x, y))
    return _unique(points)[:MAX_JUNCTIONS]


def paint_crossings(veg, landscape, buckets, proj) -> dict:
    """Lay a crossing and a stop line on each approach to every junction."""
    import numpy as np

    counts = {"crosswalk": 0, "stop_line": 0, "kerb_cut": 0}
    ways = _street_ways(buckets, proj)
    if not ways:
        return counts
    points = junction_points(ways)
    if not points:
        return counts

    flat, owner = [], []
    for index, own in enumerate(_segments(ways)):
        for segment in own:
            flat.append(segment)
            owner.append(index)
    if not flat:
        return counts
    index = _SegmentIndex(flat)

    ground = np.asarray(landscape.convert("RGB"))
    height, width = ground.shape[:2]
    asphalt = np.zeros((height, width), dtype=bool)
    for colour in (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
                   C.DARK_POTHOLE, C.LIGHT_POTHOLE):
        asphalt |= np.all(ground == colour, axis=2)
    veg_px = veg.load()

    def road(x, y) -> bool:
        return 0 <= x < width and 0 <= y < height and bool(asphalt[y, x])

    def put(x, y, colour, along_x) -> bool:
        """One line tile, where the street is under it and nothing else is."""
        if not (0 <= x < width and 0 <= y < height):
            return False
        existing = veg_px[x, y]
        if existing not in (C.VEG_NOTHING, *_LINE_TILES):
            return False
        if not road(x, y):
            return False
        # The line sits on the edge between two tiles, so the square behind it
        # has to be street too or the paint hangs over the kerb.
        behind = road(x, y - 1) if along_x else road(x - 1, y)
        if not behind:
            return False
        if existing == colour:
            return False        # this stripe is already painted
        veg_px[x, y] = colour
        return True

    def cut(x, y, dx, dy) -> bool:
        """Drop the kerb where a crossing runs out of road.

        Walk out from the last stripe square until a straight kerb turns up, or
        something that is not street-side emptiness does. Taking the kerb tile
        away leaves the pavement showing, which from above is what a dropped
        kerb at a crossing looks like.
        """
        for k in range(0, 4):
            cx, cy = x + dx * k, y + dy * k
            if not (0 <= cx < width and 0 <= cy < height):
                return False
            existing = veg_px[cx, cy]
            if existing in _KERB_TILES:
                veg_px[cx, cy] = C.VEG_NOTHING
                return True
            if existing != C.VEG_NOTHING:
                return False
        return False

    for jx, jy in points:
        near = []
        seen = set()
        for position in index.near(jx, jy):
            way = owner[position]
            if way in seen:
                continue
            nx, ny, distance2 = _near_point(jx, jy, flat[position])
            if distance2 > 2.5 ** 2:
                continue
            seen.add(way)
            near.append((nx, ny, ways[way][1], flat[position]))
        if len(near) < 2:
            continue
        widest = max(road_width for _x, _y, road_width, _seg in near)
        for nx, ny, road_width, segment in near:
            # The street's own direction where it passes this junction.
            x0, y0, x1, y1 = segment
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if not length:
                continue
            ux, uy = dx / length, dy / length
            # The junction box is as deep as half the widest street through it.
            offset = widest / 2 + 1
            across = road_width / 2
            if abs(uy) <= 0.2 * abs(ux):            # a street running east-west
                step = 1 if ux > 0 else -1
                for side in (1, -1):
                    laid = False
                    first = _tile(nx + step * side * offset)
                    y_lo = int(math.floor(ny - across))
                    y_hi = int(math.ceil(ny + across))
                    for k in range(CROSSWALK_TILES):
                        x = first + step * side * k
                        for y in range(y_lo, y_hi + 1):
                            laid |= put(x, y, C.LINE_WHITE_N, True)
                        # A kerb cut at each end of the crossing, on the far
                        # side of the carriageway from the middle of it.
                        counts["kerb_cut"] += cut(x, y_lo, 0, -1)
                        counts["kerb_cut"] += cut(x, y_hi, 0, 1)
                    counts["crosswalk"] += laid
                    stop = _tile(nx + step * side *
                                 (offset + CROSSWALK_TILES + STOP_LINE_GAP))
                    # Right-hand traffic: approaching from the west the near
                    # lanes are the southern half, from the east the northern.
                    low = ny - across if step * side > 0 else ny
                    high = ny if step * side > 0 else ny + across
                    laid = False
                    for y in range(int(math.floor(low)), int(math.ceil(high)) + 1):
                        laid |= put(stop, y, C.LINE_WHITE_W, False)
                    counts["stop_line"] += laid
            elif abs(ux) <= 0.2 * abs(uy):          # a street running north-south
                step = 1 if uy > 0 else -1
                for side in (1, -1):
                    laid = False
                    first = _tile(ny + step * side * offset)
                    x_lo = int(math.floor(nx - across))
                    x_hi = int(math.ceil(nx + across))
                    for k in range(CROSSWALK_TILES):
                        y = first + step * side * k
                        for x in range(x_lo, x_hi + 1):
                            laid |= put(x, y, C.LINE_WHITE_W, False)
                        counts["kerb_cut"] += cut(x_lo, y, -1, 0)
                        counts["kerb_cut"] += cut(x_hi, y, 1, 0)
                    counts["crosswalk"] += laid
                    stop = _tile(ny + step * side *
                                 (offset + CROSSWALK_TILES + STOP_LINE_GAP))
                    # Approaching from the north the near lanes are the
                    # western half, from the south the eastern.
                    low = nx - across if step * side > 0 else nx
                    high = nx if step * side > 0 else nx + across
                    laid = False
                    for x in range(int(math.floor(low)), int(math.ceil(high)) + 1):
                        laid |= put(x, stop, C.LINE_WHITE_N, True)
                    counts["stop_line"] += laid
    return counts
