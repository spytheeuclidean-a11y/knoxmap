"""Projection between lat/lon and tiles, the selection drawn on the map, and the bbox the grid covers."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pyproj

from .. import pz_colors as C
from ..osm import OSMFeature


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

    def to_latlon(self, px: float, py: float) -> tuple[float, float]:
        """The inverse of to_px."""
        back = getattr(self, "_back", None)
        if back is None:
            back = pyproj.Transformer.from_crs(self._transformer.target_crs,
                                               "EPSG:4326", always_xy=True)
            object.__setattr__(self, "_back", back)
        x_m = self.min_x_m + px * self.meters_per_tile
        y_m = self.min_y_m + (self.height - py) * self.meters_per_tile
        if self.rotation:
            cx = self.min_x_m + self.width * self.meters_per_tile / 2
            cy = self.min_y_m + self.height * self.meters_per_tile / 2
            a = math.radians(-self.rotation)
            dx, dy = x_m - cx, y_m - cy
            x_m = cx + dx * math.cos(a) - dy * math.sin(a)
            y_m = cy + dx * math.sin(a) + dy * math.cos(a)
        lon, lat = back.transform(x_m, y_m)
        return lat, lon

    def to_latlon_many(self, px, py):
        """to_latlon for numpy arrays of pixel coordinates: (lat, lon) arrays."""
        import numpy as np

        back = getattr(self, "_back", None)
        if back is None:
            back = pyproj.Transformer.from_crs(self._transformer.target_crs,
                                               "EPSG:4326", always_xy=True)
            object.__setattr__(self, "_back", back)
        x_m = self.min_x_m + np.asarray(px, dtype=np.float64) * self.meters_per_tile
        y_m = self.min_y_m + (self.height - np.asarray(py, dtype=np.float64)) * self.meters_per_tile
        if self.rotation:
            cx = self.min_x_m + self.width * self.meters_per_tile / 2
            cy = self.min_y_m + self.height * self.meters_per_tile / 2
            a = math.radians(-self.rotation)
            dx, dy = x_m - cx, y_m - cy
            x_m = cx + dx * math.cos(a) - dy * math.sin(a)
            y_m = cy + dx * math.sin(a) + dy * math.cos(a)
        lon, lat = back.transform(x_m, y_m)
        return np.asarray(lat), np.asarray(lon)

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


def _ceil_to(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)
