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
worldmap-annotations.lua
               a function adding text labels through the map's symbols API,
               in absolute world tiles: the town's name, its parks and
               squares, rivers and lakes, and its best-known buildings.
"""
from __future__ import annotations

import json
import os
import re
from xml.sax.saxutils import quoteattr

from shapely.geometry import LineString, MultiLineString, Polygon, box
from shapely.ops import linemerge, unary_union

from generator import osm
from generator.renderer import (THROUGH_ROADS, _is_polygon, _way_width_m,
                                sea_polygons, shape_px)

from .world import origin

CELL = 300

# What each generated building kind is on the map. These are the categories
# the vanilla style colours; a shed is drawn as a plain building.
BUILDING_VALUE = {
    "house": "Residential", "apartment": "Residential",
    "shop": "RetailAndCommercial", "mall": "RetailAndCommercial",
    "restaurant": "RestaurantsAndEntertainment",
    "school": "CommunityServices", "civic": "CommunityServices",
    "church": "CommunityServices", "medical": "Medical",
    "industrial": "Industrial", "barn": "Industrial", "shed": "yes",
}
# Road classes as the map style knows them. It has no class for a service
# lane, so those draw as the smallest street.
HIGHWAY_VALUE = {
    "road_major": "primary", "road_medium": "secondary",
    "road_minor": "tertiary", "road_service": "tertiary",
    "pedestrian": "tertiary",
    "dirt_path": "trail", "paved_path": "tertiary",
}
RAIL_WIDTH_M = 4.0
AREA_VALUE = {"water": ("water", "river"), "pool": ("water", "river"),
              "forest": ("natural", "forest")}
# Streets worth a name on the map. Footpaths carry names too, but labelling
# every alley and pavement buries the streets people navigate by.
NAMED_CLASSES = {"road_major", "road_medium", "road_minor", "road_service",
                 "pedestrian"}
# The credit lines under the OpenStreetMap note on the paper map: names to a line,
# and tiles between lines.
CREDIT_NAMES_PER_LINE = 4
CREDIT_LINE_GAP = 8
SIMPLIFY = 0.5     # tiles; the map is drawn far smaller than one tile per pixel

# Points in one <street> of streets.xml, at most. Project Zomboid (Build 42) builds
# each street's outline for the paper map in one shared 3 KB buffer
# (IsoMetaGrid.clipperBuffer, in WorldMapStreet.createPolygon and
# clipToObscuredCells) and never makes it bigger there. A street of more than
# about 190 points overflows it: BufferOverflowException is thrown inside the
# map's render, and the whole map window - streets, legend, buttons - draws
# nothing for as long as that street is under the mouse, so the M map looks
# broken for the rest of the session. Long country roads in OpenStreetMap get
# there. 32 keeps a piece's outline and its triangles under 3 KB even with every corner mitred.
# The map joins pieces of one name that share an end, so a road still highlights as one.
MAX_STREET_POINTS = 32

# Labels: the style layer each goes on and how large, as the vanilla
# Muldraugh annotations use them.
TOWN_SCALE = {"city": 4.5, "town": 3.5, "village": 2.5, "suburb": 2.0,
              "quarter": 1.5, "neighbourhood": 1.2, "hamlet": 1.2}
PLACE_SCALE = 0.6
BUILDING_SCALE = 0.6
# Only buildings people would give directions by, and not every one of them:
# a label per corner shop buries the map.
LABELLED_KINDS = {"school", "church", "medical", "civic", "industrial", "shop",
                  "restaurant", "house", "apartment"}
MIN_LABELLED_TILES = 150
MAX_BUILDING_LABELS = 40
MIN_PLACE_TILES = 400
PLACE_CATEGORIES = {"park", "plaza", "cemetery", "sports", "grass"}


def write(out_dir: str, map_name: str, proj, info: dict,
          buildings: list[tuple[list[tuple[float, float]], str, str]]) -> dict:
    """Write worldmap.xml and streets.xml into `out_dir`. Returns counts.

    `buildings` holds each placed building's projected outline and its kind.
    Roads, water and woodland come from the OSM download cached beside the
    map; a map folder without one still gets its buildings.
    """
    metres_per_tile = info["meters_per_tile"]
    width, height = proj.width, proj.height
    features: list[tuple[Polygon, str, str]] = []

    labels: list[tuple[str, str, float, float, float]] = []
    named_buildings = []
    for outline, kind, name in buildings:
        poly = _clean(Polygon(outline))
        if poly is not None:
            features.append((poly, "building", BUILDING_VALUE.get(kind, "yes")))
            if name and kind in LABELLED_KINDS and poly.area >= MIN_LABELLED_TILES:
                named_buildings.append((poly.area, name, poly))
    named_buildings.sort(key=lambda b: -b[0])
    for _area, name, poly in named_buildings[:MAX_BUILDING_LABELS]:
        spot = poly.representative_point()
        labels.append((name, "text-building", BUILDING_SCALE, spot.x, spot.y))

    bbox = info.get("bbox") or {}
    cache = os.path.join(out_dir, info["osm_cache"]) if info.get("osm_cache") \
        else osm.cache_path(out_dir, map_name)
    wanted = tuple(info["osm_bbox"]) if info.get("osm_bbox") else \
        (bbox.get("south"), bbox.get("west"), bbox.get("north"), bbox.get("east"))
    # Whatever download is beside the map, however old the filter list it was
    # fetched with. This step never fetches one, so turning an older file away
    # does not get the newer tags - it writes a map with the buildings on it
    # and not one road, river or wood.
    feats = osm.load_cache(cache, wanted, filters=None) or []
    feats = osm.proposed_roads(feats, info.get("include_proposed_roads", 0))
    if not feats:
        print(f"  paper map           : no download beside the map "
              f"({os.path.basename(cache)}), so it has buildings only - "
              f"generate the map again to put the streets back")
    if info.get("straight_roads"):
        # The streets as the map drew them, not as they are.
        from generator.octilinear import replay
        from generator.renderer import classify
        replay(feats, proj, classify, _is_polygon, info, out_dir, map_name)
    clip = shape_px(info.get("shape"), proj)
    streets: dict[str, list[tuple[LineString, float]]] = {}
    railways = []
    for feat in feats:
        if feat.kind == "node":
            continue
        cat = osm.classify(feat.tags, _is_polygon(feat))
        if cat in HIGHWAY_VALUE and not _is_polygon(feat):
            line = _line(feat, proj)
            if line is None:
                continue
            if clip is not None and cat not in THROUGH_ROADS:
                # The drawn shape's side streets only, as on the ground.
                line = line.intersection(clip)
                if line.is_empty or line.length < 1:
                    continue
                if not isinstance(line, LineString):
                    parts = [g for g in getattr(line, "geoms", []) if isinstance(g, LineString)]
                    if not parts:
                        continue
                    line = max(parts, key=lambda g: g.length)
            width_tiles = _way_width_m(feat, cat) / metres_per_tile
            strip = line.buffer(width_tiles / 2, cap_style=2, join_style=2)
            poly = _clean(strip)
            if poly is not None:
                features.append((poly, "highway", HIGHWAY_VALUE[cat]))
            name = (feat.tags.get("name") or "").strip()
            if name and cat in NAMED_CLASSES:
                streets.setdefault(name, []).append((line, width_tiles))
        elif cat == "railway" and not _is_polygon(feat):
            railways.append(feat)
        elif cat in AREA_VALUE and _is_polygon(feat):
            key, value = AREA_VALUE[cat]
            for ring in _outer_rings(feat, proj):
                poly = _clean(Polygon(ring))
                if poly is not None:
                    features.append((poly, key, value))
                    name = (feat.tags.get("name") or "").strip()
                    if name and key == "water" and poly.area >= MIN_PLACE_TILES:
                        spot = poly.representative_point()
                        labels.append((name, "text-water-medium", 1.0, spot.x, spot.y))
        elif cat in PLACE_CATEGORIES and _is_polygon(feat) and "highway" not in feat.tags:
            name = (feat.tags.get("name") or "").strip()
            rings = _outer_rings(feat, proj)
            if name and rings:
                poly = _clean(Polygon(rings[0]))
                if poly is not None and poly.area >= MIN_PLACE_TILES:
                    spot = poly.representative_point()
                    labels.append((name, "text-place", PLACE_SCALE, spot.x, spot.y))

    from generator.rendering.rails import rail_paths
    for path in rail_paths(railways, proj):
        poly = _clean(LineString(path).buffer(RAIL_WIDTH_M / metres_per_tile / 2,
                                             cap_style=2, join_style=2))
        if poly is not None:
            features.append((poly, "railway", "rail"))

    for sea in sea_polygons(feats, proj):
        for part in getattr(sea, "geoms", None) or [sea]:
            poly = _clean(part) if hasattr(part, "exterior") else None
            if poly is not None:
                features.append((poly, "water", "river"))

    cells = _write_worldmap(os.path.join(out_dir, "worldmap.xml"), features,
                            width, height)
    named = _write_streets(os.path.join(out_dir, "streets.xml"), streets)

    places_path = os.path.join(out_dir, f"{map_name}_places.json")
    if os.path.exists(places_path):
        with open(places_path, encoding="utf-8") as f:
            for place in json.load(f):
                if place.get("inside") and place.get("name"):
                    labels.append((place["name"], "text-town",
                                   TOWN_SCALE.get(place.get("place"), 2.0),
                                   place["tile_x"], place["tile_y"]))
    # OpenStreetMap attribution in the game itself, in a corner of the map
    # players open, as the ODbL attribution guidelines ask of produced works.
    labels.append(("Map data (c) OpenStreetMap contributors", "text-note", 0.35,
                   min(width - 1, 150), min(height - 1, 12)))
    # And the credit for KnoxMap and everyone who made it, under it: one line
    # for the maker, then the rest in lines of CREDIT_NAMES_PER_LINE.
    from . import credits
    people = list(credits.CONTRIBUTORS)
    credit_lines = [f"Made with KnoxMap by {credits.MAKER}"]
    credit_lines += ["with " + ", ".join(people[i:i + CREDIT_NAMES_PER_LINE]) if i == 0
                     else ", ".join(people[i:i + CREDIT_NAMES_PER_LINE])
                     for i in range(0, len(people), CREDIT_NAMES_PER_LINE)]
    for n, line in enumerate(credit_lines, start=1):
        labels.append((line, "text-note", 0.35, min(width - 1, 150),
                       min(height - 1, 12 + CREDIT_LINE_GAP * n)))
    _write_annotations(os.path.join(out_dir, "worldmap-annotations.lua"),
                       labels, width, height)
    return {"map_features": len(features), "map_cells": cells, "streets": named,
            "labels": len(labels)}

def lua_string(text: str) -> str:
    """A Lua string literal for `text`, with every byte above ASCII escaped.

    The game reads worldmap-annotations.lua with a reader that a non-ASCII byte
    stops: a town whose name is in Cyrillic lost its whole in-game map, and
    replacing the one Cyrillic character in a name with a Latin lookalike brought
    all 44 of that map's annotations back (#38). A Lua decimal escape is the same
    byte in the string and nothing but ASCII in the file, so the name is still
    the name - the bytes are exactly the UTF-8 they were, and nothing here
    guesses at how the game reads them.
    """
    out = []
    for char in text:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char in "\n\r" or ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(" ")          # a control character has no place in a label
        elif ord(char) < 0x7F:
            out.append(char)
        else:
            # UTF-8 never starts or continues with a byte below 128, so every
            # escape here is three digits and cannot run into the next one.
            out.extend(f"\\{byte}" for byte in char.encode("utf-8"))
    return '"' + "".join(out) + '"'


_LUA_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
                "v": "\v", "\\": "\\", '"': '"', "'": "'"}


def lua_text(literal: str) -> str:
    """The text a Lua string literal stands for - lua_string() the other way.

    Takes the literal with or without its quotes: the regex that reads a label
    back out of worldmap-annotations.lua captures what is between them. A string
    that is not a literal is decoded as it stands, because a map built by an
    older KnoxMap has raw UTF-8 in that file and it still has to install.
    """
    body = literal[1:-1] if (len(literal) >= 2 and literal.startswith('"')
                             and literal.endswith('"')) else literal
    out, i = bytearray(), 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out += char.encode("utf-8")
            i += 1
            continue
        following = body[i + 1] if i + 1 < len(body) else ""
        digits = re.match(r"\d{1,3}", body[i + 1:]) if following.isdigit() else None
        if digits:
            out.append(int(digits.group(0)) & 0xFF)
            i += 1 + len(digits.group(0))
        elif following in _LUA_ESCAPES:
            out += _LUA_ESCAPES[following].encode("utf-8")
            i += 2
        else:
            out += following.encode("utf-8")     # not an escape Lua knows: keep it
            i += 2
    return out.decode("utf-8", errors="replace")


def _write_annotations(path: str, labels: list[tuple[str, str, float, float, float]],
                       width: int, height: int) -> None:
    """Text on the paper map, the way vanilla's worldmap-annotations.lua adds it."""
    ox, oy = origin()[0] * CELL, origin()[1] * CELL
    seen = set()
    lines = ["return function(mapUI)",
             "\tlocal mapAPI = mapUI.javaObject:getAPIv3()",
             "\tlocal symbolsAPI = mapAPI:getSymbolsAPIv2()",
             "\tlocal symbol"]
    for name, layer, scale, x, y in labels:
        if not (0 <= x < width and 0 <= y < height) or (name, layer) in seen:
            continue
        seen.add((name, layer))
        lines += [
            f"\tsymbol = symbolsAPI:addUntranslatedText({lua_string(name)}, "
            f'"{layer}", {round(x + ox)}, {round(y + oy)})',
            "\tsymbol:setRGBA(0.000, 0.000, 0.000, 0.000)",
            f"\tsymbol:setScale({scale:.3f})",
            "\tsymbol:setAnchor(0.50, 0.50)",
            "\tsymbol:setRotation(0.0)",
            "\tsymbol:setMatchPerspective(true)",
            "\tsymbol:setApplyZoom(true)",
            "\tsymbol:setMinZoom(0.00)",
            "\tsymbol:setMaxZoom(24.00)",
            "\tsymbol:setUserDefined(false)",
            ""]
    lines.append("end")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


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
    ox, oy = origin()
    by_cell: dict[tuple[int, int], list[str]] = {}
    for poly, key, value in features:
        minx, miny, maxx, maxy = poly.bounds
        for cy in range(max(0, int(miny // CELL)), min(height // CELL, int(maxy // CELL) + 1)):
            for cx in range(max(0, int(minx // CELL)), min(width // CELL, int(maxx // CELL) + 1)):
                x0, y0 = cx * CELL, cy * CELL
                if minx >= x0 and maxx <= x0 + CELL and miny >= y0 and maxy <= y0 + CELL:
                    clipped = poly
                else:
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
    
def _street_pieces(coords: list, most: int = MAX_STREET_POINTS) -> list[list]:
    """`coords` cut into runs of at most `most` points, each starting on the last
    one's final point, so together they are the same line (see MAX_STREET_POINTS)."""
    if len(coords) <= most:
        return [coords]
    pieces, i = [], 0
    while i < len(coords) - 1:
        pieces.append(coords[i:i + most])
        i += most - 1
    return pieces




def _write_streets(path: str, streets: dict[str, list[tuple[LineString, float]]]) -> int:
    """One entry per continuous stretch of each named street."""
    ox, oy = origin()[0] * CELL, origin()[1] * CELL
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
                for coords in _street_pieces(list(line.coords)):
                    pts = "\n".join(f'            <point x="{x + ox:.1f}" y="{y + oy:.1f}"/>'
                                    for x, y in coords)
                    f.write(f'    <street name={quoteattr(name)} width="{width}">\n'
                            f'        <points>\n{pts}\n        </points>\n    </street>\n')
                    count += 1
        f.write("</streets>\n")
    return count
