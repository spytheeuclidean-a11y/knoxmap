"""Hand-drawn map features, in the shape OpenStreetMap's come in.

A town that is not on OpenStreetMap - one that was never surveyed, one behind
a licence, or one that only exists in somebody's head - cannot be downloaded.
This lets it be drawn instead: a street here, a river there, a row of
buildings, and the rest of KnoxMap treats them exactly as it treats the real
thing.

Nothing downstream knows the difference, and that is the point. A drawn
feature is an `OSMFeature` with real OpenStreetMap tags on it, so `classify`
sorts it, the renderer paints it, the building generator furnishes it and the
compiler writes it, with no second path through any of them. Draw a
`highway=residential` and it gets a residential street's width, its pavement,
its kerb, its lamps and its parked cars, because it *is* one as far as every
later step can tell.

The ids are negative and count downwards, which is the convention OSM's own
editors use for something not yet uploaded: a drawn feature can never collide
with a real one, and anything that logs an id says plainly which it was.
"""
from __future__ import annotations

from .osm import OSMFeature, classify

# What can be drawn, as (id, label, geometry, tags).
#
# `geometry` is "line", "area" or "point" - what the window lets you draw for
# it. The tags are real OpenStreetMap tags, chosen so `classify` sorts each
# one into the category named in the comment; tests/test_sketch.py checks
# every row of this table against `classify` rather than trusting the comment,
# because a tag that classifies as None is drawn on the page and then silently
# missing from the map.
PALETTE: list[tuple[str, str, str, dict]] = [
    # --- roads, biggest first ------------------------------------------
    ("motorway", "Motorway", "line", {"highway": "motorway"}),
    ("primary", "Main road", "line", {"highway": "primary"}),
    ("secondary", "Through road", "line", {"highway": "secondary"}),
    ("residential", "Street", "line", {"highway": "residential"}),
    ("service", "Alley or drive", "line", {"highway": "service"}),
    ("footpath", "Footpath", "line", {"highway": "footway"}),
    ("track", "Dirt track", "line", {"highway": "track"}),
    ("railway", "Railway", "line", {"railway": "rail"}),

    # --- water -----------------------------------------------------------
    ("river", "River", "line", {"waterway": "river"}),
    ("stream", "Stream", "line", {"waterway": "stream"}),
    ("water", "Lake or pond", "area", {"natural": "water"}),
    ("coastline", "Coastline", "line", {"natural": "coastline"}),

    # --- ground ----------------------------------------------------------
    ("forest", "Woods", "area", {"natural": "wood"}),
    ("scrub", "Scrub", "area", {"natural": "scrub"}),
    ("grass", "Grass", "area", {"landuse": "grass"}),
    ("park", "Park", "area", {"leisure": "park"}),
    ("farmland", "Farmland", "area", {"landuse": "farmland"}),
    ("sand", "Sand", "area", {"natural": "sand"}),
    ("parking", "Car park", "area", {"amenity": "parking"}),
    ("cemetery", "Graveyard", "area", {"landuse": "cemetery"}),
    ("pitch", "Sports pitch", "area", {"leisure": "pitch"}),
    ("playground", "Playground", "area", {"leisure": "playground"}),
    ("industrial_land", "Industrial estate", "area", {"landuse": "industrial"}),

    # --- buildings -------------------------------------------------------
    # The kind is what decides the rooms inside, so a drawn block of flats is
    # furnished as flats and a drawn school as a school.
    ("house", "House", "area", {"building": "house"}),
    ("apartments", "Block of flats", "area", {"building": "apartments"}),
    ("shop", "Shop", "area", {"building": "retail", "shop": "yes"}),
    ("school", "School", "area", {"building": "school", "amenity": "school"}),
    ("church", "Church", "area", {"building": "church", "amenity": "place_of_worship"}),
    ("hospital", "Clinic", "area", {"building": "hospital", "amenity": "clinic"}),
    ("warehouse", "Warehouse", "area", {"building": "industrial"}),
    ("shed", "Shed", "area", {"building": "shed"}),

    # --- lines round things ----------------------------------------------
    ("fence", "Fence", "line", {"barrier": "fence"}),
    ("hedge", "Hedge", "line", {"barrier": "hedge"}),

    # --- single things ---------------------------------------------------
    ("tree", "Tree", "point", {"natural": "tree"}),
]

BY_ID = {entry[0]: entry for entry in PALETTE}

# Tags the window may set on a feature of its own accord, on top of its
# palette entry's. Anything else sent is dropped: the tags reach `classify`
# and the renderer, and a page should not be able to post arbitrary ones.
EXTRA_TAGS = {
    "building:levels",   # how many storeys a drawn building has
    "name",              # what it is called, which reaches the paper map
    "width",             # metres across, for a road drawn wider than its class
    "bridge",            # a road or railway over the water below it
    "tunnel",
    "oneway",
    "layer",
}


def palette() -> list[dict]:
    """The table above as the window wants it."""
    return [{"id": i, "label": label, "geometry": geom, "tags": dict(tags)}
            for i, label, geom, tags in PALETTE]


def _ring_is_closed(points: list) -> bool:
    return len(points) > 2 and points[0] == points[-1]


def _tags_for(entry_id: str, extra: dict | None) -> dict | None:
    entry = BY_ID.get(str(entry_id))
    if entry is None:
        return None
    tags = dict(entry[3])
    for key, value in (extra or {}).items():
        if key in EXTRA_TAGS and value not in (None, ""):
            tags[str(key)] = str(value)
    return tags


def features(drawn: dict | list | None) -> list[OSMFeature]:
    """Drawn shapes as OSM features, ready to go in beside downloaded ones.

    `drawn` is a GeoJSON FeatureCollection whose every feature carries a
    "kind" property naming a row of PALETTE. Coordinates are GeoJSON's
    (lon, lat); OSMFeature holds (lat, lon), as Overpass gives them.

    Anything unrecognised is left out rather than guessed at: a shape with no
    kind, a kind that is not in the palette, a line of one point, an area of
    two. They cannot be drawn through the window, but a hand-edited file or an
    older release's save can hold them.
    """
    if isinstance(drawn, dict):
        items = drawn.get("features") or []
    else:
        items = drawn or []
    out: list[OSMFeature] = []
    next_id = -1
    for item in items:
        if not isinstance(item, dict):
            continue
        props = item.get("properties") or {}
        geom = item.get("geometry") or {}
        tags = _tags_for(props.get("kind"), props.get("tags"))
        if tags is None:
            continue
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
            points = [(float(coords[1]), float(coords[0]))]
            kind = "node"
        elif gtype == "LineString" and isinstance(coords, list):
            points = [(float(lat), float(lon)) for lon, lat in coords
                      if isinstance(lon, (int, float)) and isinstance(lat, (int, float))]
            kind = "way"
            if len(points) < 2:
                continue
        elif gtype == "Polygon" and coords:
            ring = coords[0] or []
            points = [(float(lat), float(lon)) for lon, lat in ring
                      if isinstance(lon, (int, float)) and isinstance(lat, (int, float))]
            # A closed way is what makes an area an area, here and in OSM.
            if len(points) < 3:
                continue
            if not _ring_is_closed(points):
                points.append(points[0])
            kind = "way"
        else:
            continue
        out.append(OSMFeature(next_id, kind, tags, points))
        next_id -= 1
    return out


def category_of(entry_id: str) -> str | None:
    """What the renderer will make of this palette entry, or None if nothing.

    The area flag matters: the same tags on a line and on a closed way are not
    always the same feature, so this asks the way the drawn one will be asked.
    """
    entry = BY_ID.get(str(entry_id))
    if entry is None:
        return None
    _i, _label, geom, tags = entry
    if "building" in tags:
        return "building"
    return classify(tags, area=geom == "area")
