"""What a render writes besides the two bitmaps: place names, area, line and opening GeoJSON, the
zombie spawn map and the preview picture."""
from __future__ import annotations

import random

from PIL import Image

from .. import pz_colors as C
from ..osm import OSMFeature
from .geometry import _is_polygon
from .landcover import AREA_CATEGORIES
from .projection import Projector


def _places(feats: list[OSMFeature], proj: Projector) -> list[dict]:
    """Named places with an official population, and where they sit."""
    out = []
    for f in feats:
        raw = str(f.tags.get("population", "")).replace(",", "").replace(" ", "")
        try:
            population = int(float(raw.split(";")[0]))
        except (ValueError, OverflowError):      # OverflowError: "inf", "1e999"
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


# Ways people walk through a fence on: the path to the playing field, the
# track to the yard. A fence drawn across one is drawn with a gap.
OPENING_PATHS = {"paved_path", "dirt_path", "pedestrian"}


def _openings_geojson(gates: list[OSMFeature], buckets: dict) -> dict:
    """Where a fence should have a way through it: gates, and the paths that
    cross one. The crossing itself is worked out where the fence is built
    (knoxbuild/fences.py), which is the only place that knows where the line
    ended up on the grid."""
    features = []
    for f in gates:
        if not f.geometry:
            continue
        lat, lon = f.geometry[0]
        features.append({
            "type": "Feature",
            "properties": {"opening": "gate",
                           "barrier": f.tags.get("barrier") or "gate"},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    for cat in sorted(OPENING_PATHS):
        for f in buckets.get(cat, ()):
            if f.kind != "way" or len(f.geometry) < 2 or _is_polygon(f):
                continue
            features.append({
                "type": "Feature",
                "properties": {"opening": "path", "category": cat},
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
                   C.BUSHES_TREES_DARK_GRASS, C.TREE_SMALL}
    # A big tree covers more ground than its one tile, so the preview gives it
    # the square it keeps clear - otherwise a wood of them reads as a clearing.
    for y in range(h):
        for x in range(w):
            v = vp[x, y]
            if v in tree_colors:
                lp[x, y] = (40, 75, 35) if v == C.TREES else (65, 95, 45)
            elif v in C.BIG_TREE_ROOM:
                side = C.BIG_TREE_ROOM[v]
                reach = side // 2 if side % 2 else 0
                for fy in range(max(0, y - reach), min(h, y - reach + side)):
                    for fx in range(max(0, x - reach), min(w, x - reach + side)):
                        lp[fx, fy] = (25, 60, 25)
    return preview
