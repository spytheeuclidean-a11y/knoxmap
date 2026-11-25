"""How wide roads, pavements and verges are drawn, and how a road is marked."""
from __future__ import annotations

import math

from ..osm import OSMFeature, road_hierarchy


# Road widths in meters. Converted to pixels by dividing by meters_per_tile.
#
# These are the fallbacks. A way carrying lanes= or width= is measured from
# those instead, because every street in a class being identically wide is what
# made the towns read as a printed circuit rather than a place - real ones have
# a four-lane high street feeding two-lane side roads feeding one-car alleys.
ROAD_WIDTHS_M = {
    "road_major": 12.0,
    "road_medium": 8.0,
    "road_minor": 6.0,
    "road_service": 3.5,
    # A pedestrian zone is as wide as the square it paves, not as wide as
    # a lane; mapped as lines with no area round them, this is what fills
    # the space between the buildings.
    "pedestrian": 9.0,
    "dirt_path": 2.5,
    "paved_path": 2.5,
    "pier": 3.0,
    # A breakwater is a wall of stone with a road on it, not a jetty: on the
    # 3 m fallback of a line category it read as a narrow causeway.
    "breakwater": 6.0,
    "railway": 4.0,
    # An airfield. A runway is the widest thing a town has by a long way:
    # a county strip is 18-23 m, a regional one 30, an international 45-60.
    # 30 is the middle of that and what an untagged one gets.
    "runway": 30.0,
    "taxiway": 15.0,
}
# Paved shoulder either side of a runway (FAA/ICAO commercial standard is
# ~3-4.5 m; 9 m each side produced an oversized concrete slab). Metres each side.
RUNWAY_SHOULDER_M = 3.5

# What a tagged width may be believed up to, by category. A street tagged
# sixty metres wide is a mistake somebody made; a runway tagged forty-five
# is a runway.
MAX_TAGGED_WIDTH_M = {"runway": 80.0, "taxiway": 45.0}
# The narrowest a road may come out, in tiles, whatever the scale makes of
# its width in metres.
#
# Measured on the squares of the game's own Muldraugh (four cells, 894 runs
# of street): the median street is 8 tiles of asphalt, 515 runs are 8 wide,
# 187 are 6 and 76 are 10. Vanilla's roads are wider than the real ones they
# stand for, because two cars have to pass on them and a player has to walk
# between them - and a width in metres divided by the map's scale does not
# know that. At 2 m a tile a 6 m street came out 3 tiles: one car, no room
# to pass, and a town that read as a plan of itself rather than a place.
MIN_ROAD_TILES = {
    "road_major": 10,
    "road_medium": 8,
    "road_minor": 6,
    "road_service": 3,
}


def road_width_tiles(feat: OSMFeature, cat: str, metres_per_tile: float,
                     extra_m: float = 0.0) -> int:
    """How many tiles wide to draw this way, never narrower than the game's own.

    `extra_m` is a band on each side - a pavement, a shoulder - added after
    the floor, so that widening the carriageway widens what sits beside it
    with it and the two keep agreeing about where the road ends.
    """
    from .geometry import _pixel_width
    tiles = max(_pixel_width(_way_width_m(feat, cat), metres_per_tile),
                MIN_ROAD_TILES.get(cat, 0))
    if extra_m > 0:
        tiles += 2 * _pixel_width(extra_m, metres_per_tile)
    return tiles


ROAD_WIDTHS_BY_HIERARCHY_M = {
    "motorway": 24.0, "trunk": 16.0, "primary": 12.0,
    "secondary": 9.0, "tertiary": 7.0, "residential": 6.0,
    "service": 3.5, "footway": 2.5,
}

# Metres of kerb either side. Town streets in the vanilla game sit in a band of
# pale concrete; without it the asphalt runs straight into grass and every road
# looks like it was dropped on the landscape rather than built into it.
SIDEWALK_M = {
    "road_major": 2.5,
    "road_medium": 3.5,
    "road_minor": 3.0,
}
# Of that, the strip of grass between the kerb and the pavement on a
# residential street - Knox County's streets run kerb, verge, pavement, lawn.
# In a built-up block the verge is paved over with the rest of the ground.
VERGE_M = {
    "road_medium": 1.5,
    "road_minor": 1.5,
}
SIDEWALK_BY_HIERARCHY_M = {
    "motorway": 0.0, "trunk": 1.5, "primary": 2.5,
    "secondary": 2.5, "tertiary": 2.5, "residential": 2.5,
    "service": 0.5,
}
VERGE_BY_HIERARCHY_M = {
    "motorway": 0.0, "trunk": 0.0, "primary": 0.0,
    "secondary": 0.5, "tertiary": 1.0, "residential": 1.5,
    "service": 0.0,
}


def _sidewalk_width_m(feat: OSMFeature, cat: str) -> float:
    tags = feat.tags
    both = tags.get("sidewalk:both", tags.get("sidewalk", ""))
    if all(tags.get(f"sidewalk:{side}", both) in {"no", "none", "separate"}
           for side in ("left", "right")):
        return 0.0
    return SIDEWALK_BY_HIERARCHY_M.get(road_hierarchy(feat.tags),
                                      SIDEWALK_M.get(cat, 0.0))


def _verge_width_m(feat: OSMFeature, cat: str) -> float:
    return VERGE_BY_HIERARCHY_M.get(road_hierarchy(feat.tags),
                                    VERGE_M.get(cat, 0.0))


def _way_width_m(feat: OSMFeature, cat: str) -> float:
    """Carriageway width for this way, from its own tags where it has them."""
    # Strict on purpose: a category with no entry is a mistake in the caller,
    # and a silent default would paint it a lane wide without a word. Every
    # category that reaches here has an entry in the table above.
    base = ROAD_WIDTHS_BY_HIERARCHY_M.get(road_hierarchy(feat.tags),
                                         ROAD_WIDTHS_M[cat])
    raw = feat.tags.get("width") or feat.tags.get("est_width")
    if raw:
        # OSM widths are metres unless suffixed; "7", "7 m" and "7.5" all occur.
        try:
            given = float(str(raw).split()[0].replace(",", "."))
            # "nan" is a number to float(), and min(30.0, nan) is 30.0: a road
            # tagged width=nan came out thirty metres wide.
            if math.isfinite(given):
                return max(2.0, min(MAX_TAGGED_WIDTH_M.get(cat, 30.0), given))
        except (ValueError, IndexError):      # IndexError: a width of " "
            pass
    lanes = feat.tags.get("lanes")
    if lanes:
        try:
            n = max(1, min(8, int(str(lanes).split(";")[0])))
        except ValueError:
            n = 0
        if n:
            # 3.2 m a lane, plus a little for the shoulder and markings.
            width = n * 3.2 + 1.0
            if feat.tags.get("oneway") == "yes":
                width = max(width, 3.5)
            return width
    return base


def _road_markings(feat: OSMFeature, cat: str) -> list[tuple[str, float]]:
    """(color, offset in metres) for lane markings across a road centerline."""
    # A runway has one marking and it is not a lane divider: the dashed white
    # line down the middle that the game's own airfield has. Lane counting
    # would otherwise put seven stripes across thirty metres of concrete.
    if cat == "runway":
        return [("white", 0.0)]
    # A taxiway carries one yellow line down the centre - that is what the
    # colour means on an airfield, and what tells a taxiway from the runway
    # it leads to when both are the same grey.
    if cat == "taxiway":
        return [("yellow", 0.0)]
    width = _way_width_m(feat, cat)
    if any(str(feat.tags.get(key, "")).lower() == "no"
           for key in ("centreline", "centerline", "road_marking")):
        return []
    raw_lanes = str(feat.tags.get("lanes") or "").split(";")[0].strip()
    try:
        lanes = max(1, min(8, int(float(raw_lanes)))) if raw_lanes else max(
            1, min(8, int(round(width / 3.2))))
    except ValueError:
        lanes = max(1, min(8, int(round(width / 3.2))))
    if lanes < 2:
        return []

    oneway = (str(feat.tags.get("oneway") or "").lower() in ("yes", "1", "-1")
              or feat.tags.get("junction") == "roundabout")
    lane_width = width / lanes
    if oneway:
        return [("white", -width / 2 + lane_width * lane)
                for lane in range(1, lanes)]

    markings = [("yellow", 0.0)]
    lanes_per_direction = lanes // 2
    if lanes >= 4:
        for lane in range(1, lanes_per_direction):
            offset = lane_width * lane
            markings.extend((("white", -offset), ("white", offset)))
    return markings
