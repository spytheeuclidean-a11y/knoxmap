"""The in-game paper map and its street names.

Project Zomboid draws the map a player opens with M from two files in the map
folder: worldmap.xml, polygons tagged with what they are, and streets.xml,
named centre lines. Without them a generated map opens as a blank sheet - the
one place in the game where the real town should be most recognisable.

Both are written the way the vanilla Muldraugh files are laid out (Build 42):

worldmap.xml   <world version="1.0"> of <cell x y> blocks, one per 300-tile
               cell in world cell numbers. Each <feature> is a polygon in
               that cell's own coordinates, 0-300, with a property the map
               style filters on: building=Residential/RetailAndCommercial/...,
               highway=primary/secondary/tertiary/trail, water=river,
               natural=forest. Everything is a polygon - roads included, as
               strips as wide as the road.
streets.xml    <streets version="1"> of <street name width> with <point x y>
               in absolute world tiles.
"""
from __future__ import annotations

import os
from xml.sax.saxutils import quoteattr

from shapely.geometry import LineString, MultiLineString, Polygon, box
from shapely.ops import linemerge, unary_union

from generator import osm
from generator.renderer import _is_polygon, _way_width_m

from .world import WORLD_ORIGIN_CELLS

CELL = 300

# What each generated building kind is on the map. These are the categories
# the vanilla style colours; a shed is drawn as a plain building.
BUILDING_VALUE = {
    "house": "Residential", "apartment": "Residential",
    "shop": "RetailAndCommercial", "restaurant": "RestaurantsAndEntertainment",
    "school": "CommunityServices", "civic": "CommunityServices",
    "church": "CommunityServices", "medical": "Medical",
    "industrial": "Industrial", "barn": "Industrial", "shed": "yes",
}
# Road classes as the map style knows them. It has no class for a service
# lane, so those draw as the smallest street.
HIGHWAY_VALUE = {
    "road_major": "primary", "road_medium": "secondary",
    "road_minor": "tertiary", "road_service": "tertiary",
    "dirt_path": "trail", "paved_path": "trail",
}
AREA_VALUE = {"water": ("water", "river"), "pool": ("water", "river"),
              "forest": ("natural", "forest")}
# Streets worth a name on the map. Footpaths carry names too, but labelling
# every alley and pavement buries the streets people navigate by.
NAMED_CLASSES = {"road_major", "road_medium", "road_minor", "road_service"}
SIMPLIFY = 0.5     # tiles; the map is drawn far smaller than one tile per pixel


def write(out_dir: str, map_name: str, proj, info: dict,
          buildings: list[tuple[list[tuple[float, float]], str]]) -> dict:
    """Write worldmap.xml and streets.xml into `out_dir`. Returns counts.

    `buildings` holds each placed building's projected outline and its kind.
    Roads, water and woodland come from the OSM download cached beside the
    map; a map folder without one still gets its buildings.
    """
    metres_per_tile = info["meters_per_tile"]
    width, height = proj.width, proj.height
    features: list[tuple[Polygon, str, str]] = []

    for outline, kind in buildings:
        poly = _clean(Polygon(outline))
        if poly is not None:
            features.append((poly, "building", BUILDING_VALUE.get(kind, "yes")))

    bbox = info.get("bbox") or {}
    feats = osm.load_cache(osm.cache_path(out_dir, map_name),
                           (bbox.get("south"), bbox.get("west"),
                            bbox.get("north"), bbox.get("east"))) or []
    streets: dict[str, list[tuple[LineString, float]]] = {}
    for feat in feats:
        if feat.kind == "node":
            continue
        cat = osm.classify(feat.tags)
        if cat in HIGHWAY_VALUE and not _is_polygon(feat):
            line = _line(feat, proj)
            if line is None:
                continue
            width_tiles = _way_width_m(feat, cat) / metres_per_tile
            strip = line.buffer(width_tiles / 2, cap_style=2, join_style=2)
            poly = _clean(strip)
            if poly is not None:
                features.append((poly, "highway", HIGHWAY_VALUE[cat]))
            name = (feat.tags.get("name") or "").strip()
            if name and cat in NAMED_CLASSES:
                streets.setdefault(name, []).append((line, width_tiles))
        elif cat in AREA_VALUE and _is_polygon(feat):
            key, value = AREA_VALUE[cat]
            for ring in _outer_rings(feat, proj):
                poly = _clean(Polygon(ring))
                if poly is not None:
                    features.append((poly, key, value))

    cells = _write_worldmap(os.path.join(out_dir, "worldmap.xml"), features,
                            width, height)
    named = _write_streets(os.path.join(out_dir, "streets.xml"), streets)
    return {"map_features": len(features), "map_cells": cells, "streets": named}


def _clean(poly) -> Polygon | None:
    if poly.is_empty:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    poly = poly.simplify(SIMPLIFY, preserve_topology=True)
    return None if poly.is_empty or poly.area < 1 else poly


def _line(feat, proj) -> LineString | None:
    pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
    return LineString(pts) if len(pts) >= 2 else None


def _outer_rings(feat, proj) -> list[list[tuple[float, float]]]:
    if feat.kind == "way":
        return [[proj.to_px(la, lo) for la, lo in feat.geometry]]
    return [[proj.to_px(la, lo) for la, lo in ring]
            for role, ring in feat.role_geoms
            if role in ("outer", "") and len(ring) >= 3]


def _parts(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _write_worldmap(path: str, features: list[tuple[Polygon, str, str]],
                    width: int, height: int) -> int:
    """Clip every feature to the cells it crosses, in cell coordinates."""
    ox, oy = WORLD_ORIGIN_CELLS
    by_cell: dict[tuple[int, int], list[str]] = {}
    for poly, key, value in features:
        minx, miny, maxx, maxy = poly.bounds
        for cy in range(max(0, int(miny // CELL)), min(height // CELL, int(maxy // CELL) + 1)):
            for cx in range(max(0, int(minx // CELL)), min(width // CELL, int(maxx // CELL) + 1)):
                x0, y0 = cx * CELL, cy * CELL
                clipped = poly.intersection(box(x0, y0, x0 + CELL, y0 + CELL))
                for part in _parts(clipped):
                    if part.area < 1:
                        continue
                    ring = list(part.exterior.coords)[:-1]
                    pts = "\n".join(
                        f'     <point x="{round(x - x0)}" y="{round(y - y0)}"/>'
                        for x, y in ring)
                    by_cell.setdefault((cx, cy), []).append(
                        '  <feature>\n   <geometry type="Polygon">\n'
                        f'    <coordinates>\n{pts}\n    </coordinates>\n'
                        '   </geometry>\n   <properties>\n'
                        f'    <property name="{key}" value={quoteattr(value)}/>\n'
                        '   </properties>\n  </feature>')
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<world version="1.0">\n')
        for (cx, cy) in sorted(by_cell, key=lambda c: (c[1], c[0])):
            f.write(f' <cell x="{ox + cx}" y="{oy + cy}">\n')
            f.write("\n".join(by_cell[(cx, cy)]))
            f.write("\n </cell>\n")
        f.write("</world>\n")
    return len(by_cell)


def _write_streets(path: str, streets: dict[str, list[tuple[LineString, float]]]) -> int:
    """One entry per continuous stretch of each named street."""
    ox, oy = WORLD_ORIGIN_CELLS[0] * CELL, WORLD_ORIGIN_CELLS[1] * CELL
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<streets version="1">\n')
        for name in sorted(streets):
            pieces = streets[name]
            width = max(3, round(max(w for _l, w in pieces)))
            joined = unary_union([l for l, _w in pieces])
            merged = linemerge(joined) if isinstance(joined, MultiLineString) else joined
            lines = [merged] if isinstance(merged, LineString) else \
                list(getattr(merged, "geoms", []))
            for line in lines:
                line = line.simplify(SIMPLIFY)
                if line.length < 10:
                    continue
                pts = "\n".join(f'            <point x="{x + ox:.1f}" y="{y + oy:.1f}"/>'
                                for x, y in line.coords)
                f.write(f'    <street name={quoteattr(name)} width="{width}">\n'
                        f'        <points>\n{pts}\n        </points>\n    </street>\n')
                count += 1
        f.write("</streets>\n")
    return count
