"""What makes an area or a scale acceptable: the sizes the window warns about, a drawn
outline checked and folded, and whether a map will fit in memory.
"""
from __future__ import annotations

import sys

import knoxlog


# Where a map stops being an easy one. None of these refuses anything: they
# are what the window warns about, and what the log records, so somebody who
# wants a whole city can have one and knows what they are in for.
#
# They used to be hard limits, and a limit that says no is worth having only
# when the thing behind it cannot be done. These can: the area cap was
# originally 20 km2 because that is about all one Overpass query will answer,
# and osm.fetch_features_tiled lifted that by splitting a big request into a
# grid of small ones. What is left is memory and patience, and both are the
# mapper's to spend.
#
# BIG_TILES_PER_SIDE is the memory one: the renderer holds a landscape and a
# vegetation image at full size, 3 bytes a tile each, so 20000 tiles a side is
# about 2.4 GB of pixels before anything else.
BIG_AREA_KM2 = 1000.0
OVERPASS_TILE_KM2 = 30.0       # size of each sub-query; overshoot re-splits
BIG_TILES_PER_SIDE = 20000     # 66 cells at 300 tiles each
# A scale still has to be a scale: zero or a negative divides the world by
# nothing. The range the window offers is 0.5 to 8; outside it is allowed and
# said to be unusual.
MIN_METERS_PER_TILE = 0.5
MAX_METERS_PER_TILE = 100.0
# Scales are kept to quarter metres. It used to be whole metres above one, on
# the grounds that a tile is a metre in the game and anything between buys
# nothing - but between 1 and 2 is exactly where it buys something: at 1 a
# town is as big as it really is and at 2 everything in it is half the size,
# and people asked for the steps in between to find the size they wanted. A
# quarter is as fine as it goes, so a scale stays a number somebody can read
# off a map folder rather than 1.0137.
SCALE_STEP = 0.25


def tidy_scale(metres: float) -> float:
    """The nearest scale the map is really drawn at."""
    stepped = round(metres / SCALE_STEP) * SCALE_STEP
    return float(min(max(stepped, MIN_METERS_PER_TILE), MAX_METERS_PER_TILE))
USUAL_METERS_PER_TILE = (1.0, 8.0)

# Landmark lookup asks for far more tag keys than the terrain query, so it is
# the first thing to get slow.
BIG_LANDMARK_KM2 = 40.0


# Enough for a town boundary traced in detail; more is a mistake or an abuse.
MAX_SHAPE_POINTS = 20000


def _shape_rings(shape: dict) -> list:
    polys = shape["coordinates"] if shape["type"] == "MultiPolygon" else [shape["coordinates"]]
    return [ring for rings in polys for ring in rings]


# Smaller than this and the outline is a line, not a selection: about a
# hundredth of a square kilometre, well under the smallest map worth building.
MIN_SHAPE_AREA_DEG2 = 1e-6


def _shape_area_deg2(polys: list) -> float:
    """The area the outer rings enclose, in square degrees.

    The shoelace sum, not shapely: this runs on every generate request, before
    anything has decided the map is worth loading a geometry library for.
    """
    total = 0.0
    for rings in polys:
        if not rings:
            continue
        ring = rings[0]
        acc = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            acc += x0 * y1 - x1 * y0
        total += abs(acc) / 2.0
    return total


def _clean_shape(raw) -> tuple[dict | None, str | None]:
    """A drawn selection as GeoJSON Polygon/MultiPolygon, checked and folded.

    The page sends one for a polygon, a circle, a freehand lasso or a place's
    real outline; a rectangle sends none. Longitudes are folded back into
    range the same way the bbox is, and the points are counted so a broken
    page cannot hand the renderer a million-vertex outline.
    """
    if not raw:
        return None, None
    try:
        kind = raw["type"]
        if kind not in ("Polygon", "MultiPolygon"):
            return None, "The selection must be a polygon."
        polys = raw["coordinates"] if kind == "MultiPolygon" else [raw["coordinates"]]
        cleaned, points = [], 0
        for rings in polys:
            out_rings = []
            for ring in rings:
                pts = [[_wrap_lon(float(lon)), float(lat)] for lon, lat in ring]
                points += len(pts)
                if len(pts) >= 3:
                    if pts[0] != pts[-1]:
                        pts.append(pts[0])
                    out_rings.append(pts)
            if out_rings:
                cleaned.append(out_rings)
    except (KeyError, TypeError, ValueError):
        return None, "The selection shape could not be read."
    if not cleaned:
        return None, "The selection shape has no area."
    if points > MAX_SHAPE_POINTS:
        return None, f"The selection outline has {points:,} points; the most is {MAX_SHAPE_POINTS:,}."
    # An outline with three points on one line, or one drawn as a single
    # stroke that never opened out, passes every test above and covers no
    # ground. The renderer takes it at its word and turns everything outside
    # it - which is the whole map - back into grass, so the generation runs to
    # the end and hands over a meadow. Saying so here is the only place the
    # user can still do anything about it.
    if _shape_area_deg2(cleaned) < MIN_SHAPE_AREA_DEG2:
        return None, ("The drawn selection covers no area. Draw it again as "
                      "an outline around the place rather than a single line.")
    if kind == "Polygon":
        return {"type": "Polygon", "coordinates": cleaned[0]}, None
    return {"type": "MultiPolygon", "coordinates": cleaned}, None


def _wrap_lon(lon: float) -> float:
    """Fold a longitude back into -180..180."""
    return (lon + 180.0) % 360.0 - 180.0


def _normalise_bbox(south: float, west: float, north: float,
                    east: float) -> tuple[tuple[float, float, float, float],
                                          str | None]:
    """Clean a bbox from the map widget, or say why it cannot be used.

    Leaflet hands back *unwrapped* coordinates once the map has been panned
    across a world copy: drag east past the date line twice and a rectangle
    over Bergama arrives as longitude 747.17 rather than 27.17. It passes
    west < east and it passes the area check, because the span is still small -
    and then every Overpass server rejects it with "the only allowed values are
    floats between -180.0 and 180.0", which reaches the page as three identical
    walls of XHTML and no clue that panning caused it.
    """
    south = max(-85.05, min(85.05, south))
    north = max(-85.05, min(85.05, north))
    west, east = _wrap_lon(west), _wrap_lon(east)
    if not south < north:
        return (south, west, north, east), "BBox is degenerate."
    if west == east:
        return (south, west, north, east), "BBox is degenerate."
    if west > east:
        # Wrapping put the two edges either side of the date line. Splitting
        # the query would work but every map built here would then straddle
        # the seam, so say so rather than quietly building half of it.
        return ((south, west, north, east),
                "That selection crosses the 180th meridian. Draw it on one "
                "side or the other.")
    return (south, west, north, east), None


# Drawing a map holds several pictures of it at once - the ground, the
# vegetation, the masks the gardens and the paving are worked out from. Measured
# on real towns (a 2400 x 2400 Paris peaked at 0.54 GB, a 1200 x 900 Manhattan
# at 0.12 GB), that is about this much, plus what the program itself takes.
BYTES_PER_TILE = 80
BASE_BYTES = 150e6
# Generate buildings reads the ground and vegetation back (3 bytes a tile each)
# and works masks out of them. Measured on a 7200 x 4800 map: 684 MB at the
# peak, 20 bytes a tile; this leaves some room over that. The same numbers are
# in static/js/app.js (BUILD_BYTES_PER_TILE).
BUILD_BYTES_PER_TILE = 24
BUILD_BASE_BYTES = 300e6

# The settings the ground itself is drawn from. Change one of these and the
# map has to be rendered again; every other knob is read while the buildings
# are generated, and those can be laid out afresh on the ground already there.
# Changing the woodland used to mean drawing the box and setting every knob a
# second time, so the page asks for this (/api/settings) and runs only the
# steps a change really needs. tests/test_render_settings.py checks it against
# what generate() actually reads, so the two cannot drift apart.
RENDER_SETTINGS = ["align_streets", "rotate_degrees", "straight_roads",
                   "tree_density", "forest_density", "fill_gaps", "fill_frontage"]


def _too_big_for_memory(tiles_w: float, tiles_h: float,
                        per_tile: float = BYTES_PER_TILE,
                        base: float = BASE_BYTES) -> str | None:
    """Why this map will not fit in memory, or None when it should.

    A 32-bit Python can only use about 2 GB however much the PC has, and a map
    of a few square kilometres needs more: it used to get halfway through and
    fail with "MemoryError".
    """
    import knoxpaths
    needed = tiles_w * tiles_h * per_tile + base
    status = knoxlog.memory_status()
    if not status:
        return None
    _total, free, room = status
    smaller = "Pick a smaller area, or a larger scale (metres per tile)."
    if sys.maxsize <= 2 ** 32 and needed > room * 0.8:
        return (f"This map needs about {needed / 1e9:.1f} GB of memory, and KnoxMap is "
                f"running 32-bit Python, which can only use about 2 GB however much this "
                f"PC has. Close KnoxMap and run {knoxpaths.setup_command()} again: it "
                f"fetches a 64-bit "
                f"Python and makes its environment again. " + smaller)
    if needed > min(free, room) * 0.8:
        return (f"This map needs about {needed / 1e9:.1f} GB of memory and only "
                f"{min(free, room) / 1e9:.1f} GB is free. Close a few things and try "
                f"again. " + smaller)
    return None


def _beyond_this_pc(tiles_w: float, tiles_h: float) -> str | None:
    """Why this map cannot be made on this PC however much is closed, or None.

    A map that needs more memory than the PC has installed cannot work, and
    trying it only fills the disk with swap before it fails. A map that merely
    does not fit in what is free now is still allowed through (a warning)."""
    status = knoxlog.memory_status()
    if not status:
        return None
    total = status[0]
    needed = tiles_w * tiles_h * BYTES_PER_TILE + BASE_BYTES
    if total and needed > total:
        return (f"This map needs about {needed / 1e9:.0f} GB of memory and this PC has "
                f"{total / 1e9:.0f} GB, so it cannot be made here. Pick a smaller area, "
                f"or a larger scale (metres per tile).")
    return None
