"""Buildings from the OSM data: the tags that make one, houses invented from address points, and the buildings GeoJSON."""
from __future__ import annotations

from ..osm import OSMFeature, classify
from .geometry import _feature_coords_px, _is_polygon
from .projection import Projector
from .widths import _way_width_m


# What survives into the geojson knoxbuild reads. amenity/shop/leisure carry
# what a building actually is far more reliably than the building tag alone,
# and they pick its materials and room plan.
#
# building:levels earns its place twice over: it is the only thing in OSM that
# says how tall a building is, and dropping it meant every block of flats in a
# town was rebuilt as a bungalow no matter what the mapper had recorded.
# Houses where the map has an address but no building.
#
# In whole countries - and in most American suburbs - the houses are not drawn
# at all; what the survey left behind is one node per home carrying
# addr:housenumber. Those streets came out as roads through empty grass. A
# node with an address on it is a building by definition, so one of a
# household's size is put there, upright on the grid; the rest of the build
# treats it like any other footprint, so it is skipped if a real building
# already covers the spot and it moves off the road like the others do.
#
# Except where the numbers are the ends of an address interpolation: a line
# along the street tagged addr:interpolation, whose end nodes say "2" and
# "48" for every home between. Those two points are the ends of a range, not
# two houses, and they stand at a corner or in the gap between real houses,
# so a house made from them was wedged in among the ones Overture filled in.
ADDRESS_HOUSE_M = (9.0, 11.0)    # frontage, depth: a small detached house
ADDRESS_CLEAR_M = 4.0            # keep this far off a mapped building
ADDRESS_APART_M = 7.0            # and this far from the next address point
MAX_ADDRESS_HOUSES = 40000
# How far the near wall of the house stands back from the edge of the road.
#
# An address is a point on a street, and mappers put it anywhere from the
# doorstep to the middle of the carriageway. A house dropped where the point
# is therefore sat on the road often enough to read as roads going missing.
# Each one is pushed away from the nearest road until it is clear of it, and
# dropped if it cannot be.
ADDRESS_SETBACK_M = 2.0
ADDRESS_PUSH_M = 18.0            # as far as a house is moved to get clear
# Every road a house has to stand clear of: the ones with a carriageway. A
# footpath or a drive may run right past the door.
ADDRESS_AVOIDS_ROADS = {"road_major", "road_medium", "road_minor", "road_service",
                        "pedestrian"}


def _off_the_road(x: float, y: float, need: float, roads, road_half,
                  road_tree, push_limit: float, max_road_half: float | None = None):
    """Move a point away from the road nearest it until the house round it
    clears the carriageway. None when it cannot be cleared."""
    from shapely.geometry import Point

    if max_road_half is None:
        max_road_half = max(road_half, default=0.0)
    reach = need + max_road_half
    for _ in range(6):
        here = Point(x, y)
        worst, gap = None, 0.0
        for i in road_tree.query(here, predicate="dwithin", distance=reach):
            i = int(i)
            short = need + road_half[i] - roads[i].distance(here)
            if short > gap:
                worst, gap = i, short
        if worst is None:
            return x, y
        # Straight away from the road it is closest to.
        near = roads[worst].interpolate(roads[worst].project(here))
        dx, dy = x - near.x, y - near.y
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return None                  # on the centre line; no way to know
        step = gap + 0.5
        if step > push_limit:
            return None
        x += dx / length * step
        y += dy / length * step
        push_limit -= step
        if push_limit <= 0:
            return None
    return None


def _houses_from_addresses(feats: list["OSMFeature"], buildings: list["OSMFeature"],
                           proj: "Projector") -> list["OSMFeature"]:
    """A house-sized footprint for every address that has no building."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.strtree import STRtree

    # Overpass gives an interpolation line the same coordinates as its nodes,
    # so a node is found on one by where it is.
    ranges = {tuple(p) for f in feats
              if f.kind == "way" and f.tags.get("addr:interpolation")
              for p in f.geometry}
    points = [f for f in feats
              if f.kind == "node" and f.geometry and f.tags.get("addr:housenumber")
              and not f.tags.get("building") and tuple(f.geometry[0]) not in ranges]
    if not points:
        return []
    shapes = []
    for f in buildings:
        rings = _feature_coords_px(f, proj)
        for ring in rings:
            if len(ring) >= 3:
                poly = Polygon(ring)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    shapes.append(poly)
    tree = STRtree(shapes) if shapes else None
    # The roads themselves, each as a band of its own width, so a house can
    # be pushed off the one it belongs to.
    roads, road_half = [], []
    for f in feats:
        cat = classify(f.tags, _is_polygon(f))
        if cat not in ADDRESS_AVOIDS_ROADS:
            continue
        for ring in _feature_coords_px(f, proj):
            if len(ring) >= 2:
                roads.append(LineString(ring))
                road_half.append(_way_width_m(f, cat) / proj.meters_per_tile / 2)
    road_tree = STRtree(roads) if roads else None
    max_road_half = max(road_half, default=0.0)
    setback = ADDRESS_SETBACK_M / proj.meters_per_tile
    push_limit = ADDRESS_PUSH_M / proj.meters_per_tile
    clear = ADDRESS_CLEAR_M / proj.meters_per_tile
    apart = ADDRESS_APART_M / proj.meters_per_tile
    half_w = (ADDRESS_HOUSE_M[0] / proj.meters_per_tile) / 2
    half_h = (ADDRESS_HOUSE_M[1] / proj.meters_per_tile) / 2
    taken: dict[tuple[int, int], list] = {}
    cell = max(1.0, apart)
    made = []
    for f in points:
        if len(made) >= MAX_ADDRESS_HOUSES:
            break
        lat, lon = f.geometry[0]
        x, y = proj.to_px(lat, lon)
        if not (-half_w <= x < proj.width + half_w and -half_h <= y < proj.height + half_h):
            continue
        here = Point(x, y)
        if tree is not None and len(tree.query(here, predicate="dwithin", distance=clear)) > 0:
            continue
        if road_tree is not None:
            spot = _off_the_road(x, y, max(half_w, half_h) + setback,
                                 roads, road_half, road_tree, push_limit,
                                 max_road_half=max_road_half)
            if spot is None:
                continue                 # nowhere off the road to put it
            if (x, y) != spot:
                x, y = spot
                here = Point(x, y)
                if tree is not None and len(tree.query(here, predicate="dwithin", distance=clear)) > 0:
                    continue
        key = (int(x // cell), int(y // cell))
        crowd = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                 for p in taken.get((key[0] + dx, key[1] + dy), ())]
        if any(abs(px - x) < apart and abs(py - y) < apart for px, py in crowd):
            continue
        taken.setdefault(key, []).append((x, y))
        ring = [(x - half_w, y - half_h), (x + half_w, y - half_h),
                (x + half_w, y + half_h), (x - half_w, y + half_h),
                (x - half_w, y - half_h)]
        tags = {k: v for k, v in f.tags.items() if k in BUILDING_TAGS}
        tags.setdefault("building", "house")
        made.append(OSMFeature(osm_id=f.osm_id, kind="way", tags=tags,
                               geometry=[proj.to_latlon(px, py) for px, py in ring]))
    return made


BUILDING_TAGS = {
    "building", "building:levels", "building:part", "building:material",
    "building:use", "height", "levels", "roof:levels", "roof:shape",
    "name", "addr:housenumber", "addr:street", "addr:flats",
    "amenity", "shop", "leisure", "tourism", "industrial",
    "healthcare", "office", "craft", "man_made", "residential", "cuisine",
    # What tells a drive-in from any other cinema: knoxbuild/landmarks.py puts
    # its board up by the road only when this says so.
    "drive_in",
}


def _buildings_geojson(feats: list[OSMFeature],
                       indoor: list[OSMFeature] = ()) -> dict:
    """Export building footprints so the user knows where to drop .tbx lots.

    Ways tagged indoor=room are attached to the building they stand in, as
    a "rooms" property: the mapper's own interior walls, which knoxbuild
    cuts the ground floor along instead of guessing at it
    (knoxbuild/build.py, knoxbuild/layout._mapped_rooms).
    """
    from shapely.geometry import MultiPolygon, Polygon

    features = []
    polys = []        # each building's shape, only built when rooms must fit
    for f in feats:
        if f.kind == "way":
            coords = [[lon, lat] for lat, lon in f.geometry]
            if len(coords) >= 3:
                features.append({
                    "type": "Feature",
                    # amenity/shop/leisure carry what a building actually is
                    # far more reliably than the building tag alone, and
                    # knoxbuild uses them to pick materials and room plans.
                    "properties": {**{k: v for k, v in f.tags.items()
                                      if k in BUILDING_TAGS},
                                   "osm_id": f.osm_id},
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                })
                if indoor:
                    g = Polygon(coords)
                    polys.append(g if g.is_valid else g.buffer(0))
        elif f.kind == "relation":
            rings = []
            for role, ring in f.role_geoms:
                if role == "inner":
                    continue
                coords = [[lon, lat] for lat, lon in ring]
                if len(coords) >= 3:
                    rings.append(coords)
            if rings:
                features.append({
                    "type": "Feature",
                    "properties": {**{k: v for k, v in f.tags.items()
                                      if k in BUILDING_TAGS},
                                   "osm_id": f.osm_id},
                    "geometry": {"type": "MultiPolygon", "coordinates":
                                 [[r] for r in rings]},
                })
                if indoor:
                    g = MultiPolygon([Polygon(r) for r in rings])
                    polys.append(g if g.is_valid else g.buffer(0))
    if indoor and features:
        import numpy as np
        # One representative point per room, against the bounding boxes of all
        # buildings first: a city can hold thousands of each, and only the
        # handful of buildings whose box holds the point are asked properly.
        boxes = np.array([g.bounds for g in polys])
        for f in indoor:
            if len(f.geometry) < 3:
                continue
            ring = [[lon, lat] for lat, lon in f.geometry]
            room = Polygon(ring)
            if not room.is_valid:
                room = room.buffer(0)
            if room.is_empty:
                continue
            p = room.representative_point()
            near = np.flatnonzero((boxes[:, 0] <= p.x) & (p.x <= boxes[:, 2])
                                  & (boxes[:, 1] <= p.y) & (p.y <= boxes[:, 3]))
            for i in near.tolist():
                if polys[i].contains(p):
                    features[i]["properties"].setdefault("rooms", []).append(
                        {"ring": ring,
                         "room": f.tags.get("room"),
                         "amenity": f.tags.get("amenity")})
                    break
    return {"type": "FeatureCollection", "features": features}
