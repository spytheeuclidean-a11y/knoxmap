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

import math

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
    ("pedestrian", "Pedestrian street", "line", {"highway": "pedestrian"}),

    # --- water -----------------------------------------------------------
    ("river", "River", "line", {"waterway": "river"}),
    ("stream", "Stream", "line", {"waterway": "stream"}),
    ("water", "Lake or pond", "area", {"natural": "water"}),
    ("canal", "Canal", "line", {"waterway": "canal"}),
    ("coastline", "Coastline", "line", {"natural": "coastline"}),
    ("pool", "Swimming pool", "area", {"leisure": "swimming_pool"}),

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
    ("orchard", "Orchard", "area", {"landuse": "orchard"}),
    ("wetland", "Marsh", "area", {"natural": "wetland"}),
    ("plaza", "Square", "area", {"place": "square"}),
    ("sports", "Sports ground", "area", {"leisure": "sports_centre"}),
    # Land that is given over to something, rather than built on directly.
    # It decides what the generator makes of the untagged buildings on it.
    ("houses_land", "Housing estate", "area", {"landuse": "residential"}),
    ("commercial_land", "Shopping district", "area", {"landuse": "commercial"}),
    ("industrial_land", "Industrial estate", "area", {"landuse": "industrial"}),
    ("military_land", "Army base", "area", {"landuse": "military"}),
    ("schoolyard", "School grounds", "area", {"amenity": "school"}),

    # --- buildings -------------------------------------------------------
    # The kind is what decides the rooms inside, so a drawn block of flats is
    # furnished as flats and a drawn school as a school.
    ("house", "House", "area", {"building": "house"}),
    ("apartments", "Block of flats", "area", {"building": "apartments"}),
    ("shop", "Shop", "area", {"building": "retail", "shop": "yes"}),
    ("school", "School", "area", {"building": "school", "amenity": "school"}),
    ("church", "Church", "area", {"building": "church", "amenity": "place_of_worship"}),
    ("hospital", "Clinic", "area", {"building": "hospital", "amenity": "clinic"}),
    ("supermarket", "Supermarket", "area",
     {"building": "retail", "shop": "supermarket"}),
    ("mall", "Shopping centre", "area", {"building": "retail", "shop": "mall"}),
    ("cafe", "Cafe", "area", {"building": "yes", "amenity": "cafe"}),
    ("restaurant", "Restaurant", "area",
     {"building": "yes", "amenity": "restaurant"}),
    ("pub", "Pub", "area", {"building": "yes", "amenity": "pub"}),
    ("hotel", "Hotel", "area", {"building": "hotel", "tourism": "hotel"}),
    ("garage", "Garage", "area", {"building": "yes", "shop": "car_repair"}),
    ("police", "Police station", "area",
     {"building": "yes", "amenity": "police"}),
    ("fire", "Fire station", "area",
     {"building": "yes", "amenity": "fire_station"}),
    ("library", "Library", "area", {"building": "yes", "amenity": "library"}),
    ("townhall", "Town hall", "area",
     {"building": "civic", "amenity": "townhall"}),
    ("bank", "Bank", "area", {"building": "yes", "amenity": "bank"}),
    ("barracks", "Barracks", "area",
     {"building": "yes", "military": "barracks"}),
    ("stadium", "Stadium", "area", {"building": "yes", "leisure": "stadium"}),
    ("castle", "Castle", "area", {"building": "castle"}),
    ("warehouse", "Warehouse", "area", {"building": "industrial"}),
    ("barn", "Barn", "area", {"building": "barn"}),
    ("shed", "Shed", "area", {"building": "shed"}),

    # --- lines round things ----------------------------------------------
    ("fence", "Fence", "line", {"barrier": "fence"}),
    ("hedge", "Hedge", "line", {"barrier": "hedge"}),
    ("pier", "Pier", "line", {"man_made": "pier"}),

    # --- single things ---------------------------------------------------
    ("tree", "Tree", "point", {"natural": "tree"}),
    # A point, not an outline: the forecourt and its pumps are laid out round
    # a petrol station mapped as a node (knoxbuild/build.py, place_pumps), and
    # an outline tagged this way is only a building the generator cannot place
    # pumps against.
    ("fuel", "Petrol station", "point", {"amenity": "fuel"}),
]

BY_ID = {entry[0]: entry for entry in PALETTE}

# The same order, under the headings the window puts them under: thirty-four
# tools in one list is a wall to read, and nobody looking for "Hedge" scans
# past "Motorway" to find it. The order inside each group is the order above.
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Roads and rails", ("motorway", "primary", "secondary", "residential",
                         "service", "pedestrian", "footpath", "track",
                         "railway")),
    ("Water", ("river", "stream", "canal", "water", "pool", "coastline")),
    ("Ground", ("forest", "scrub", "grass", "park", "farmland", "orchard",
                "sand", "wetland", "parking", "cemetery", "pitch",
                "playground", "plaza", "sports")),
    ("What the land is for", ("houses_land", "commercial_land",
                              "industrial_land", "military_land",
                              "schoolyard")),
    ("Homes and shops", ("house", "apartments", "hotel", "shop", "supermarket",
                         "mall", "cafe", "restaurant", "pub", "garage")),
    ("Public buildings", ("school", "church", "hospital", "police", "fire",
                          "library", "townhall", "bank", "barracks",
                          "stadium", "castle")),
    ("Works and farm", ("warehouse", "barn", "shed")),
    ("Edges and odds", ("fence", "hedge", "pier", "tree", "fuel")),
]
GROUP_OF = {entry_id: name for name, ids in GROUPS for entry_id in ids}

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
    # In group order, not in the order of the table above: the window draws a
    # heading wherever the group changes, and the table grew by having new
    # tools dropped in beside their like, so "Public buildings" came out as
    # two headings with a gap of shops between them.
    out = []
    for name, ids in GROUPS:
        for entry_id in ids:
            i, label, geom, tags = BY_ID[entry_id]
            out.append({"id": i, "label": label, "geometry": geom,
                        "tags": dict(tags), "group": name})
    return out


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


def _listed(value) -> list:
    """A list of whatever was sent, or nothing. A cleaner never throws: this
    reads what the window posts and what is on disk, and a number where a
    list was expected used to come back as a Python TypeError."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _table(value) -> dict:
    return value if isinstance(value, dict) else {}


def _lat_lons(coords) -> list[tuple[float, float]]:
    """GeoJSON (lon, lat) pairs as (lat, lon), skipping whatever is not a
    pair of numbers: a hand-edited file can hold [null] where a point was."""
    out = []
    for point in _listed(coords):
        if (isinstance(point, (list, tuple)) and len(point) >= 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
                and not isinstance(point[0], bool)
                and not isinstance(point[1], bool)):
            out.append((float(point[1]), float(point[0])))
    return out


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
    items = (_listed(drawn.get("features")) if isinstance(drawn, dict)
             else _listed(drawn))
    out: list[OSMFeature] = []
    next_id = -1
    for item in items:
        if not isinstance(item, dict):
            continue
        props = _table(item.get("properties"))
        geom = _table(item.get("geometry"))
        tags = _tags_for(props.get("kind"), props.get("tags"))
        if tags is None:
            continue
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Point":
            points = _lat_lons([coords])
            if not points:
                continue
            kind = "node"
        elif gtype == "LineString" and isinstance(coords, list):
            points = _lat_lons(coords)
            kind = "way"
            if len(points) < 2:
                continue
            # A road drawn back to where it started is a loop of road, not a
            # plot of ground: the renderer fills a closed way as an area.
            if len(points) > 2 and points[0] == points[-1]:
                tags["knox:line"] = "yes"
        elif gtype == "Polygon" and isinstance(coords, list) and coords:
            ring = _listed(coords[0])
            points = _lat_lons(ring)
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


# --- a map drawn from scratch, on a blank sheet ---------------------------
#
# The editor is a drawing board, not the world: what is drawn on it is in
# metres from the bottom-left corner, because that is what a person laying out
# a town thinks in - "the high street is 400 m long" rather than "the high
# street is 0.0036 degrees long". Everything after it works in latitude and
# longitude, so the sheet is pinned to a corner of the world and converted
# here, once, where it can be tested.
#
# Which corner barely matters: a map from scratch is nowhere in particular, and
# the only thing the coordinates decide is the projection the renderer uses and
# where the map lands beside other KnoxMap maps. It is settable all the same,
# for somebody laying their invented town over a real coast.
METRES_PER_DEGREE_LAT = 111320.0
# A sheet has to be big enough to hold a building and small enough to render.
MIN_SHEET_M = 100.0
MAX_SHEET_M = 40000.0
# How far under the asked-for size the sheet is allowed to land, in metres.
# Small enough that nobody could see it, big enough to stay the right side of
# a cell boundary whatever the projection does.
CELL_SLACK_M = 0.2


def _sheet_size(design: dict) -> tuple[float, float]:
    try:
        width = float(design.get("width_m") or 0)
        height = float(design.get("height_m") or 0)
    except (TypeError, ValueError):
        width = height = 0.0
    # float("NaN") is a number to Python and nothing to anybody else: it goes
    # through min() and max() untouched and comes out as "cannot convert
    # float NaN to integer" four steps later, in the renderer.
    if not math.isfinite(width) or not math.isfinite(height):
        width = height = 0.0
    width = min(max(width or 1000.0, MIN_SHEET_M), MAX_SHEET_M)
    height = min(max(height or 1000.0, MIN_SHEET_M), MAX_SHEET_M)
    return width, height


def _anchor(design: dict) -> tuple[float, float]:
    """The south-west corner of the sheet, in the world."""
    spot = _table(design.get("anchor"))
    try:
        lat = float(spot.get("lat"))
        lon = float(spot.get("lon"))
    except (TypeError, ValueError):
        return 0.0, 0.0
    # Far enough from the poles that a degree of longitude is still a usable
    # distance, and inside the world at all.
    if not (-80.0 <= lat <= 80.0) or not (-180.0 <= lon <= 180.0):
        return 0.0, 0.0
    return lat, lon


def _utm_extent(south: float, west: float, north: float, east: float):
    """How wide and tall the renderer will measure this box, in metres.

    The renderer projects the four corners into the UTM zone the box sits in
    and takes the spread (generator/rendering/projection.py, Projector.build). Asking the
    same question the same way is the only way to hand it a sheet that comes
    out the size it was drawn at.
    """
    import pyproj

    lon_c, lat_c = (west + east) / 2, (south + north) / 2
    zone = int((lon_c + 180) / 6) + 1
    epsg = (32600 if lat_c >= 0 else 32700) + zone
    t = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    corners = [(west, south), (east, south), (east, north), (west, north)]
    xs, ys = zip(*(t.transform(lo, la) for lo, la in corners))
    return max(xs) - min(xs), max(ys) - min(ys)


def design_bbox(design: dict) -> tuple[float, float, float, float]:
    """(south, west, north, east) of the sheet, as the generator wants it.

    A flat degrees-per-metre guess is about 1% out, which sounds harmless and
    is not: the map is rounded up to whole 300-tile cells, so a 900 m sheet
    measured as 909 m becomes 1200 tiles instead of 900 - half as much map
    again, from a 9 m error. The guess is made, measured the way the renderer
    will measure it, and corrected; twice over is enough to be exact to the
    metre anywhere a map can be drawn.
    """
    design = _table(design)
    width, height = _sheet_size(design)
    lat, lon = _anchor(design)
    d_lat = height / METRES_PER_DEGREE_LAT
    mid = math.radians(lat + d_lat / 2)
    d_lon = width / (METRES_PER_DEGREE_LAT * max(math.cos(mid), 1e-6))
    for _pass in range(4):
        got_w, got_h = _utm_extent(lat, lon, lat + d_lat, lon + d_lon)
        if got_w <= 0 or got_h <= 0:
            break
        if width - CELL_SLACK_M <= got_w <= width                 and height - CELL_SLACK_M <= got_h <= height:
            break
        # Aimed a hair under rather than at it. The map is rounded up to whole
        # 300-tile cells, so a 900 m sheet that measures 900.04 m is four
        # cells across instead of three - a third more map, from 4 cm. Landing
        # just short costs nothing: the rounding puts it back.
        d_lon *= (width - CELL_SLACK_M / 2) / got_w
        d_lat *= (height - CELL_SLACK_M / 2) / got_h
    return lat, lon, lat + d_lat, lon + d_lon


def design_to_drawn(design: dict | None) -> dict:
    """A sheet of metres as the GeoJSON the rest of the drawing code takes.

    Points are (x, y) in metres from the bottom-left corner, x east and y
    north, which is the way a drawing board runs and the opposite of the way
    a screen does - the editor flips it, not this.
    """
    design = design if isinstance(design, dict) else {}
    width, height = _sheet_size(design)
    south, west, north, east = design_bbox(design)

    def to_lonlat(point):
        # By proportion of the sheet rather than by metres again: the box was
        # already fitted to the sheet, so a thing at the right-hand edge lands
        # on the right-hand edge and the two cannot disagree.
        x, y = float(point[0]), float(point[1])
        return [west + (east - west) * (x / width),
                south + (north - south) * (y / height)]

    out = []
    for item in _listed(design.get("features")):
        if not isinstance(item, dict):
            continue
        entry = BY_ID.get(str(item.get("kind")))
        if entry is None:
            continue
        points = _listed(item.get("points"))
        try:
            ring = [to_lonlat(p) for p in points]
        except (TypeError, ValueError, IndexError):
            continue
        geometry = entry[2]
        if geometry == "point":
            if not ring:
                continue
            shape = {"type": "Point", "coordinates": ring[0]}
        elif geometry == "area":
            if len(ring) < 3:
                continue
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            shape = {"type": "Polygon", "coordinates": [ring]}
        else:
            if len(ring) < 2:
                continue
            shape = {"type": "LineString", "coordinates": ring}
        props = {"kind": entry[0]}
        if isinstance(item.get("tags"), dict):
            props["tags"] = item["tags"]
        out.append({"type": "Feature", "properties": props, "geometry": shape})
    return {"type": "FeatureCollection", "features": out}
