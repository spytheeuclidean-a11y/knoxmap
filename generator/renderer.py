"""Rasterize OSM features into Project Zomboid bitmaps.

Output contract (per the Mapping Guide):
  <name>.bmp              — landscape (11 palette colors)
  <name>_veg.bmp          — vegetation (must be same size as landscape)
  <name>_ZombieSpawnMap.bmp — grayscale, 1/10th resolution

Dimensions are snapped up to the next multiple of 300 (PZ cell size). The
requested real-world bbox is expanded symmetrically to fit that grid so the
meters-per-tile scale stays consistent.
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from typing import Iterable

import pyproj
from PIL import Image, ImageDraw, ImageFilter

from . import pz_colors as C
from .osm import FENCE_BARRIERS, OSMFeature, classify


# --- projection ------------------------------------------------------------

@dataclass
class Projector:
    """Latitude/longitude → pixel coordinate in the output bitmap.

    Uses the UTM zone covering the bbox center so distance in meters maps
    nearly linearly to pixels. The projected bbox is expanded up to the next
    300-tile cell multiple.
    """
    south: float
    west: float
    north: float
    east: float
    meters_per_tile: float
    width: int   # pixels (tile count)
    height: int  # pixels
    min_x_m: float
    min_y_m: float
    _transformer: pyproj.Transformer
    # Degrees the map is turned, counter-clockwise, so its main street grid
    # runs along the tile grid. See dominant_road_angle.
    rotation: float = 0.0

    @classmethod
    def build(cls, south: float, west: float, north: float, east: float,
              meters_per_tile: float, rotation: float = 0.0) -> "Projector":
        lon_c = (west + east) / 2
        lat_c = (south + north) / 2
        utm_zone = int((lon_c + 180) / 6) + 1
        epsg = (32600 if lat_c >= 0 else 32700) + utm_zone
        t = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}",
                                        always_xy=True)
        # Project the four corners so we pick up any distortion at the edges.
        corners = [(west, south), (east, south), (east, north), (west, north)]
        xs, ys = zip(*(t.transform(lo, la) for lo, la in corners))
        raw_w = max(xs) - min(xs)
        raw_h = max(ys) - min(ys)
        tiles_w = max(C.CELL_SIZE, _ceil_to(raw_w / meters_per_tile, C.CELL_SIZE))
        tiles_h = max(C.CELL_SIZE, _ceil_to(raw_h / meters_per_tile, C.CELL_SIZE))
        # Re-center: expand bbox in meters to match the rounded-up tile count.
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half_w_m = (tiles_w * meters_per_tile) / 2
        half_h_m = (tiles_h * meters_per_tile) / 2
        return cls(south, west, north, east, meters_per_tile,
                   tiles_w, tiles_h,
                   cx - half_w_m, cy - half_h_m,
                   t, rotation)

    def to_px(self, lat: float, lon: float) -> tuple[float, float]:
        x_m, y_m = self._transformer.transform(lon, lat)
        if self.rotation:
            cx = self.min_x_m + self.width * self.meters_per_tile / 2
            cy = self.min_y_m + self.height * self.meters_per_tile / 2
            a = math.radians(self.rotation)
            dx, dy = x_m - cx, y_m - cy
            x_m = cx + dx * math.cos(a) - dy * math.sin(a)
            y_m = cy + dx * math.sin(a) + dy * math.cos(a)
        px = (x_m - self.min_x_m) / self.meters_per_tile
        # Image Y grows downward; UTM Y grows northward → flip.
        py = self.height - (y_m - self.min_y_m) / self.meters_per_tile
        return px, py

    def latlon_bbox(self) -> tuple[float, float, float, float]:
        """(south, west, north, east) covering the whole map, turned or not."""
        back = pyproj.Transformer.from_crs(self._transformer.target_crs,
                                           "EPSG:4326", always_xy=True)
        w_m = self.width * self.meters_per_tile
        h_m = self.height * self.meters_per_tile
        cx, cy = self.min_x_m + w_m / 2, self.min_y_m + h_m / 2
        a = math.radians(-self.rotation)
        lons, lats = [], []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            dx, dy = sx * w_m / 2, sy * h_m / 2
            lon, lat = back.transform(cx + dx * math.cos(a) - dy * math.sin(a),
                                      cy + dx * math.sin(a) + dy * math.cos(a))
            lons.append(lon)
            lats.append(lat)
        return min(lats), min(lons), max(lats), max(lons)

    def cell_grid(self) -> tuple[int, int]:
        return self.width // C.CELL_SIZE, self.height // C.CELL_SIZE


# Roads that count towards a town's street grid. Paths wander, and a motorway
# slicing through at its own angle should not turn the town around it.
GRID_ROADS = {"road_minor", "road_medium", "road_service"}
# How strongly the streets must agree on a direction before the map is turned
# to it: 1 is a perfect grid, 0 no preference. Measured on test maps, gridded
# towns sit well above this and old organic centres below it.
ALIGN_MIN_STRENGTH = 0.25


# Roads that carry on past the edge of a drawn shape. Cutting every road at the
# line would leave the town an island in a field; the main roads out of it
# stay, the side streets and driveways of places not chosen do not.
THROUGH_ROADS = ("road_major", "road_medium")


def shape_px(shape: dict | None, proj: Projector):
    """A drawn selection (GeoJSON Polygon or MultiPolygon, lon/lat) in tile
    coordinates, or None for a plain rectangle."""
    if not shape:
        return None
    from shapely.geometry import MultiPolygon, Polygon

    polys = shape["coordinates"] if shape.get("type") == "MultiPolygon" else [shape["coordinates"]]
    parts = []
    for rings in polys:
        if not rings or len(rings[0]) < 3:
            continue
        outer = [proj.to_px(lat, lon) for lon, lat in rings[0]]
        holes = [[proj.to_px(lat, lon) for lon, lat in r] for r in rings[1:] if len(r) >= 3]
        poly = Polygon(outer, holes)
        parts.append(poly if poly.is_valid else poly.buffer(0))
    if not parts:
        return None
    merged = parts[0] if len(parts) == 1 else MultiPolygon(
        [g for p in parts for g in (getattr(p, "geoms", None) or [p])])
    return merged if merged.is_valid else merged.buffer(0)


def _inside(feat: OSMFeature, proj: Projector, shape) -> bool:
    """Whether a feature belongs to the drawn shape: its middle is inside."""
    from shapely.geometry import LineString, Point, Polygon

    if feat.kind == "relation":
        rings = [ring for role, ring in feat.role_geoms if role != "inner" and len(ring) >= 3]
        if not rings:
            return False
        geom = Polygon([proj.to_px(la, lo) for la, lo in rings[0]])
        geom = geom if geom.is_valid else geom.buffer(0)
        return not geom.is_empty and shape.contains(geom.representative_point())
    pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
    if not pts:
        return False
    if len(pts) >= 3 and pts[0] == pts[-1]:
        geom = Polygon(pts)
        spot = geom.representative_point() if geom.is_valid else Point(pts[0])
        return shape.contains(spot)
    if len(pts) >= 2:
        return shape.intersects(LineString(pts))
    return shape.contains(Point(pts[0]))


def _clip_to_shape(landscape: Image.Image, shape, buckets: dict[str, list[OSMFeature]],
                   proj: Projector) -> None:
    """Outside the drawn shape, the ground goes back to countryside.

    Water stays - a river does not stop at a line on the map - and so do the
    main roads through it, with their pavements. Everything else outside, the
    yards and car parks and side streets of the neighbourhood next door,
    becomes grass.
    """
    import numpy as np

    w, h = landscape.size
    inside = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(inside)
    for part in getattr(shape, "geoms", None) or [shape]:
        d.polygon(list(part.exterior.coords), fill=255)
        for hole in part.interiors:
            d.polygon(list(hole.coords), fill=0)
    keep = inside.copy()
    kd = ImageDraw.Draw(keep)
    mpt = proj.meters_per_tile
    for cat in THROUGH_ROADS:
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            width = (_way_width_m(feat, cat) + 2 * SIDEWALK_M[cat]) / mpt
            _draw_line(kd, _feature_coords_px(feat, proj), 255, int(width))
    for cat in ("water", "pool", "coastline"):
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                for ring in _feature_coords_px(feat, proj):
                    if len(ring) >= 3:
                        kd.polygon(ring, fill=255)
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        outside = np.asarray(keep.crop((0, y0, w, y1))) == 0
        if not outside.any():
            continue
        ground = np.asarray(landscape.crop((0, y0, w, y1)))
        water = (ground[:, :, 0] == C.WATER[0]) & (ground[:, :, 1] == C.WATER[1]) \
            & (ground[:, :, 2] == C.WATER[2])
        outside &= ~water
        if outside.any():
            grass = Image.new("RGB", (w, y1 - y0), C.DARK_GRASS)
            landscape.paste(grass, (0, y0), Image.fromarray(outside.astype(np.uint8) * 255))


def cover_bbox(south: float, west: float, north: float, east: float,
               meters_per_tile: float) -> tuple[float, float, float, float]:
    """A (south, west, north, east) box holding the map however it is turned.

    The map is a rectangle of whole cells round the selection; turned, it
    sweeps a circle through its corners. The box round that circle holds every
    feature the map could show at any angle, so one download serves both
    measuring the street grid and drawing the turned map.
    """
    proj = Projector.build(south, west, north, east, meters_per_tile)
    w_m = proj.width * meters_per_tile
    h_m = proj.height * meters_per_tile
    cx, cy = proj.min_x_m + w_m / 2, proj.min_y_m + h_m / 2
    r = math.hypot(w_m, h_m) / 2 + 50       # a margin for ways just outside
    back = pyproj.Transformer.from_crs(proj._transformer.target_crs, "EPSG:4326",
                                       always_xy=True)
    lons, lats = zip(*(back.transform(cx + dx, cy + dy)
                       for dx in (-r, r) for dy in (-r, r)))
    return min(lats), min(lons), max(lats), max(lons)


def dominant_road_angle(features: Iterable[OSMFeature], south: float, west: float,
                        north: float, east: float) -> tuple[float, float]:
    """The main direction of a town's streets, and how strongly they share it.

    Tiles are square, so a street at 20 degrees becomes a staircase with a step
    every few tiles - kerbs zigzagging along it and blends failing at every
    corner. Most towns have a grid, even a loose one; turning the whole map so
    that grid runs along the tiles straightens every street on it. Buildings,
    fences and the paper map are projected the same way, so nothing is
    misaligned - only north is no longer straight up.

    Returns (angle, strength): the angle in degrees in (-45, 45], counter-
    clockwise from east, and the strength in [0, 1]. Directions are averaged
    with a 90-degree period, so a north-south street and an east-west one
    agree; each segment weighs by its length.
    """
    proj = Projector.build(south, west, north, east, 1.0)
    sin_sum = cos_sum = total = 0.0
    for feat in features:
        if feat.kind != "way" or classify(feat.tags) not in GRID_ROADS:
            continue
        pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, ay - by      # tile y grows south; flip to north-up
            length = math.hypot(dx, dy)
            if length < 1:
                continue
            a = 4 * math.atan2(dy, dx)
            sin_sum += length * math.sin(a)
            cos_sum += length * math.cos(a)
            total += length
    if total == 0:
        return 0.0, 0.0
    angle = math.degrees(math.atan2(sin_sum, cos_sum) / 4)
    return angle, math.hypot(sin_sum, cos_sum) / total


def _ceil_to(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)


# --- feature painting ------------------------------------------------------

# Paint order for landscape: later categories overwrite earlier ones, so this
# is effectively painted bottom-to-top.
LANDSCAPE_ORDER = [
    # Broad land use first, so anything more specific inside it - a pitch in a
    # schoolyard, a car park on an industrial estate - is painted over it.
    "residential",    # gardens and yards
    "commercial",     # pavement in front of shops
    "industrial",     # gravel yards
    "military",
    "schoolyard",
    "hospital_grounds",
    "worship_grounds",
    "cemetery",
    "orchard",
    "farmland",       # light grass
    "grass",          # medium grass
    "park",           # medium grass w/ trees added by vegetation pass
    "sports",
    "wetland",
    "sand",
    "dirt",
    "playground",
    "track",
    # Water under the ways that cross it: a river polygon painted last erased
    # every bridge, leaving no way over. Above land use, which it still wins.
    "water",
    "pool",
    "railway",        # gravel track bed; roads cross it at level crossings
    "dirt_path",      # thin dirt line
    "paved_path",     # footway, pavement, cycleway
    "pier",           # jetties and breakwaters, over the water
    "parking",        # car park tarmac
    "plaza",          # paved pedestrian square
    "road_service",   # alleys and driveways
    "road_minor",
    "road_medium",
    "road_major",     # widest, so it wins at junctions
    # Building footprints are not painted at all. They used to be dirt, which
    # showed as a brown fringe wherever the placed building and the painted
    # footprint disagreed by a tile - and the building's own floor covers the
    # ground under it anyway.
]

# Waterways drawn from a centre line, when no area is mapped around them.
# A river is usually mapped with its banks too, which paints over this.
WATERWAY_WIDTH_M = {"river": 12.0, "canal": 8.0, "stream": 2.0}

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
    "dirt_path": 2.5,
    "paved_path": 2.5,
    "pier": 3.0,
    "railway": 4.0,
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

LANDSCAPE_FILL = {
    "water": C.WATER,
    "sand": C.SAND,
    "dirt": C.DIRT,
    "dirt_path": C.DIRT,
    "paved_path": C.PALE_CONCRETE,
    "pier": C.PALE_CONCRETE,
    "railway": C.LIGHT_ASPHALT,
    "grass": C.MEDIUM_GRASS,
    "park": C.MEDIUM_GRASS,
    "farmland": C.LIGHT_GRASS,
    # street/street2/street4 in Rules.txt. road_minor used to paint
    # lightgravel, which put a gravel track through the middle of every
    # residential street in town.
    # Service lanes were gravel, which next to slab pavements read as more
    # pavement. Main roads get the worn speckled tarmac so they stand apart
    # from the smooth tarmac of ordinary streets; both blend at the edges.
    "road_service": C.DARKEST_ASPHALT,
    "road_minor": C.MEDIUM_ASPHALT,
    "road_medium": C.MEDIUM_ASPHALT,
    "road_major": C.DARKEST_ASPHALT,
    "parking": C.DARK_ASPHALT,
    "plaza": C.PAVING,
    "residential": C.MEDIUM_GRASS,
    "commercial": C.PALE_CONCRETE,
    "industrial": C.LIGHT_ASPHALT,
    "military": C.DIRT,
    "schoolyard": C.PALE_CONCRETE,
    "hospital_grounds": C.MEDIUM_GRASS,
    "worship_grounds": C.PAVING,
    "cemetery": C.LIGHT_GRASS,
    "orchard": C.MEDIUM_GRASS,
    "sports": C.MEDIUM_GRASS,
    "wetland": C.DARK_GRASS,
    "playground": C.SAND,
    "track": C.CLAY,
    "pool": C.WATER,
}

# Categories knoxbuild needs as areas, to tell what a building standing in
# them probably is: an untagged building on an industrial estate is a works,
# not a house.
AREA_CATEGORIES = {"residential", "commercial", "industrial", "military",
                   "schoolyard", "hospital_grounds", "worship_grounds",
                   "cemetery", "parking", "sports"}
# Drawn onto the vegetation bitmap rather than the ground.
VEG_CATEGORIES = {"forest", "scrub", "tree_single", "hedge", "orchard",
                  "cemetery", "wetland"}


def _way_width_m(feat: OSMFeature, cat: str) -> float:
    """Carriageway width for this way, from its own tags where it has them."""
    base = ROAD_WIDTHS_M[cat]
    raw = feat.tags.get("width") or feat.tags.get("est_width")
    if raw:
        # OSM widths are metres unless suffixed; "7", "7 m" and "7.5" all occur.
        try:
            return max(2.0, min(30.0, float(str(raw).split()[0].replace(",", "."))))
        except ValueError:
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


def _feature_coords_px(feat: OSMFeature, proj: Projector) -> list[list[tuple[float, float]]]:
    """Project every ring/linestring in this feature to pixel space."""
    if feat.kind == "way":
        return [[proj.to_px(la, lo) for la, lo in feat.geometry]]
    if feat.kind == "relation":
        rings: list[list[tuple[float, float]]] = []
        for _role, coords in feat.role_geoms:
            rings.append([proj.to_px(la, lo) for la, lo in coords])
        return rings
    if feat.kind == "node":
        la, lo = feat.geometry[0]
        return [[proj.to_px(la, lo)]]
    return []


def _is_polygon(feat: OSMFeature) -> bool:
    """Treat as polygon if first/last point match (way) or it's a relation."""
    if feat.kind == "relation":
        return True
    if feat.kind == "way" and len(feat.geometry) >= 3:
        return feat.geometry[0] == feat.geometry[-1]
    return False


def _paint_multipolygon(image: Image.Image, feat: OSMFeature, proj: Projector,
                        fill: tuple[int, int, int]) -> None:
    """Fill a relation's outer rings and leave its inner rings as they were.

    An island in a lake or a clearing in a wood is an inner ring. Drawn like
    the outers it was flooded or planted over; here it is cut out of a mask
    the size of the relation, so whatever lies under it shows through.
    """
    rings = [(role, [proj.to_px(la, lo) for la, lo in ring])
             for role, ring in feat.role_geoms if len(ring) >= 3]
    if not rings:
        return
    xs = [x for _r, ring in rings for x, _y in ring]
    ys = [y for _r, ring in rings for _x, y in ring]
    x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))
    x1, y1 = min(image.width, int(max(xs)) + 2), min(image.height, int(max(ys)) + 2)
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    md = ImageDraw.Draw(mask)
    for role, ring in sorted(rings, key=lambda r: r[0] == "inner"):
        md.polygon([(x - x0, y - y0) for x, y in ring],
                   fill=0 if role == "inner" else 255)
    image.paste(Image.new("RGB", mask.size, fill), (x0, y0), mask)


def _draw_polygon(draw: ImageDraw.ImageDraw, rings: list[list[tuple[float, float]]],
                  fill: tuple[int, int, int]) -> None:
    for ring in rings:
        if len(ring) >= 3:
            draw.polygon(ring, fill=fill)


def _draw_line(draw: ImageDraw.ImageDraw, rings: list[list[tuple[float, float]]],
               fill: tuple[int, int, int], width_px: int) -> None:
    w = max(1, int(round(width_px)))
    for ring in rings:
        if len(ring) >= 2:
            draw.line(ring, fill=fill, width=w, joint="curve")
            # Round line caps so intersections look right.
            r = w // 2
            if r > 0:
                for x, y in ring:
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


# --- main entry point ------------------------------------------------------

@dataclass
class RenderResult:
    landscape_path: str
    vegetation_path: str
    spawn_map_path: str
    preview_path: str
    buildings_geojson_path: str
    meta_path: str
    width: int
    height: int
    cells_x: int
    cells_y: int


def render(features: Iterable[OSMFeature], south: float, west: float,
           north: float, east: float, meters_per_tile: float,
           output_dir: str, map_name: str,
           spawn_density: int = 10,
           tree_density: float = 1.0,
           rotation: float = 0.0,
           osm_cache: str | None = None,
           osm_bbox: tuple[float, float, float, float] | None = None,
           shape: dict | None = None) -> RenderResult:
    proj = Projector.build(south, west, north, east, meters_per_tile, rotation)
    # A drawn polygon, circle or real outline rather than a rectangle: the map
    # still covers its bounding box in whole cells, but only what lies inside
    # the shape is built.
    clip = shape_px(shape, proj)
    landscape = Image.new("RGB", (proj.width, proj.height), C.DARK_GRASS)
    vegetation = Image.new("RGB", (proj.width, proj.height), C.VEG_NOTHING)
    l_draw = ImageDraw.Draw(landscape)

    # Bucket features so we paint in a deterministic order.
    buckets: dict[str, list[OSMFeature]] = {}
    vegetation_feats: list[OSMFeature] = []
    building_feats: list[OSMFeature] = []
    fence_feats: list[OSMFeature] = []
    place_feats: list[OSMFeature] = []
    for feat in features:
        # Fences and hedges are collected from any outline that carries one,
        # before and independently of what the outline is: the fence around a
        # schoolyard is still a fence when the way is also the schoolyard.
        if feat.kind == "node" and "population" in feat.tags and "place" in feat.tags:
            place_feats.append(feat)
            continue
        if feat.kind == "node" and "natural" not in feat.tags:
            continue      # shops and cafes inside buildings: knoxbuild/uses.py
        barrier = feat.tags.get("barrier")
        if barrier in FENCE_BARRIERS and feat.kind == "way":
            fence_feats.append(feat)
        elif barrier == "hedge" and feat.kind == "way":
            vegetation_feats.append(feat)
        cat = classify(feat.tags)
        if cat is None:
            continue
        if cat in {"fence", "hedge"}:
            continue          # the line itself is collected below
        if cat in VEG_CATEGORIES:
            vegetation_feats.append(feat)
            if cat in {"forest", "scrub", "tree_single", "hedge"}:
                continue
        if cat == "building":
            if clip is not None and not _inside(feat, proj, clip):
                continue
            building_feats.append(feat)
        buckets.setdefault(cat, []).append(feat)

    # The sea first, under everything: a pier or a beach mapped over it
    # paints on top.
    for sea in sea_polygons(buckets.get("coastline", []), proj):
        for part in getattr(sea, "geoms", None) or [sea]:
            if hasattr(part, "exterior"):
                l_draw.polygon(list(part.exterior.coords), fill=C.WATER)
                for hole in part.interiors:
                    l_draw.polygon(list(hole.coords), fill=C.DARK_GRASS)

    for cat in LANDSCAPE_ORDER:
        if cat == "railway":
            # Pavements, as one pass over every road class and after the land
            # use: painted first, a park or a lawn mapped up to the kerb erased
            # the pavement and the tarmac met the grass. One pass so a side
            # street's pavement cannot cut across the high street it joins.
            for road in ("road_minor", "road_medium", "road_major"):
                margin = SIDEWALK_M[road]
                for feat in buckets.get(road, []):
                    if _is_polygon(feat):
                        continue
                    width_px = (_way_width_m(feat, road) + 2 * margin) / meters_per_tile
                    _draw_line(l_draw, _feature_coords_px(feat, proj),
                               C.PALE_CONCRETE, int(width_px))
            for road, verge in VERGE_M.items():
                for feat in buckets.get(road, []):
                    if _is_polygon(feat):
                        continue
                    width_px = (_way_width_m(feat, road) + 2 * verge) / meters_per_tile
                    _draw_line(l_draw, _feature_coords_px(feat, proj),
                               C.DARK_GRASS, int(width_px))
        fill = LANDSCAPE_FILL.get(cat)
        if fill is None:
            continue
        for feat in buckets.get(cat, []):
            rings = _feature_coords_px(feat, proj)
            if cat in ROAD_WIDTHS_M and not _is_polygon(feat):
                width_px = _way_width_m(feat, cat) / meters_per_tile
                _draw_line(l_draw, rings, fill, int(width_px))
            elif feat.kind == "relation":
                _paint_multipolygon(landscape, feat, proj, fill)
            elif _is_polygon(feat):
                _draw_polygon(l_draw, rings, fill)
            else:
                # A river or canal mapped only as its centre line.
                metres = WATERWAY_WIDTH_M.get(feat.tags.get("waterway"), 3.0)
                _draw_line(l_draw, rings, fill, max(1, int(metres / meters_per_tile)))

    _pave_dense_ground(landscape, building_feats, buckets, proj)
    if clip is not None:
        _clip_to_shape(landscape, clip, buckets, proj)
    _weather_roads(landscape, proj)

    _paint_vegetation(vegetation, landscape, vegetation_feats, proj,
                      density=tree_density)
    _paint_gardens(vegetation, landscape, building_feats, proj, density=tree_density)
    _clear_building_vegetation(vegetation, building_feats, proj)
    _paint_road_details(vegetation, landscape, buckets, proj)
    _paint_street_furniture(vegetation, landscape)

    # --- zombie spawn map (10x smaller, grayscale) ---
    spawn_w = proj.width // C.SPAWN_MAP_SCALE
    spawn_h = proj.height // C.SPAWN_MAP_SCALE
    spawn_map = _build_spawn_map(landscape, spawn_w, spawn_h, spawn_density)

    # --- preview (landscape + vegetation blended) ---
    preview = _build_preview(landscape, vegetation)

    # --- output files ---
    os.makedirs(output_dir, exist_ok=True)
    landscape_path = os.path.join(output_dir, f"{map_name}.bmp")
    veg_path = os.path.join(output_dir, f"{map_name}_veg.bmp")
    spawn_path = os.path.join(output_dir, f"{map_name}_ZombieSpawnMap.bmp")
    preview_path = os.path.join(output_dir, f"{map_name}_preview.png")
    buildings_path = os.path.join(output_dir, f"{map_name}_buildings.geojson")
    meta_path = os.path.join(output_dir, f"{map_name}_info.json")

    landscape.save(landscape_path, format="BMP")
    vegetation.save(veg_path, format="BMP")
    # The ground as drawn, before knoxbuild paints front paths into it
    # (knoxbuild/yards.py), so building again starts from clean ground.
    landscape.save(os.path.join(output_dir, f"{map_name}_ground_base.bmp"), format="BMP")
    vegetation.save(os.path.join(output_dir, f"{map_name}_veg_base.bmp"), format="BMP")
    spawn_map.save(spawn_path, format="BMP")
    preview.save(preview_path, format="PNG")

    with open(buildings_path, "w") as f:
        json.dump(_buildings_geojson(building_feats), f)
    with open(os.path.join(output_dir, f"{map_name}_areas.geojson"), "w") as f:
        json.dump(_areas_geojson(buckets), f)
    with open(os.path.join(output_dir, f"{map_name}_fences.geojson"), "w") as f:
        json.dump(_lines_geojson([f for f in fence_feats
                                  if clip is None or _inside(f, proj, clip)]), f)
    with open(os.path.join(output_dir, f"{map_name}_places.json"), "w",
              encoding="utf-8") as f:
        json.dump(_places(place_feats, proj), f, ensure_ascii=False)

    cells_x, cells_y = proj.cell_grid()
    with open(meta_path, "w") as f:
        json.dump({
            "map_name": map_name,
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "rotation": rotation,
            "osm_cache": osm_cache,
            "osm_bbox": list(osm_bbox) if osm_bbox else None,
            "shape": shape,
            "meters_per_tile": meters_per_tile,
            "width_tiles": proj.width,
            "height_tiles": proj.height,
            "cells_x": cells_x,
            "cells_y": cells_y,
            "spawn_density_max": spawn_density,
            "building_count": len(building_feats),
            "guide_reference": "Thuztor Mapping Guide v0.2",
        }, f, indent=2)

    return RenderResult(
        landscape_path=landscape_path,
        vegetation_path=veg_path,
        spawn_map_path=spawn_path,
        preview_path=preview_path,
        buildings_geojson_path=buildings_path,
        meta_path=meta_path,
        width=proj.width,
        height=proj.height,
        cells_x=cells_x,
        cells_y=cells_y,
    )


# A city block is paved when buildings cover at least this share of it - the
# same line knoxbuild draws between a city and a suburb.
# Measured: central Paris, Kadikoy and a Tokyo neighbourhood sit at 0.4-0.5, a
# US suburb and a French village around 0.16.
DENSE_COVERAGE = 0.28
# Mapped green space keeps its grass however built-up the area around it is.
GREEN_CATEGORIES = {"park", "grass", "sports", "cemetery", "orchard", "farmland",
                    "wetland", "hospital_grounds"}


def sea_polygons(feats: list[OSMFeature], proj: Projector) -> list:
    """The sea inside the map, as shapely polygons in tile coordinates.

    OSM maps the sea only by its shore: natural=coastline ways, each running
    with the land on its left and the water on its right. The map rectangle is
    cut along every shore line into faces, and each face is sea or land by
    which side of its nearest stretch of shore it lies on. That handles a
    headland, a bay, an island - any mix, as long as the shore is in view.
    A map with no shore in it is taken to be land.
    """
    from shapely.geometry import LineString, Point, box
    from shapely.ops import nearest_points, polygonize, unary_union

    w, h = proj.width, proj.height
    frame = box(0, 0, w, h)
    shores = []
    for feat in feats:
        if feat.kind != "way" or feat.tags.get("natural") != "coastline":
            continue
        pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
        if len(pts) >= 2:
            shores.append(LineString(pts))
    if not shores:
        return []
    # Join the shore into as few lines as possible, then carry any end that
    # stops inside the map on in its own direction to beyond the edge. The
    # download holds only coast that touches the area, so a shore that wanders
    # out of it and back arrives in pieces - and a line that does not cross
    # the map cannot split it, which left whole bays as dry land.
    from shapely.ops import linemerge
    merged = linemerge(unary_union(shores)) if len(shores) > 1 else shores[0]
    pieces = [merged] if isinstance(merged, LineString) else list(getattr(merged, "geoms", []))
    far = 3 * (w + h)
    inner = frame.buffer(-1)
    shores = []
    for line in pieces:
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        if coords[0] == coords[-1]:
            shores.append(line)          # an island: closed, nothing to extend
            continue
        for end, before in ((0, 1), (-1, -2)):
            ex, ey = coords[end]
            if inner.contains(Point(ex, ey)):
                bx, by = coords[before]
                dx, dy = ex - bx, ey - by
                length = math.hypot(dx, dy) or 1.0
                tip = (ex + dx / length * far, ey + dy / length * far)
                coords = [tip] + coords if end == 0 else coords + [tip]
        shores.append(LineString(coords))
    # Clip the shore to a little beyond the frame, so lines that only graze
    # the edge still split it, and the faces stay inside the map.
    reach = frame.buffer(2)
    clipped = [s.intersection(reach) for s in shores]
    lines = [g for c in clipped for g in (getattr(c, "geoms", None) or [c])
             if not g.is_empty and g.length > 0]
    if not lines:
        return []
    faces = list(polygonize(unary_union(lines + [frame.exterior])))

    def seaward(face) -> bool:
        spot = face.representative_point()
        best, best_d = None, None
        for line in lines:
            d = line.distance(spot)
            if best_d is None or d < best_d:
                best, best_d = line, d
        coords = list(best.coords)
        at = best.project(nearest_points(best, spot)[0])
        # The segment the nearest point falls on.
        run = 0.0
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            seg = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if run + seg >= at or (x2, y2) == coords[-1]:
                break
            run += seg
        cross = (x2 - x1) * (spot.y - y1) - (y2 - y1) * (spot.x - x1)
        # Tile y grows southward, which mirrors the plane: "right of the line"
        # has a positive cross product here, where it is negative on a map.
        return cross > 0

    return [f.intersection(frame) for f in faces
            if f.intersection(frame).area > 1 and seaward(f)]


def _real_kerbs(sides):
    """Keep kerbs that run along a straight edge; drop the steps of a staircase.

    Where a road crosses the tile grid at an angle its edge steps one tile
    every row, and a corner kerb on every step drew the edge as a row of
    teeth. A straight kerb stays when it is part of a run of at least three
    along the same edge (a corner may end the run); a corner stays only where straight
    kerbs lead into it on both arms. Staircase edges are left to the ground
    blends, which soften them.
    """
    import numpy as np

    W, N, S, E = 1, 2, 4, 8
    NW, SW, NE, SE = W | N, S | W, N | E, S | E
    padded = np.pad(sides, 2)
    core = (slice(2, -2), slice(2, -2))
    left, right = padded[2:-2, 1:-3], padded[2:-2, 3:-1]
    left2, right2 = padded[2:-2, :-4], padded[2:-2, 4:]
    up, down = padded[1:-3, 2:-2], padded[3:-1, 2:-2]
    up2, down2 = padded[:-4, 2:-2], padded[4:, 2:-2]
    del core

    def run3(here, a, a2, b, b2, allowed):
        # At least three in a row along the edge, this tile included.
        ia, ia2, ib, ib2 = (np.isin(x, allowed) for x in (a, a2, b, b2))
        return here & ((ia & ib) | (ia & ia2) | (ib & ib2))

    keep = np.zeros(sides.shape, dtype=bool)
    keep |= run3(sides == N, left, left2, right, right2, (N, NW, NE))
    keep |= run3(sides == S, left, left2, right, right2, (S, SW, SE))
    keep |= run3(sides == W, up, up2, down, down2, (W, NW, SW))
    keep |= run3(sides == E, up, up2, down, down2, (E, NE, SE))
    keep |= (sides == NW) & (right == N) & (down == W)
    keep |= (sides == NE) & (left == N) & (down == E)
    keep |= (sides == SW) & (right == S) & (up == W)
    keep |= (sides == SE) & (left == S) & (up == E)
    return np.where(keep, sides, 0).astype(sides.dtype)


def _smooth_road_edges(landscape: Image.Image, asphalt, is_colour) -> None:
    """Fill one-tile notches along the edge of the road, and shave one-tile bumps.

    A street a degree or two off the tile grid rasterises with its edge
    stepping back and forth by a tile; kerbs follow every step, and the edge
    came out as a row of teeth. A pavement tile with road on both sides of it
    along a line becomes road, and a road tile with pavement on both sides
    becomes pavement.
    """
    import numpy as np

    w, h = landscape.size
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        top, bottom = max(0, y0 - 1), min(h, y1 + 1)
        ground = np.asarray(landscape.crop((0, top, w, bottom))).copy()
        for _ in range(2):
            road = is_colour(ground, asphalt)
            pave = is_colour(ground, (C.PALE_CONCRETE,))
            notch = np.zeros_like(road)
            notch[1:-1, :] |= road[:-2, :] & road[2:, :]
            notch[:, 1:-1] |= road[:, :-2] & road[:, 2:]
            notch &= pave
            bump = np.zeros_like(road)
            bump[1:-1, :] |= pave[:-2, :] & pave[2:, :]
            bump[:, 1:-1] |= pave[:, :-2] & pave[:, 2:]
            bump &= road
            if not notch.any() and not bump.any():
                break
            # A filled notch takes the tarmac of the road beside it.
            ys, xs = np.nonzero(notch)
            for y, x in zip(ys, xs):
                if y > 0 and road[y - 1, x]:
                    ground[y, x] = ground[y - 1, x]
                elif x > 0 and road[y, x - 1]:
                    ground[y, x] = ground[y, x - 1]
                elif y + 1 < road.shape[0] and road[y + 1, x]:
                    ground[y, x] = ground[y + 1, x]
                else:
                    ground[y, x] = ground[y, x + 1]
            ground[bump] = C.PALE_CONCRETE
        rows = slice(y0 - top, y0 - top + (y1 - y0))
        landscape.paste(Image.fromarray(ground[rows]), (0, y0))


def _paint_road_details(veg: Image.Image, landscape: Image.Image,
                        buckets: dict[str, list[OSMFeature]], proj: Projector) -> None:
    """Kerbs where pavement meets the road, and lines down two-lane roads.

    Asphalt ran straight into the pavement with nothing between them, and a
    road wider than a car had nothing painted on it. The vanilla map has both
    on every street - laid by hand - and without them a street reads as a grey
    patch rather than a road.
    """
    import numpy as np

    w, h = landscape.size
    asphalt = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
               C.DARK_POTHOLE, C.LIGHT_POTHOLE)

    def is_colour(ground, colours):
        mask = np.zeros(ground.shape[:2], dtype=bool)
        for colour in colours:
            same = ground[:, :, 0] == colour[0]
            same &= ground[:, :, 1] == colour[1]
            same &= ground[:, :, 2] == colour[2]
            mask |= same
        return mask

    _smooth_road_edges(landscape, asphalt, is_colour)

    # Kerbs, a strip at a time, each strip read with a row of overlap so the
    # tiles either side of a seam still see their neighbours.
    kerb_for = {1: C.KERB_W, 2: C.KERB_N, 4: C.KERB_S, 8: C.KERB_E,
                3: C.KERB_NW, 5: C.KERB_SW, 10: C.KERB_NE, 12: C.KERB_SE}
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        top, bottom = max(0, y0 - 1), min(h, y1 + 1)
        ground = np.asarray(landscape.crop((0, top, w, bottom)))
        road = is_colour(ground, asphalt)
        pave = is_colour(ground, (C.PALE_CONCRETE,))
        sides = np.zeros(road.shape, dtype=np.uint8)
        sides[:, 1:] |= road[:, :-1] * np.uint8(1)     # road to the west
        sides[1:, :] |= road[:-1, :] * np.uint8(2)     # road to the north
        sides[:-1, :] |= road[1:, :] * np.uint8(4)     # road to the south
        sides[:, :-1] |= road[:, 1:] * np.uint8(8)     # road to the east
        sides[~pave] = 0
        sides = _real_kerbs(sides)
        rows = slice(y0 - top, y0 - top + (y1 - y0))
        sides = sides[rows]
        existing = np.asarray(veg.crop((0, y0, w, y1)))
        free = (existing.reshape(-1, 3).max(axis=1) == 0).reshape(sides.shape)
        out = existing.copy()
        for bits, colour in kerb_for.items():
            out[(sides == bits) & free] = colour
        veg.paste(Image.fromarray(out), (0, y0))

    # Centre lines, on roads wide enough for two lanes and straight enough to
    # run along one axis of the tile grid; a line stepping round a diagonal
    # reads as a zigzag, so those are left plain.
    mpt = proj.meters_per_tile
    marks = []
    for cat, style in (("road_major", "yellow"), ("road_medium", "white")):
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            width = _way_width_m(feat, cat) / mpt
            if width < 6 or feat.tags.get("oneway") in ("yes", "1", "-1"):
                continue
            for ring in _feature_coords_px(feat, proj):
                for (ax, ay), (bx, by) in zip(ring, ring[1:]):
                    dx, dy = bx - ax, by - ay
                    if abs(dy) <= 0.2 * abs(dx):
                        marks.append((style, "N", ax, ay, bx, by, width))
                    elif abs(dx) <= 0.2 * abs(dy):
                        marks.append((style, "W", ax, ay, bx, by, width))
    if not marks:
        return
    colour_for = {("yellow", "N"): C.LINE_YELLOW_N, ("yellow", "W"): C.LINE_YELLOW_W,
                  ("white", "N"): C.LINE_WHITE_N, ("white", "W"): C.LINE_WHITE_W}
    ground_px = landscape.load()
    veg_px = veg.load()

    def road_at(x, y):
        return 0 <= x < w and 0 <= y < h and ground_px[x, y] in asphalt

    for style, edge, ax, ay, bx, by, width in marks:
        steps = int(max(abs(bx - ax), abs(by - ay)))
        for i in range(steps + 1):
            t = i / steps if steps else 0
            # The line sits on the edge between two tiles, so the road's
            # middle is rounded to the nearest tile boundary.
            x = int(round(ax + (bx - ax) * t))
            y = int(round(ay + (by - ay) * t))
            along = x if edge == "N" else y
            if style == "white" and (along // 3) % 2:
                continue
            if not (road_at(x, y) and (road_at(x, y - 1) if edge == "N" else road_at(x - 1, y))):
                continue
            # At a junction the tarmac runs on across the line; a line through
            # the middle of a crossroads is wrong, so stop short of it.
            run = 0
            for k in range(1, int(width) + 4):
                if edge == "N":
                    run += road_at(x, y - k) + road_at(x, y + k - 1)
                else:
                    run += road_at(x - k, y) + road_at(x + k - 1, y)
            if run > width + 3:
                continue
            if veg_px[x, y] == C.VEG_NOTHING:
                veg_px[x, y] = colour_for[(style, edge)]


# How often the vanilla streets have each, measured on their squares
# (tools/building_stats.py's neighbourhoods): grime on 9% of the tarmac, cracks
# on under 0.5%, a lamp per ~290 squares of street, and so on. Spacings are in
# tiles along the kerb.
GRIME_SHARE = 0.14
# Roads at least this wide get a faded edge line down each side.
EDGE_LINE_MIN_WIDTH = 5
CRACK_SHARE = 0.012
LITTER_SHARE = 0.002
LAMP_EVERY = 26
# A speed limit sign every so many tiles along a main street's kerb (Erika's
# Tiles only), with the limit going by how wide the carriageway is.
SPEED_SIGN_EVERY = 90
SPEED_BY_WIDTH = ((12, 45), (8, 35), (0, 25))


def _mod_tiles_ready() -> bool:
    """Whether maps may use Erika's Tiles: installed and set up, and not
    turned off with KNOXMAP_NO_MOD_TILES=1."""
    if os.environ.get("KNOXMAP_NO_MOD_TILES") == "1":
        return False
    try:
        import knoxpaths
        if not knoxpaths.erikas_tiles_ready():
            return False
        # Tools set up before the signs existed have no rule for them, and a
        # colour without a rule is dropped with a warning: run Setup again.
        rules = knoxpaths.mapping_tools_dir() / "config" / "Rules.txt"
        return "KnoxMap road Speed limit 25 S" in rules.read_text(encoding="utf-8", errors="replace")
    except Exception:      # noqa: BLE001 - no tools, no mod tiles
        return False
HYDRANT_EVERY = 70
DRAIN_EVERY = 34


def _paint_street_furniture(veg: Image.Image, landscape: Image.Image) -> dict:
    """Lamps, hydrants and drains along the kerbs; grime, cracks and litter.

    A generated street was clean tarmac, kerb and pavement and nothing else;
    Knox County's have all of these, and a road without them reads as a
    diagram. They go by the kerbs already painted: a lamp stands on the
    pavement one tile back from a straight kerb with its arm over the road, a
    hydrant likewise, a drain in the gutter in front of it.
    """
    import numpy as np

    rng = np.random.default_rng(4321)
    ground = np.asarray(landscape.convert("RGB"))
    vp = np.array(veg.convert("RGB"))
    h, w = ground.shape[:2]

    def is_colour(arr, colours):
        mask = np.zeros(arr.shape[:2], dtype=bool)
        for c in colours:
            mask |= np.all(arr == c, axis=2)
        return mask

    empty = np.all(vp == 0, axis=2)
    asphalt = is_colour(ground, (C.MEDIUM_ASPHALT, C.DARKEST_ASPHALT))
    pavement = is_colour(ground, (C.PALE_CONCRETE,))
    counts = {}

    # Edge lines: tarmac with the road's edge on exactly one side and enough
    # road across from it to be a carriageway, not a car park aisle's end.
    # (Dark tarmac, 100, is car parks and yards, and is left out.)
    k = EDGE_LINE_MIN_WIDTH
    edge_lines = 0
    for colour, (dx, dy) in ((C.EDGE_LINE_W, (-1, 0)), (C.EDGE_LINE_E, (1, 0)),
                             (C.EDGE_LINE_N, (0, -1)), (C.EDGE_LINE_S, (0, 1))):
        outside = np.zeros_like(asphalt)
        across = np.ones_like(asphalt)
        if dx:
            if dx < 0:
                outside[:, 1:] = ~asphalt[:, :-1]
                for i in range(1, k):
                    across[:, :-i] &= asphalt[:, i:]
                    across[:, -i:] = False
            else:
                outside[:, :-1] = ~asphalt[:, 1:]
                for i in range(1, k):
                    across[:, i:] &= asphalt[:, :-i]
                    across[:, :i] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[1:, :] = asphalt[:-1, :]; side_b[:-1, :] = asphalt[1:, :]
        else:
            if dy < 0:
                outside[1:, :] = ~asphalt[:-1, :]
                for i in range(1, k):
                    across[:-i, :] &= asphalt[i:, :]
                    across[-i:, :] = False
            else:
                outside[:-1, :] = ~asphalt[1:, :]
                for i in range(1, k):
                    across[i:, :] &= asphalt[:-i, :]
                    across[:i, :] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[:, 1:] = asphalt[:, :-1]; side_b[:, :-1] = asphalt[:, 1:]
        # Straight edges only: the road continues along the line both ways.
        pick = asphalt & outside & across & side_a & side_b & empty
        vp[pick] = colour
        empty &= ~pick
        edge_lines += int(pick.sum())
    counts["edge lines"] = edge_lines

    # Along each straight edge of the carriageway, road on one side: the lamp
    # stands a tile or two off the tarmac (past the kerb or on the verge) with
    # its arm reaching back over the road, the drain sits in the gutter.
    # (edge colour just painted, step away from the road, lamp colour)
    straight = [(C.EDGE_LINE_W, (-1, 0), C.LAMP_E), (C.EDGE_LINE_E, (1, 0), C.LAMP_W),
                (C.EDGE_LINE_N, (0, -1), C.LAMP_S), (C.EDGE_LINE_S, (0, 1), C.LAMP_N)]
    taken: dict[str, set] = {"lamp": set(), "hydrant": set(), "drain": set(), "speed": set()}
    out = vp.copy()
    # Speed signs stand where drivers keeping right see their faces: on the
    # east kerb of a north-south road facing south, the north kerb of an
    # east-west one facing east. Erika's signs only face those two ways.
    speed_side = {C.EDGE_LINE_E: "S", C.EDGE_LINE_N: "E"} if _mod_tiles_ready() else {}

    def carriageway(gx, gy, sx, sy):
        n = 0
        while n < 24 and 0 <= gx - n * sx < w and 0 <= gy - n * sy < h \
                and asphalt[gy - n * sy, gx - n * sx]:
            n += 1
        return n

    for edge, (sx, sy), lamp in straight:
        ys, xs = np.nonzero(np.all(vp == edge, axis=2))
        order = rng.permutation(len(xs))
        for i in order.tolist():
            gx, gy = int(xs[i]), int(ys[i])     # the gutter square itself
            bx, by = gx + 2 * sx, gy + 2 * sy   # past the kerb or the verge
            if not (0 <= bx < w and 0 <= by < h):
                continue
            facing = speed_side.get(edge)
            speed = None
            if facing:
                across = carriageway(gx, gy, sx, sy)
                limit = next(v for width, v in SPEED_BY_WIDTH if across >= width)
                speed = C.SPEED_SIGNS[(limit, facing)]
            for what, every, colour, at, need in (
                    ("speed", SPEED_SIGN_EVERY, speed, (bx, by), None),
                    ("lamp", LAMP_EVERY, lamp, (bx, by), None),
                    ("hydrant", HYDRANT_EVERY, C.HYDRANT, (bx, by), None),
                    ("drain", DRAIN_EVERY, C.STORM_DRAIN, (gx, gy), None)):
                px, py = at
                if colour is None or not (0 <= px < w and 0 <= py < h):
                    continue
                # Speed signs keep a spacing per facing: the north-south roads,
                # met first, took every cell and left east-west ones none.
                cell = (px // every, py // every, facing if what == "speed" else None)
                if cell in taken[what]:
                    continue
                # A drain takes the gutter square from its edge line; a lamp
                # or hydrant needs an empty square off the road.
                if what != "drain" and (not empty[py, px] or asphalt[py, px]):
                    continue
                taken[what].add(cell)
                out[py, px] = colour
                empty[py, px] = False
                counts[what] = counts.get(what, 0) + 1
                break

    # Wear comes in patches, as it does on a real road and on the vanilla
    # map; picked square by square it came out as a chequerboard. Smooth noise
    # - coarse random values, blurred up to full size - gives the patches.
    coarse = Image.fromarray((rng.random((max(1, h // 5), max(1, w // 5))) * 255).astype(np.uint8))
    noise = np.asarray(coarse.resize((w, h), Image.BICUBIC)
                       .filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    level = np.quantile(noise[asphalt], 1 - GRIME_SHARE) if asphalt.any() else 256
    pick = asphalt & empty & (noise >= level)
    out[pick] = C.ASPHALT_GRIME
    empty &= ~pick
    counts["grime"] = int(pick.sum())
    # Scattered things: each square rolls once, and each kind has its own band
    # of the roll, so no square gets two.
    roll = rng.random((h, w))
    lo = 0.0
    for mask, share, colour, name in (
            (asphalt, CRACK_SHARE, C.ASPHALT_CRACKS, "cracks"),
            (pavement, LITTER_SHARE, C.LITTER, "litter")):
        pick = mask & empty & (roll >= lo) & (roll < lo + share)
        lo += share
        out[pick] = colour
        empty &= ~pick
        counts[name] = int(pick.sum())
    veg.paste(Image.fromarray(out), (0, 0))
    return counts


def _pave_dense_ground(landscape: Image.Image, building_feats: list[OSMFeature],
                       buckets: dict[str, list[OSMFeature]], proj: Projector) -> None:
    """Pave the unmapped ground of built-up city blocks.

    Land OSM says nothing about is painted as wild grass, which is right in the
    countryside and wrong in an old town, where it is courtyards, alleys and
    the gaps between blocks. Central Paris came out 77% meadow.

    The decision is made per city block - the ground the streets enclose - on
    how much of that block is under buildings. It used to be made per patch of
    ground on the density nearby, which near the threshold flickered between
    paved and grass across a single block and left it blotched like camouflage.
    A block is paved whole or not at all, as real ones are. Mapped parks,
    gardens and pitches keep their grass inside a paved block; a residential
    area's lawns do not, since between buildings packed this tight they are
    yards.
    """
    import numpy as np
    from shapely import STRtree
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import polygonize, unary_union

    w, h = landscape.size
    frame = box(0, 0, w, h)
    streets = []
    for cat in ("road_major", "road_medium", "road_minor", "road_service"):
        for feat in buckets.get(cat, []):
            if feat.kind == "way" and not _is_polygon(feat):
                pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
                if len(pts) >= 2:
                    streets.append(LineString(pts))
    if not streets:
        return
    blocks = [b.intersection(frame) for b in
              polygonize(unary_union(streets + [frame.exterior]))]
    blocks = [b for b in blocks if not b.is_empty and b.area > 50]

    footprints = []
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                poly = Polygon(ring)
                footprints.append(poly if poly.is_valid else poly.buffer(0))
    if not footprints:
        return
    tree = STRtree(footprints)

    paved = Image.new("L", (w, h), 0)
    pd = ImageDraw.Draw(paved)
    any_paved = False
    for block in blocks:
        covered = sum(footprints[i].intersection(block).area
                      for i in tree.query(block))
        if covered / block.area < DENSE_COVERAGE:
            continue
        for part in getattr(block, "geoms", None) or [block]:
            if hasattr(part, "exterior"):
                pd.polygon(list(part.exterior.coords), fill=255)
                for hole in part.interiors:
                    pd.polygon(list(hole.coords), fill=0)
                any_paved = True
    if not any_paved:
        return

    keep = Image.new("L", (w, h), 0)
    kd = ImageDraw.Draw(keep)
    for cat in GREEN_CATEGORIES:
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                for ring in _feature_coords_px(feat, proj):
                    if len(ring) >= 3:
                        kd.polygon(ring, fill=255)

    # Strip by strip, so the colour tests never hold the whole map at once.
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        mask = np.asarray(paved.crop((0, y0, w, y1))) > 0
        mask &= np.asarray(keep.crop((0, y0, w, y1))) == 0
        if not mask.any():
            continue
        ground = np.asarray(landscape.crop((0, y0, w, y1)))
        grass = np.zeros(mask.shape, dtype=bool)
        for colour in (C.DARK_GRASS, C.MEDIUM_GRASS):
            same = ground[:, :, 0] == colour[0]
            same &= ground[:, :, 1] == colour[1]
            same &= ground[:, :, 2] == colour[2]
            grass |= same
        mask &= grass
        if mask.any():
            paint = Image.new("RGB", (w, y1 - y0), C.PALE_CONCRETE)
            landscape.paste(paint, (0, y0), Image.fromarray(mask.astype(np.uint8) * 255))


def _weather_roads(landscape: Image.Image, proj: Projector) -> None:
    """Break up the tarmac with worn patches.

    Every road in a class is otherwise a single flat colour from kerb to kerb
    for its whole length, which is the main reason a generated town looks
    printed rather than driven on. Rules.txt has two pothole shades that blend
    into asphalt, so scattering small blots of them costs nothing in tiles and
    gives the surface some age.

    Patches go on asphalt only - they are skipped over grass, water, pavement
    and building footprints, so nothing outside the carriageway is touched.
    """
    import random

    asphalt = {C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT}
    px = landscape.load()
    rng = random.Random(20250913)
    # One patch per 1500 tiles of map. Denser than this and the roads read as
    # bombed rather than worn.
    attempts = max(1, (proj.width * proj.height) // 1500)
    for _ in range(attempts):
        cx = rng.randrange(proj.width)
        cy = rng.randrange(proj.height)
        if px[cx, cy] not in asphalt:
            continue
        shade = rng.choice((C.DARK_POTHOLE, C.LIGHT_POTHOLE))
        radius = rng.randint(1, 3)
        for y in range(max(0, cy - radius), min(proj.height, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(proj.width, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                    continue
                if px[x, y] in asphalt:
                    px[x, y] = shade


def _paint_vegetation(veg: Image.Image, landscape: Image.Image,
                      feats: list[OSMFeature], proj: Projector,
                      density: float = 1.0) -> None:
    _paint_vegetation_extras(veg, landscape, feats, proj)
    _paint_woodland(veg, landscape,
                    [f for f in feats if classify(f.tags) in
                     {"forest", "scrub", "tree_single"}], proj, density)


def _paint_woodland(veg: Image.Image, landscape: Image.Image,
                    feats: list[OSMFeature], proj: Projector,
                    density: float = 1.0) -> None:
    """Paint trees on the vegetation bitmap.

    Forest polygons get full density (TREES), scrub becomes bushes+trees,
    single-tree nodes become small dots. Forest edges get downgraded to a
    mix with dark grass so the transition isn't a hard rectangle.

    `density` below 1 thins the woodland by stepping every tile down one
    grade - full trees become a mix with dark grass, a mix becomes sparse,
    sparse becomes nothing - and above 1 it does the reverse. Which matters
    because trees are cover: a map buried in forest plays completely
    differently from the same map with hedgerows.
    """
    mask = Image.new("L", veg.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    scrub_mask = Image.new("L", veg.size, 0)
    scrub_draw = ImageDraw.Draw(scrub_mask)

    for feat in feats:
        cat = classify(feat.tags)
        rings = _feature_coords_px(feat, proj)
        if cat == "forest":
            if _is_polygon(feat):
                for ring in rings:
                    if len(ring) >= 3:
                        mask_draw.polygon(ring, fill=255)
        elif cat == "scrub":
            if _is_polygon(feat):
                for ring in rings:
                    if len(ring) >= 3:
                        scrub_draw.polygon(ring, fill=255)
        elif cat == "tree_single":
            if rings and rings[0]:
                x, y = rings[0][0]
                r = max(1, int(2 / proj.meters_per_tile))
                mask_draw.ellipse((x - r, y - r, x + r, y + r), fill=255)

    # Build a "border band" of the forest mask so we can paint edges lighter.
    eroded = mask.filter(ImageFilter.MinFilter(5))
    veg_px = veg.load()
    mask_px = mask.load()
    eroded_px = eroded.load()
    scrub_px = scrub_mask.load()
    land_px = landscape.load()

    # Thickest to thinnest. `density` shifts every tile along this ladder.
    GRADES = [C.VEG_NOTHING, C.SPARSE_TREES, C.TREES_DARK_GRASS, C.TREES]

    def graded(colour) -> tuple[int, int, int]:
        if density == 1.0:
            return colour
        i = GRADES.index(colour)
        shift = round((density - 1.0) * 2)
        return GRADES[min(max(i + shift, 0), len(GRADES) - 1)]

    w, h = veg.size
    for y in range(h):
        for x in range(w):
            if scrub_px[x, y]:
                veg_px[x, y] = C.BUSHES_TREES_DARK_GRASS
            if mask_px[x, y]:
                # Only paint trees on grass / dirt. Skip water, roads, buildings.
                lp = land_px[x, y]
                if lp == C.WATER:
                    continue
                shade = graded(C.TREES if eroded_px[x, y]
                               else C.TREES_DARK_GRASS)
                if shade == C.VEG_NOTHING:
                    continue
                veg_px[x, y] = shade
                # Trees on a grass tile → switch the landscape to DARK_GRASS
                # so the PZ renderer is happy (trees sit on dark grass best).
                if lp in (C.MEDIUM_GRASS, C.LIGHT_GRASS):
                    land_px[x, y] = C.DARK_GRASS


def _paint_vegetation_extras(veg: Image.Image, landscape: Image.Image,
                             feats: list[OSMFeature], proj: Projector) -> None:
    """Hedges, orchards, cemeteries and wetland, which are not woodland.

    Hedges are rows of bushes a metre or two wide along their line. Orchard
    trees go in on a regular grid - what makes an orchard recognisable from
    the air is that its trees stand in rows. Cemeteries get scattered flowers
    and the odd tree, wetland patches of dense bush.
    """
    import random

    rng = random.Random(0x5EED)
    draw = ImageDraw.Draw(veg)
    land_draw = ImageDraw.Draw(landscape)
    vp = veg.load()
    lp = landscape.load()
    w, h = veg.size

    def polygon_mask(feat):
        mask = Image.new("1", veg.size, 0)
        md = ImageDraw.Draw(mask)
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                md.polygon(ring, fill=1)
        return mask

    for feat in feats:
        cat = classify(feat.tags)
        if feat.tags.get("barrier") == "hedge":
            width = max(1, int(round(1.5 / proj.meters_per_tile)))
            for ring in _feature_coords_px(feat, proj):
                if len(ring) >= 2:
                    draw.line(ring, fill=C.BUSHES, width=width)
        elif cat in {"orchard", "cemetery", "wetland"} and _is_polygon(feat):
            mask = polygon_mask(feat)
            bbox = mask.getbbox()
            if not bbox:
                continue
            mp = mask.load()
            x0, y0, x1, y1 = bbox
            spacing = max(2, int(round(4 / proj.meters_per_tile)))
            for y in range(y0, y1):
                for x in range(x0, x1):
                    if not mp[x, y] or lp[x, y] == C.WATER:
                        continue
                    if cat == "orchard":
                        if x % spacing == 0 and y % spacing == 0:
                            vp[x, y] = C.TREES
                            lp[x, y] = C.DARK_GRASS
                    elif cat == "cemetery":
                        roll = rng.random()
                        if roll < 0.012:
                            vp[x, y] = C.TREES
                            lp[x, y] = C.DARK_GRASS
                        elif roll < 0.08:
                            vp[x, y] = C.FLOWERS
                    else:
                        if rng.random() < 0.35:
                            vp[x, y] = C.DENSE_BUSHES_GRASS
                            lp[x, y] = C.DARK_GRASS


# Garden planting. Trees came only from mapped woods, orchards and single-tree
# nodes, and suburbs rarely map their garden trees, so a real leafy suburb
# came out as houses standing on bare lawn. Yards - grass within reach of a
# house, clear of roads and paths - get a tree about every GARDEN_TREE_EVERY
# tiles each way, and a few shrubs against the house walls.
GARDEN_REACH_TILES = 18        # how far from a house its yard reaches
GARDEN_TREE_EVERY = 9
GARDEN_TREE_CHANCE = 0.6
GARDEN_CLEAR_OF_HOUSE = 3      # a tree trunk this far off the wall at least
GARDEN_CLEAR_OF_PAVING = 2     # and off the kerb, drive or path
SHRUB_CHANCE = 0.12            # per tile of lawn along a house wall
# Tufts over open grass. A lawn of one flat grass tile looked like felt beside
# the vanilla map, whose grass is broken up by clumps everywhere.
SHORT_GRASS_SHARE = 0.2
# Long grass is off: its rule mixes in flowerbed tiles, which came out as pink
# and blue squares all over every lawn.
LONG_GRASS_SHARE = 0.0
GRASS_COLOURS = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS)


def _box_any(mask, radius: int):
    """True wherever `mask` is true within `radius` tiles (a square reach)."""
    import numpy as np

    h, w = mask.shape
    pad = np.pad(mask.astype(np.int32), radius + 1)
    ii = pad.cumsum(0).cumsum(1)
    k = 2 * radius + 1
    total = ii[k:k + h, k:k + w] - ii[0:h, k:k + w] - ii[k:k + h, 0:w] + ii[0:h, 0:w]
    return total > 0


def _paint_gardens(veg: Image.Image, landscape: Image.Image,
                   building_feats: list[OSMFeature], proj: Projector,
                   density: float = 1.0) -> int:
    """Trees in yards and shrubs along house walls. Returns trees planted."""
    import numpy as np

    if not building_feats or density <= 0:
        return 0
    houses = Image.new("1", veg.size, 0)
    hd = ImageDraw.Draw(houses)
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                hd.polygon(ring, fill=1)
    house = np.array(houses, dtype=bool)
    ground = np.array(landscape.convert("RGB"))
    grass = np.zeros(house.shape, dtype=bool)
    for colour in GRASS_COLOURS:
        grass |= np.all(ground == colour, axis=2)
    vegp = np.array(veg.convert("RGB"))
    empty = np.all(vegp == 0, axis=2)
    lawn = grass & empty & ~house
    paved_near = _box_any(~grass & ~house, GARDEN_CLEAR_OF_PAVING)

    yard = lawn & _box_any(house, GARDEN_REACH_TILES)         & ~_box_any(house, GARDEN_CLEAR_OF_HOUSE) & ~paved_near
    rng = np.random.default_rng(1234)
    step = GARDEN_TREE_EVERY
    chance = min(1.0, GARDEN_TREE_CHANCE * density)
    h, w = house.shape
    px = veg.load()
    planted = 0
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            if rng.random() >= chance:
                continue
            ys, xs = np.nonzero(yard[y0:y0 + step, x0:x0 + step])
            if len(xs) == 0:
                continue
            i = rng.integers(len(xs))
            px[int(x0 + xs[i]), int(y0 + ys[i])] = C.TREES
            planted += 1

    # Shrubs: lawn right against a wall, not in front of the paving.
    beside = lawn & _box_any(house, 1) & ~house & ~paved_near
    ys, xs = np.nonzero(beside & (rng.random(house.shape) < SHRUB_CHANCE * density))
    for x, y in zip(xs.tolist(), ys.tolist()):
        px[x, y] = C.BUSHES

    open_grass = lawn & ~beside & ~_box_any(house, 0)
    roll = rng.random(house.shape)
    for colour, share, lo in ((C.SHORT_GRASS, SHORT_GRASS_SHARE, 0.0),
                              (C.GRASS_ON_DARK, LONG_GRASS_SHARE, SHORT_GRASS_SHARE)):
        ys, xs = np.nonzero(open_grass & (roll >= lo) & (roll < lo + share))
        for x, y in zip(xs.tolist(), ys.tolist()):
            if px[x, y] == C.VEG_NOTHING:
                px[x, y] = colour
    return planted


def _clear_building_vegetation(veg: Image.Image, feats: list[OSMFeature],
                               proj: Projector) -> None:
    """No trees or bushes inside a building.

    Woodland polygons and single-tree nodes are mapped independently of the
    buildings standing in them, so a tree painted under a house came out as a
    tree growing through its living-room floor.
    """
    mask = Image.new("1", veg.size, 0)
    md = ImageDraw.Draw(mask)
    for feat in feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                md.polygon(ring, fill=1)
    blank = Image.new("RGB", veg.size, C.VEG_NOTHING)
    veg.paste(blank, (0, 0), mask)


def _places(feats: list[OSMFeature], proj: Projector) -> list[dict]:
    """Named places with an official population, and where they sit."""
    out = []
    for f in feats:
        raw = str(f.tags.get("population", "")).replace(",", "").replace(" ", "")
        try:
            population = int(float(raw.split(";")[0]))
        except ValueError:
            continue
        la, lo = f.geometry[0]
        x, y = proj.to_px(la, lo)
        out.append({"name": f.tags.get("name", ""), "place": f.tags.get("place"),
                    "population": population, "tile_x": round(x), "tile_y": round(y),
                    "inside": 0 <= x < proj.width and 0 <= y < proj.height})
    return out


AREA_TAGS = {"landuse", "amenity", "leisure", "name", "religion"}


def _areas_geojson(buckets: dict[str, list[OSMFeature]]) -> dict:
    """Land-use polygons, with the category each was painted as."""
    features = []
    for cat in AREA_CATEGORIES:
        for f in buckets.get(cat, []):
            if not _is_polygon(f):
                continue
            if f.kind == "way":
                rings = [[[lon, lat] for lat, lon in f.geometry]]
            else:
                rings = [[[lon, lat] for lat, lon in ring]
                         for role, ring in f.role_geoms if role != "inner"]
            polys = [[r] for r in rings if len(r) >= 3]
            if not polys:
                continue
            features.append({
                "type": "Feature",
                "properties": {"category": cat,
                               **{k: v for k, v in f.tags.items() if k in AREA_TAGS}},
                "geometry": {"type": "MultiPolygon", "coordinates": polys},
            })
    return {"type": "FeatureCollection", "features": features}


LINE_TAGS = {"barrier", "fence_type", "material", "height", "wall"}


def _lines_geojson(feats: list[OSMFeature]) -> dict:
    """Fence and wall lines for knoxbuild to turn into fence tiles."""
    features = []
    for f in feats:
        if f.kind != "way" or len(f.geometry) < 2:
            continue
        features.append({
            "type": "Feature",
            "properties": {k: v for k, v in f.tags.items() if k in LINE_TAGS},
            "geometry": {"type": "LineString",
                         "coordinates": [[lon, lat] for lat, lon in f.geometry]},
        })
    return {"type": "FeatureCollection", "features": features}


def _build_spawn_map(landscape: Image.Image, w: int, h: int,
                     max_density: int) -> Image.Image:
    """Grayscale spawn map. Dense in built-up areas, zero over water.

    The red channel is read as a raw zombie density, and Build 42 reads it on a
    much smaller scale than you would guess from a 0-255 byte. Sampling the
    vanilla Knox County spawn map: values run 1..10 and 97% of the map is 0.
    Writing 96 here - a quarter of the byte range - buries the map in thousands
    of zombies. Everything below is expressed as a fraction of `max_density`,
    which now defaults to vanilla's ceiling of 10.
    """
    scaled = landscape.resize((w, h), Image.Resampling.BILINEAR)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    sp = scaled.load()
    op = out.load()
    rng = random.Random(0xABBA)

    def band(chance: float, lo: float, hi: float) -> int:
        """Density between two fractions of the ceiling, `chance` of the time.

        Sparsity matters as much as the ceiling. Vanilla leaves 97% of the map
        at zero and averages about 0.06 per pixel; filling every pixel with a
        mid value - even a small one - still produces a wall of zombies. Town
        maps are denser than county-wide wilderness, but the shape should be
        the same: crowds on the streets, almost nothing in the fields.
        """
        if rng.random() > chance:
            return 0
        return int(round(rng.uniform(max_density * lo, max_density * hi)))

    for y in range(h):
        for x in range(w):
            r, g, b = sp[x, y]
            if r == C.WATER[0] and g == C.WATER[1] and b == C.WATER[2]:
                v = 0
            elif (75 <= r <= 175 and abs(r - g) < 30 and abs(g - b) < 30)                     or (r, g, b) == C.PAVING:
                # Asphalt, pavement and paved squares: where crowds belong.
                # The low end has to reach 75 now that the widest roads are
                # painted street4 at 80,80,80 - a range starting at 95 left
                # every main road through town as quiet as a field.
                v = band(0.40, 0.4, 1.0)
            elif r > g and r > 90 and g < 110:
                # Dirt tracks, yards, building footprints.
                v = band(0.15, 0.2, 0.5)
            elif g > r and g > 80:
                # Open grass: the odd wanderer, nothing more.
                v = band(0.03, 0.1, 0.2)
            else:
                v = band(0.08, 0.1, 0.3)
            op[x, y] = (v, v, v)
    return out


def _build_preview(landscape: Image.Image, vegetation: Image.Image) -> Image.Image:
    """Human-friendly PNG: landscape with trees painted dark green."""
    preview = landscape.copy()
    lp = preview.load()
    vp = vegetation.load()
    w, h = preview.size
    tree_colors = {C.TREES, C.TREES_DARK_GRASS, C.SPARSE_TREES,
                   C.BUSHES_TREES_DARK_GRASS}
    for y in range(h):
        for x in range(w):
            v = vp[x, y]
            if v in tree_colors:
                lp[x, y] = (40, 75, 35) if v == C.TREES else (65, 95, 45)
    return preview


# What survives into the geojson knoxbuild reads. amenity/shop/leisure carry
# what a building actually is far more reliably than the building tag alone,
# and they pick its materials and room plan.
#
# building:levels earns its place twice over: it is the only thing in OSM that
# says how tall a building is, and dropping it meant every block of flats in a
# town was rebuilt as a bungalow no matter what the mapper had recorded.
BUILDING_TAGS = {
    "building", "building:levels", "building:part", "building:material",
    "building:use", "height", "levels", "roof:levels", "roof:shape",
    "name", "addr:housenumber", "addr:street", "addr:flats",
    "amenity", "shop", "leisure", "tourism", "industrial",
    "healthcare", "office", "craft", "man_made", "residential", "cuisine",
}


def _buildings_geojson(feats: list[OSMFeature]) -> dict:
    """Export building footprints so the user knows where to drop .tbx lots."""
    features = []
    for f in feats:
        if f.kind == "way":
            coords = [[lon, lat] for lat, lon in f.geometry]
            if len(coords) >= 3:
                features.append({
                    "type": "Feature",
                    # amenity/shop/leisure carry what a building actually is
                    # far more reliably than the building tag alone, and
                    # knoxbuild uses them to pick materials and room plans.
                    "properties": {k: v for k, v in f.tags.items()
                                   if k in BUILDING_TAGS},
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                })
        elif f.kind == "relation":
            polys = []
            for role, ring in f.role_geoms:
                if role == "inner":
                    continue
                coords = [[lon, lat] for lat, lon in ring]
                if len(coords) >= 3:
                    polys.append([coords])
            if polys:
                features.append({
                    "type": "Feature",
                    "properties": {k: v for k, v in f.tags.items()
                                   if k in BUILDING_TAGS},
                    "geometry": {"type": "MultiPolygon", "coordinates": polys},
                })
    return {"type": "FeatureCollection", "features": features}
