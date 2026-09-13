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

    @classmethod
    def build(cls, south: float, west: float, north: float, east: float,
              meters_per_tile: float) -> "Projector":
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
                   t)

    def to_px(self, lat: float, lon: float) -> tuple[float, float]:
        x_m, y_m = self._transformer.transform(lon, lat)
        px = (x_m - self.min_x_m) / self.meters_per_tile
        # Image Y grows downward; UTM Y grows northward → flip.
        py = self.height - (y_m - self.min_y_m) / self.meters_per_tile
        return px, py

    def cell_grid(self) -> tuple[int, int]:
        return self.width // C.CELL_SIZE, self.height // C.CELL_SIZE


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
    "dirt_path",      # thin dirt line
    "parking",        # car park tarmac
    "plaza",          # paved pedestrian square
    "road_service",   # alleys and driveways
    "road_minor",
    "road_medium",
    "road_major",     # widest, so it wins at junctions
    "water",          # water overrides almost everything
    "pool",
    # Building footprints are not painted at all. They used to be dirt, which
    # showed as a brown fringe wherever the placed building and the painted
    # footprint disagreed by a tile - and the building's own floor covers the
    # ground under it anyway.
]

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
}

# Metres of kerb either side. Town streets in the vanilla game sit in a band of
# pale concrete; without it the asphalt runs straight into grass and every road
# looks like it was dropped on the landscape rather than built into it.
SIDEWALK_M = {
    "road_major": 2.5,
    "road_medium": 2.0,
    "road_minor": 1.5,
}

LANDSCAPE_FILL = {
    "water": C.WATER,
    "sand": C.SAND,
    "dirt": C.DIRT,
    "dirt_path": C.DIRT,
    "grass": C.MEDIUM_GRASS,
    "park": C.MEDIUM_GRASS,
    "farmland": C.LIGHT_GRASS,
    # street/street2/street4 in Rules.txt. road_minor used to paint
    # lightgravel, which put a gravel track through the middle of every
    # residential street in town.
    "road_service": C.LIGHT_ASPHALT,
    "road_minor": C.MEDIUM_ASPHALT,
    "road_medium": C.DARK_ASPHALT,
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
           tree_density: float = 1.0) -> RenderResult:
    proj = Projector.build(south, west, north, east, meters_per_tile)
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
            building_feats.append(feat)
        buckets.setdefault(cat, []).append(feat)

    # Kerbs first, as one pass over every road class. Doing it per class would
    # let a side street's pavement cut across the high street it joins, because
    # the high street is painted earlier in the order.
    for cat in ("road_minor", "road_medium", "road_major"):
        margin = SIDEWALK_M[cat]
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            rings = _feature_coords_px(feat, proj)
            width_px = (_way_width_m(feat, cat) + 2 * margin) / meters_per_tile
            _draw_line(l_draw, rings, C.PALE_CONCRETE, int(width_px))

    for cat in LANDSCAPE_ORDER:
        fill = LANDSCAPE_FILL.get(cat)
        if fill is None:
            continue
        for feat in buckets.get(cat, []):
            rings = _feature_coords_px(feat, proj)
            if cat in ROAD_WIDTHS_M and not _is_polygon(feat):
                width_px = _way_width_m(feat, cat) / meters_per_tile
                _draw_line(l_draw, rings, fill, int(width_px))
            elif _is_polygon(feat):
                _draw_polygon(l_draw, rings, fill)
            else:
                # Unexpected: linear water like a stream. Draw it narrow.
                _draw_line(l_draw, rings, fill, max(1, int(3 / meters_per_tile)))

    _weather_roads(landscape, proj)

    _paint_vegetation(vegetation, landscape, vegetation_feats, proj,
                      density=tree_density)
    _clear_building_vegetation(vegetation, building_feats, proj)

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
    spawn_map.save(spawn_path, format="BMP")
    preview.save(preview_path, format="PNG")

    with open(buildings_path, "w") as f:
        json.dump(_buildings_geojson(building_feats), f)
    with open(os.path.join(output_dir, f"{map_name}_areas.geojson"), "w") as f:
        json.dump(_areas_geojson(buckets), f)
    with open(os.path.join(output_dir, f"{map_name}_fences.geojson"), "w") as f:
        json.dump(_lines_geojson(fence_feats), f)
    with open(os.path.join(output_dir, f"{map_name}_places.json"), "w",
              encoding="utf-8") as f:
        json.dump(_places(place_feats, proj), f, ensure_ascii=False)

    cells_x, cells_y = proj.cell_grid()
    with open(meta_path, "w") as f:
        json.dump({
            "map_name": map_name,
            "bbox": {"south": south, "west": west, "north": north, "east": east},
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
    "healthcare", "office", "craft", "man_made", "residential",
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
            for _role, ring in f.role_geoms:
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
