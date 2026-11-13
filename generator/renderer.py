"""Rasterize OSM features into Project Zomboid bitmaps.

Output contract (per the Mapping Guide):
  <name>.bmp              — landscape (11 palette colors)
  <name>_veg.bmp          — vegetation (must be same size as landscape)
    <name>_road_hierarchy.bmp — grayscale OSM road class across right-of-way
  <name>_ZombieSpawnMap.bmp — grayscale, 1/10th resolution

Dimensions are snapped up to the next multiple of 300 (PZ cell size). The
requested real-world bbox is expanded symmetrically to fit that grid so the
meters-per-tile scale stays consistent.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

import knoxfiles
import knoxstop

from . import pz_colors as C
from . import structures
from .osm import (FENCE_BARRIERS, GATE_BARRIERS, OSMFeature,  # noqa: F401
                  ROAD_HIERARCHY_BY_CODE, ROAD_HIERARCHY_CODES, classify,
                  road_hierarchy)

# Everything that moved out is still importable from here: the tests, the
# tools and knoxbuild reach into this module by name.
from .rendering.buildings import (ADDRESS_APART_M, ADDRESS_AVOIDS_ROADS,
                                  ADDRESS_CLEAR_M, ADDRESS_HOUSE_M,
                                  ADDRESS_PUSH_M, ADDRESS_SETBACK_M,
                                  BUILDING_TAGS, MAX_ADDRESS_HOUSES,
                                  _buildings_geojson, _houses_from_addresses,
                                  _off_the_road)  # noqa: F401
from .rendering.infill import _back_sheds, _infill_frontage
from .rendering.furniture import (CRACK_SHARE, DRAIN_EVERY,
                                  EDGE_LINE_MIN_WIDTH, GRIME_SHARE,
                                  HYDRANT_EVERY, LAMP_EVERY, LITTER_SHARE,
                                  ROAD_FURNITURE_INTERVALS, SPEED_BY_WIDTH,
                                  SPEED_SIGN_EVERY, _mod_tiles_ready,
                                  _paint_street_furniture)  # noqa: F401
from .rendering.geometry import (_draw_line, _draw_roads, _draw_polygon, _feature_coords_px,
                                 _is_polygon, _paint_multipolygon,
                                 _pixel_width)  # noqa: F401
from .rendering.gridangle import (ALIGN_MIN_STRENGTH, DISTRICT_CELL_M,
                                  DISTRICT_CLUSTER_DEG, DISTRICT_MIN_ROAD_M,
                                  GRID_ROADS, _grid_delta, dominant_road_angle)  # noqa: F401
from .rendering.landcover import (AREA_CATEGORIES, DENSE_COVERAGE,
                                  GREEN_CATEGORIES, LANDSCAPE_FILL,
                                  LANDSCAPE_ORDER, VEG_CATEGORIES,
                                  WATERWAY_WIDTH_M, paint_markers,
                                  grid_for_map, refine_owned, resized_grid,
                                  settle_markers)  # noqa: F401
from .rendering.fields import paint_fields, paint_pools, paint_rocks
from .rendering.homesteads import clear_homesteads, keep_yards_clear
from .rendering.landcover_veg import plant_landcover
from .rendering.outputs import (AREA_TAGS, LINE_TAGS, OPENING_PATHS,
                                _areas_geojson, _build_preview,
                                _build_spawn_map, _lines_geojson,
                                _openings_geojson, _places)  # noqa: F401
from .rendering.projection import (Projector, _ceil_to, _inside, cover_bbox,
                                   shape_px)  # noqa: F401
from .rendering.roads import (_paint_road_details, _pave_dense_ground,
                              _real_kerbs, _road_hierarchy_image,
                              _smooth_road_edges, _weather_roads,
                              paint_rails)  # noqa: F401
from .rendering.sea import sea_polygons  # noqa: F401
from .rendering.shape import THROUGH_ROADS, _clip_to_shape  # noqa: F401
from .rendering.vegetation import (BOX_STRIP_ROWS, GARDEN_CLEAR_OF_HOUSE,
                                   GARDEN_CLEAR_OF_PAVING, GARDEN_REACH_TILES,
                                   GARDEN_TREE_CHANCE, GARDEN_TREE_EVERY,
                                   GRASS_COLOURS, LONG_GRASS_SHARE,
                                   PARK_EDGE_M, SHORT_GRASS_SHARE, SHRUB_CHANCE,
                                   WILD_BUSH_SHARE, WILD_CLEAR_OF_PAVING,
                                   WILD_CLUMP_M, WILD_GROUND, WILD_TREE_CHANCE,
                                   WILD_TREE_EVERY_M, _box_any,
                                   _clear_building_vegetation,
                                   _clear_road_vegetation, _paint_gardens,
                                   _paint_groves, _paint_parks, _paint_vegetation,
                                   _paint_vegetation_extras, _paint_wild_growth,
                                   _paint_woodland, _plant_big_trees,
                                   tree_rules_ready)  # noqa: F401
from .rendering.widths import (ROAD_WIDTHS_BY_HIERARCHY_M, ROAD_WIDTHS_M,
                               SIDEWALK_BY_HIERARCHY_M, SIDEWALK_M,
                               VERGE_BY_HIERARCHY_M, VERGE_M, _road_markings,
                               _sidewalk_width_m, _verge_width_m, _way_width_m)  # noqa: F401


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


_log = logging.getLogger("knoxmap.renderer")


# The Road layout setting (straight_roads) past Knox County's straight runs (1):
# routed on vanilla's lattice (roadgraph/modes.py).
ROAD_LAYOUTS = {2: "graph", 3: "cost"}


# Ground tint multipliers per NOAA climate class: a gentle shift, never a
# repaint. Project Zomboid's art is Kentucky-themed, so this only leans it.
CLIMATE_TINT = {
    "arid": (1.10, 1.02, 0.80),
    "cold continental": (0.95, 1.00, 1.06),
    "humid": (0.95, 1.04, 0.95),
    "temperate": (1.0, 1.0, 1.0),
}
_WINTER_GROUND = (210, 214, 218)


def _colour_mask(ground, colours) -> "np.ndarray":
    """Which pixels of `ground` are one of `colours`."""
    mask = np.zeros(ground.shape[:2], dtype=bool)
    for colour in colours:
        mask |= np.all(ground == np.array(colour, dtype=ground.dtype), axis=2)
    return mask


def _paint_climate(landscape: Image.Image, climate: dict,
                   winter_look: str = "auto") -> None:
    """Tint the ground for its real climate: dry, cold, lush or default."""
    import numpy as np

    climate = climate or {}
    klass = str(climate.get("class") or "").strip().lower()
    mult = CLIMATE_TINT.get(klass)
    cold = klass == "cold continental" or float(climate.get("jan_c") or 0) < -3
    winter = winter_look == "on" or (winter_look == "auto" and cold)
    if mult is None and not winter:
        return
    arr = np.asarray(landscape, dtype="float32")
    if mult:
        arr = arr * np.array(mult, dtype="float32")
    if winter:
        arr = arr * 0.80 + np.array(_WINTER_GROUND, dtype="float32") * 0.20
    landscape.paste(Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB"),
                    (0, 0))


MIN_RELIEF_M = 30.0
SNOW_RELIEF_M = 400.0


def _paint_relief(landscape: Image.Image, metres, span=None,
                  strength: float = 0.30) -> None:
    """Compressed relief: a hillshade and rock/snow bands, no z channel.

    The metres grid is one sample per tile (or a coarse DEM window); it is
    stretched to the ground image. Flat areas are left alone, so a map with
    no relief looks exactly as before.
    """
    import numpy as np

    m = np.asarray(metres, dtype="float32")
    if m.ndim != 2 or m.size == 0:
        return
    if (m.shape[1], m.shape[0]) != landscape.size:
        m = np.asarray(Image.fromarray(m).resize(landscape.size, Image.BILINEAR))
    if not np.isfinite(m).any():
        return
    lo, hi = span if span else (float(np.nanmin(m)), float(np.nanmax(m)))
    relief = float(hi) - float(lo)
    if relief < MIN_RELIEF_M:
        return
    m = np.nan_to_num(m, nan=float(np.nanmin(m)))
    # Hillshade from the north-west, so slopes read the way paper maps do.
    gy, gx = np.gradient(m)
    shade = -(gx + gy)
    scale = float(np.percentile(np.abs(shade), 95)) or 1.0
    shade = np.clip(shade / scale, -1.0, 1.0) * strength
    arr = np.asarray(landscape, dtype="float32") * (1.0 + shade[..., None])
    rock = m >= np.percentile(m, 75)
    arr[rock] = arr[rock] * 0.85 + np.array([120, 110, 96], "float32") * 0.15
    if relief >= SNOW_RELIEF_M:
        snow = m >= np.percentile(m, 92)
        arr[snow] = arr[snow] * 0.55 + np.array([238, 240, 244], "float32") * 0.45
    landscape.paste(Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB"),
                    (0, 0))


def _paint_climate_ground(landscape: Image.Image, climate: dict,
                          winter_look: str = "auto") -> None:
    """Shift grass palette colours for climate while keeping exact Rules.txt RGBs."""
    import numpy as np

    climate = climate or {}
    klass = str(climate.get("class") or "").strip().lower()
    cold = klass == "cold continental" or float(climate.get("jan_c") or 0) < -3
    winter = winter_look == "on" or (winter_look == "auto" and cold)
    if klass not in ("arid", "humid") and not winter:
        return
    arr = np.array(landscape, dtype="uint8", copy=True)
    dark = ((arr[:, :, 0] == C.DARK_GRASS[0])
            & (arr[:, :, 1] == C.DARK_GRASS[1])
            & (arr[:, :, 2] == C.DARK_GRASS[2]))
    med = ((arr[:, :, 0] == C.MEDIUM_GRASS[0])
           & (arr[:, :, 1] == C.MEDIUM_GRASS[1])
           & (arr[:, :, 2] == C.MEDIUM_GRASS[2]))
    light = ((arr[:, :, 0] == C.LIGHT_GRASS[0])
             & (arr[:, :, 1] == C.LIGHT_GRASS[1])
             & (arr[:, :, 2] == C.LIGHT_GRASS[2]))
    if klass == "arid":
        arr[dark] = C.MEDIUM_GRASS
        arr[med] = C.LIGHT_GRASS
        arr[light] = C.DIRT_GRASS
    elif klass == "humid":
        arr[light] = C.MEDIUM_GRASS
    if winter:
        arr[dark & ~med] = C.MEDIUM_GRASS
    landscape.paste(Image.fromarray(arr, "RGB"), (0, 0))


def _paint_relief_ground(landscape: Image.Image, metres, span=None) -> None:
    """Map relief bands to valid Rules.txt ground colours under OSM."""
    import numpy as np

    m = np.asarray(metres, dtype="float32")
    if m.ndim != 2 or m.size == 0:
        return
    if (m.shape[1], m.shape[0]) != landscape.size:
        m = np.asarray(Image.fromarray(m).resize(landscape.size, Image.BILINEAR))
    if not np.isfinite(m).any():
        return
    lo, hi = span if span else (float(np.nanmin(m)), float(np.nanmax(m)))
    relief = float(hi) - float(lo)
    if relief < MIN_RELIEF_M:
        return
    m = np.nan_to_num(m, nan=float(np.nanmin(m)))
    arr = np.array(landscape, dtype="uint8", copy=True)
    upper = m >= np.percentile(m, 65)
    rock = m >= np.percentile(m, 88)
    arr[upper] = C.MEDIUM_GRASS
    arr[rock] = C.GRAVEL_DIRT
    if relief >= SNOW_RELIEF_M:
        arr[m >= np.percentile(m, 95)] = C.LIGHT_GRASS
    landscape.paste(Image.fromarray(arr, "RGB"), (0, 0))


# OSM wetland that gets pools: marsh, swamp, bog, reed bed, or untyped. Not
# wet meadow, which is a field that floods.
POOL_WETLANDS = {None, "marsh", "swamp", "bog", "reedbed"}
# WorldCover classes relief may band: tree cover, shrubland, grassland,
# built-up - grass ground that stays grass.
RELIEF_CLASSES = (10, 20, 30, 50)


def _either(a, b):
    """The union of two optional bool masks."""
    if a is None:
        return b
    return a if b is None else a | b


def _polygon_mask(feats, proj):
    """Bool array, True inside any of the features' polygons."""
    mask = Image.new("L", (proj.width, proj.height), 0)
    draw = ImageDraw.Draw(mask)
    for feat in feats:
        if not _is_polygon(feat):
            continue
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                draw.polygon(ring, fill=255)
    return np.asarray(mask) > 0


def _paint_landcover(landscape: Image.Image, grid) -> None:
    """Paint the WorldCover base, one class per tile, under the OSM features.

    OSM is painted afterwards, so anything it knows wins; this only colours
    ground nothing else claimed.
    """
    import numpy as np

    from .rendering.landcover import WORLDCOVER_PAINT

    height, width = grid.shape
    rgb = np.zeros((height, width, 3), dtype="uint8")
    for code, colour in WORLDCOVER_PAINT.items():
        rgb[grid == code] = colour
    base = Image.fromarray(rgb, "RGB")
    if base.size != landscape.size:
        base = base.resize(landscape.size, Image.NEAREST)
    landscape.paste(base, (0, 0))


def render(features: Iterable[OSMFeature], south: float, west: float,
           north: float, east: float, meters_per_tile: float,
           output_dir: str, map_name: str,
           spawn_density: int = 10,
           tree_density: float = 1.0,
           forest_density: float = 1.0,
           rotation: float = 0.0,
           osm_cache: str | None = None,
           osm_bbox: tuple[float, float, float, float] | None = None,
           shape: dict | None = None,
           straight_roads: int = 4,
           include_proposed_roads: int = 0,
           fill_frontage: int = 0,
           terrain_only: int = 0,
           landcover_for=None,
           climate=None,
           winter_look: str = "auto",
           elevation=None,
           elevation_span=None,
           should_stop=None, progress=None) -> RenderResult:
    proj = Projector.build(south, west, north, east, meters_per_tile, rotation)
    # Read more than once below - the buildings pass goes back over the
    # address points - so never leave this as a generator.
    features = list(features)
    road_layout = int(straight_roads or 0)
    if road_layout in (1, 4):
        # Every road in straight runs at 45-degree steps (octilinear.py).
        from .octilinear import straighten_roads
        straighten_roads(features, proj, classify, _is_polygon, clean=True)
    elif road_layout in ROAD_LAYOUTS:
        # Routed on vanilla's lattice (roadgraph/route.py), and saved: Build and
        # the paper map read the roads back rather than routing them again.
        from .octilinear import apply_road_graph, graph_path
        from .roadgraph.route import route

        def tick(done, total):
            knoxstop.check(should_stop, "the roads")
            if progress:
                progress(done, total)
        graph = route(features, proj, ROAD_LAYOUTS[road_layout], shape, tick=tick)
        knoxfiles.write(graph_path(output_dir, map_name), graph)
        apply_road_graph(features, graph, proj)
    # A drawn polygon, circle or real outline rather than a rectangle: the map
    # still covers its bounding box in whole cells, but only what lies inside
    # the shape is built.
    clip = shape_px(shape, proj)
    landscape = Image.new("RGB", (proj.width, proj.height), C.DARK_GRASS)
    landcover_grid = None
    if landcover_for is not None:
        # Optional WorldCover ground under everything OSM paints (knoxdata),
        # in marker colours until OSM has painted, so what OSM left blank can
        # be told apart (generator/rendering/landcover.py).
        try:
            # What the image covers, turned with the map if it is turned.
            landcover_grid = grid_for_map(landcover_for, proj)
            if landcover_grid is not None:
                landcover_grid = resized_grid(landcover_grid, landscape.size)
                paint_markers(landscape, landcover_grid)
        except Exception as exc:        # noqa: BLE001 - optional, never fatal
            _log.warning("worldcover skipped: %s: %s", type(exc).__name__, exc)
            landcover_grid = None
    if elevation is not None and landcover_grid is None:
        # Optional 3DEP relief (knoxdata): compressed into the ground under
        # OSM, since Project Zomboid's outdoor ground is flat by format.
        try:
            _paint_relief_ground(landscape, elevation, elevation_span)
        except Exception:               # noqa: BLE001 - optional, never fatal
            pass
    vegetation = Image.new("RGB", (proj.width, proj.height), C.VEG_NOTHING)
    l_draw = ImageDraw.Draw(landscape)

    # Bucket features so we paint in a deterministic order.
    buckets: dict[str, list[OSMFeature]] = {}
    vegetation_feats: list[OSMFeature] = []
    building_feats: list[OSMFeature] = []
    indoor_feats: list[OSMFeature] = []
    fence_feats: list[OSMFeature] = []
    gate_feats: list[OSMFeature] = []
    place_feats: list[OSMFeature] = []
    monument_feats: list[OSMFeature] = []
    for feat in features:
        # Fences and hedges are collected from any outline that carries one,
        # before and independently of what the outline is: the fence around a
        # schoolyard is still a fence when the way is also the schoolyard.
        if feat.kind == "node" and "population" in feat.tags and "place" in feat.tags:
            place_feats.append(feat)
            continue
        if structures.monument_kind(feat.tags):
            monument_feats.append(feat)
        if feat.kind == "node" and feat.tags.get("barrier") in GATE_BARRIERS:
            gate_feats.append(feat)
        if feat.kind == "node" and "natural" not in feat.tags:
            continue      # shops and cafes inside buildings: knoxbuild/uses.py
        # Rooms a mapper drew inside a building. classify() has no colour for
        # them - they are walls, not ground - so they are taken aside here and
        # attached to their building when the geojson is written.
        if feat.kind == "way" and feat.tags.get("indoor") in ("room", "corridor"):
            indoor_feats.append(feat)
            continue
        barrier = feat.tags.get("barrier")
        if barrier in FENCE_BARRIERS and feat.kind == "way":
            fence_feats.append(feat)
        elif barrier == "hedge" and feat.kind == "way":
            vegetation_feats.append(feat)
        cat = classify(feat.tags, _is_polygon(feat))
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

    # Bridges lifted over the roads they cross, and monuments. See
    # generator/structures.py; what they leave out of the ground is cut here.
    lifted = structures.Plan()
    structures.plan_bridges(buckets, proj, meters_per_tile, _way_width_m, lifted)
    structures.plan_piers(buckets, proj, meters_per_tile, _way_width_m, lifted)
    structures.plan_monuments(monument_feats, proj, meters_per_tile, lifted)
    if lifted.not_buildings:
        building_feats = [f for f in building_feats if id(f) not in lifted.not_buildings]
        buckets["building"] = [f for f in buckets.get("building", [])
                               if id(f) not in lifted.not_buildings]

    # Streets where every home is an address point and not a drawn building.
    infilled: list[OSMFeature] = []
    sheds: list[OSMFeature] = []
    if terrain_only:
        building_feats = []
        buckets["building"] = []
    else:
        addressed = _houses_from_addresses(features, building_feats, proj)
        if addressed:
            building_feats = building_feats + addressed
            buckets["building"] = buckets.get("building", []) + addressed

        # Buildings for the gaps in a row, from the ones beside them
        # (generator/rendering/infill.py). After the addresses, so a numbered
        # house that was just put down is a neighbour like any other.
        if fill_frontage:
            infilled = _infill_frontage(
                buckets, vegetation_feats, building_feats,
                proj, clip, extend_ends=(int(fill_frontage) != 2))
            if infilled:
                building_feats = building_feats + infilled
                buckets["building"] = buckets.get("building", []) + infilled
        # A shed or garage behind some of the houses, whether or not the gaps are
        # filled: a yard has one either way.
        sheds = _back_sheds(buckets, vegetation_feats, building_feats, proj, clip)
        if sheds:
            building_feats = building_feats + sheds
            buckets["building"] = buckets.get("building", []) + sheds

    def ground_rings(feat: OSMFeature) -> list[list[tuple[float, float]]]:
        rings = _feature_coords_px(feat, proj)
        cut = lifted.cut.get(id(feat))
        if cut is None:
            return rings
        from shapely.geometry import LineString as _Line
        left = _Line(rings[0]).difference(cut)
        return [list(g.coords) for g in getattr(left, "geoms", [left])
                if g.geom_type == "LineString" and not g.is_empty]

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
            for fill, is_sidewalk in ((C.PALE_CONCRETE, True),
                                      (C.DARK_GRASS, False)):
                strokes = []
                for road in ("road_service", "road_minor", "road_medium", "road_major"):
                    for feat in buckets.get(road, []):
                        if _is_polygon(feat):
                            continue
                        w_road = _pixel_width(_way_width_m(feat, road), meters_per_tile)
                        v_m = _verge_width_m(feat, road)
                        verge_side = max(1, int(v_m / meters_per_tile + 0.49)) if v_m > 0 else 0
                        if not is_sidewalk:
                            if verge_side <= 0:
                                continue
                            w_stroke = w_road + 2 * verge_side
                        else:
                            s_m = _sidewalk_width_m(feat, road)
                            if s_m <= v_m:
                                continue
                            pave_side = max(1, round((s_m - v_m) / meters_per_tile))
                            r_v = (w_road + 2 * verge_side - 1) / 2.0
                            r_s = r_v + pave_side
                            if int(r_s * 1.41421356) - int((r_v * 1.41421356) + 0.999999) + 1 < 4:
                                pave_side += 1
                            w_stroke = w_road + 2 * (verge_side + pave_side)
                        strokes.append((w_stroke, ground_rings(feat)))
                _draw_roads(landscape, strokes, fill)
        fill = LANDSCAPE_FILL.get(cat)
        if fill is None:
            continue
        if cat in ROAD_WIDTHS_M:
            strokes = [(_pixel_width(_way_width_m(feat, cat), meters_per_tile), ground_rings(feat))
                       for feat in buckets.get(cat, []) if not _is_polygon(feat)]
            _draw_roads(landscape, strokes, fill)
        for feat in buckets.get(cat, []):
            if cat == "railway" and not _is_polygon(feat):
                continue  # the continuous track pass supplies its own ballast
            rings = _feature_coords_px(feat, proj)
            if cat in ROAD_WIDTHS_M and not _is_polygon(feat):
                continue  # Painted together so split ways share the same beveled join.
            elif feat.kind == "relation":
                _paint_multipolygon(landscape, feat, proj, fill)
            elif _is_polygon(feat):
                _draw_polygon(l_draw, rings, fill)
            else:
                # A river or canal mapped only as its centre line.
                metres = WATERWAY_WIDTH_M.get(feat.tags.get("waterway"), 3.0)
                _draw_line(l_draw, rings, fill, _pixel_width(metres, meters_per_tile))

    # Track and ballast share the same continuous route.
    paint_rails(l_draw, buckets, proj, should_stop)

    # Bridges over water squared to the tiles (generator/structures.py).
    for deck, cat in lifted.straight:
        l_draw.rectangle(deck.bounds, fill=LANDSCAPE_FILL.get(cat, C.MEDIUM_ASPHALT))
    owned = None
    if landcover_grid is not None:
        # OSM has painted: what is still a marker is WorldCover's.
        owned = settle_markers(landscape, landcover_grid)
        # Woods and scrub OSM maps paint no ground, only trees, so they are
        # claimed here.
        owned &= ~_polygon_mask(
            [f for f in vegetation_feats
             if classify(f.tags, _is_polygon(f)) in {"forest", "scrub"}], proj)
    # No field or lake under a building or in its yard: WorldCover's 10 m grid
    # does not know the farmyard is there (generator/rendering/homesteads.py).
    footprints = [ring for f in building_feats if _is_polygon(f)
                  for ring in _feature_coords_px(f, proj) if len(ring) >= 3]
    yards = None
    try:
        yards = keep_yards_clear(landscape, landcover_grid, owned, footprints,
                                 proj.meters_per_tile)
    except Exception as exc:            # noqa: BLE001 - never lose a map to it
        _log.warning("building yards skipped: %s: %s", type(exc).__name__, exc)
    _pave_dense_ground(landscape, building_feats, buckets, proj)
    for paved in lifted.paving:
        l_draw.polygon(list(paved.exterior.coords), fill=C.PAVING)
    if clip is not None:
        _clip_to_shape(landscape, clip, buckets, proj)
    _weather_roads(landscape, proj)
    if owned is not None:
        refine_owned(landscape, landcover_grid, owned)
        if elevation is not None:
            # Relief bands the ground OSM left blank, as it does the whole
            # ground without WorldCover - but only the grassy classes: its
            # bands are flat ground colours, and would turn a hillside lake,
            # marsh or rock field into grass, and cropland past being
            # ploughed (fields only take light grass).
            try:
                banded = landscape.copy()
                _paint_relief_ground(banded, elevation, elevation_span)
                grassy = owned & np.isin(landcover_grid, RELIEF_CLASSES)
                landscape.paste(banded, (0, 0),
                                Image.fromarray(grassy.astype("uint8") * 255))
            except Exception:           # noqa: BLE001 - optional, never fatal
                pass

    # Ground that is more than a colour: fields on farmland and cropland, rock
    # fields on bare ground (generator/rendering/fields.py).
    try:
        farm_rings = [ring for f in buckets.get("farmland", [])
                      if f.tags.get("landuse") == "farmland" and _is_polygon(f)
                      for ring in _feature_coords_px(f, proj) if len(ring) >= 3]
        cropland = owned & (landcover_grid == 40) if owned is not None else None
        paint_fields(landscape, vegetation, proj, farm_rings, cropland, blocked=yards)
        if owned is not None:
            paint_rocks(landscape, vegetation, proj, landcover_grid, owned)
    except Exception as exc:            # noqa: BLE001 - never lose a map to it
        _log.warning("fields skipped: %s: %s", type(exc).__name__, exc)
    forest = None
    if owned is not None:
        try:
            forest, _counts = plant_landcover(vegetation, landscape, landcover_grid,
                                              owned, proj, density=tree_density)
        except Exception as exc:        # noqa: BLE001 - optional, never fatal
            _log.warning("worldcover planting skipped: %s: %s", type(exc).__name__, exc)
            owned = None

    knoxstop.check(should_stop, "the terrain")
    # The woods the mapper drew take both dials; the gardens and the scrub
    # over open ground take the overall one only.
    _paint_vegetation(vegetation, landscape, vegetation_feats, proj,
                      density=tree_density * forest_density, should_stop=should_stop,
                      extra_forest=forest)
    # A building in the woods gets a clearing and a drive to the road.
    homes = None
    try:
        drive_roads = [line for road in ("road_service", "road_minor", "road_medium",
                                         "road_major")
                       for f in buckets.get(road, []) if not _is_polygon(f)
                       for line in _feature_coords_px(f, proj) if len(line) >= 2]
        homes, _home_counts = clear_homesteads(vegetation, landscape, footprints,
                                               drive_roads, proj.meters_per_tile)
    except Exception as exc:            # noqa: BLE001 - never lose a map to it
        _log.warning("clearings skipped: %s: %s", type(exc).__name__, exc)
    # Pools in the marsh, after its reeds (generator/rendering/fields.py).
    try:
        wet = _polygon_mask([f for f in buckets.get("wetland", [])
                             if f.tags.get("wetland") in POOL_WETLANDS], proj)
        if owned is not None:
            wet |= owned & np.isin(landcover_grid, (90, 95))
        if wet.any():
            paint_pools(landscape, vegetation, proj, wet,
                        _polygon_mask(building_feats, proj))
    except Exception as exc:            # noqa: BLE001 - never lose a map to it
        _log.warning("pools skipped: %s: %s", type(exc).__name__, exc)
    _paint_parks(vegetation, landscape, buckets.get("park", []), proj,
                 density=tree_density)
    _paint_gardens(vegetation, landscape, building_feats, proj, density=tree_density)
    # Where WorldCover has a class, it says what grows; elsewhere, a guess.
    _paint_wild_growth(vegetation, landscape, proj, density=tree_density,
                       exclude=_either(owned, homes))
    # Made-up woods only stand in for land cover data: with WorldCover the
    # woods are the real ones, and a random one would only add woods where
    # the data says there are none. They still grow where it has no data.
    _paint_groves(vegetation, landscape, proj, density=tree_density * forest_density,
                  exclude=_either(None if owned is None else landcover_grid > 0, homes))
    # Last of the planting: some of the trees now down become the big ones,
    # which need a square of their own and so can only be chosen once it is
    # settled what stands where.
    _plant_big_trees(vegetation, landscape, vegetation_feats,
                     buckets.get("park", []), building_feats, proj,
                     density=tree_density)
    _clear_building_vegetation(vegetation, building_feats, proj)
    _clear_road_vegetation(vegetation, landscape)
    _paint_road_details(vegetation, landscape, buckets, proj)
    hierarchy_image = _road_hierarchy_image(buckets, proj)
    # Where the buildings are, so a hydrant, a bin or a mailbox only stands
    # where it has something to serve.
    building_mask = Image.new("L", (proj.width, proj.height), 0)
    mask_draw = ImageDraw.Draw(building_mask)
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                mask_draw.polygon(ring, fill=255)
    _paint_street_furniture(vegetation, landscape, hierarchy_image, building_mask)
    # The last word on the ground edge belongs to the smoother: a lamp's square
    # and the passes after the road details can leave a verge square standing
    # between two pavements, which in the game is a lawn in the sidewalk.
    _smooth_road_edges(landscape, (C.MEDIUM_ASPHALT, C.DARK_ASPHALT,
                                   C.DARKEST_ASPHALT, C.DARK_POTHOLE,
                                   C.LIGHT_POTHOLE),
                       _colour_mask)
    _clear_road_vegetation(vegetation, landscape)
    # Nothing grows through a deck or a ramp, and no lamp stands on one.
    veg_px = vegetation.load()
    for x, y in lifted.clear_veg:
        if 0 <= x < proj.width and 0 <= y < proj.height:
            veg_px[x, y] = C.VEG_NOTHING
    structures.rail_water(lifted, landscape, C.WATER)
    ground_px = landscape.load()
    under = {C.WATER, C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
             C.LIGHT_ASPHALT, C.PALE_CONCRETE}
    structures.settle_posts(lifted, lambda x, y: 0 <= x < proj.width and 0 <= y < proj.height
                            and ground_px[x, y] not in under)

    if climate:
        # Optional NOAA climate tint (knoxdata): after the ground is drawn, so
        # it leans everything, and only when the layer actually ran.
        try:
            _paint_climate_ground(landscape, climate, winter_look)
        except Exception:               # noqa: BLE001 - optional, never fatal
            pass

    # --- zombie spawn map (10x smaller, grayscale) ---
    spawn_w = proj.width // C.SPAWN_MAP_SCALE
    spawn_h = proj.height // C.SPAWN_MAP_SCALE
    spawn_map = _build_spawn_map(landscape, spawn_w, spawn_h, spawn_density)

    # --- preview (landscape + vegetation blended) ---
    preview = _build_preview(landscape, vegetation)
    if elevation is not None:
        try:
            _paint_relief(preview, elevation, elevation_span)
        except Exception:               # noqa: BLE001 - optional, never fatal
            pass
    if climate:
        try:
            _paint_climate(preview, climate, winter_look)
        except Exception:               # noqa: BLE001 - optional, never fatal
            pass

    # --- output files ---
    os.makedirs(output_dir, exist_ok=True)
    landscape_path = os.path.join(output_dir, f"{map_name}.bmp")
    veg_path = os.path.join(output_dir, f"{map_name}_veg.bmp")
    road_hierarchy_path = os.path.join(output_dir, f"{map_name}_road_hierarchy.bmp")
    spawn_path = os.path.join(output_dir, f"{map_name}_ZombieSpawnMap.bmp")
    preview_path = os.path.join(output_dir, f"{map_name}_preview.png")
    buildings_path = os.path.join(output_dir, f"{map_name}_buildings.geojson")
    meta_path = os.path.join(output_dir, f"{map_name}_info.json")

    # Every one of these is written beside itself and moved into place
    # (knoxfiles.py). A map's ground is hundreds of megabytes and the window
    # can be closed while it is going down, which used to leave half a file
    # that the build then read as the map.
    knoxfiles.save(landscape, landscape_path, format="BMP")
    knoxfiles.save(vegetation, veg_path, format="BMP")
    knoxfiles.save(hierarchy_image, road_hierarchy_path, format="BMP")
    # The ground as drawn, before knoxbuild paints front paths into it
    # (knoxbuild/yards.py), so building again starts from clean ground.
    knoxfiles.save(landscape, os.path.join(output_dir, f"{map_name}_ground_base.bmp"),
                   format="BMP")
    knoxfiles.save(vegetation, os.path.join(output_dir, f"{map_name}_veg_base.bmp"),
                   format="BMP")
    knoxfiles.save(spawn_map, spawn_path, format="BMP")
    knoxfiles.save(preview, preview_path, format="PNG")

    knoxfiles.write(buildings_path, _buildings_geojson(building_feats, indoor_feats))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_areas.geojson"),
                    _areas_geojson(buckets))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_fences.geojson"),
                    _lines_geojson([f for f in fence_feats
                                    if clip is None or _inside(f, proj, clip)]))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_fence_openings.geojson"),
                    _openings_geojson(gate_feats, buckets))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_structures.json"),
                    {"bridges": lifted.bridges, "monuments": lifted.monuments,
                     "tiles": lifted.rows()})
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_places.json"),
                    _places(place_feats, proj), ensure_ascii=False)

    cells_x, cells_y = proj.cell_grid()
    # Last of the lot on purpose: the build looks for <name>_info.json to know
    # there is a map here at all, so it appears once everything beside it has.
    knoxfiles.write(meta_path, {
        "map_name": map_name,
        "bbox": {"south": south, "west": west, "north": north, "east": east},
        "rotation": rotation,
        "osm_cache": osm_cache,
        "straight_roads": road_layout,
        "include_proposed_roads": include_proposed_roads,
        "osm_bbox": list(osm_bbox) if osm_bbox else None,
        "shape": shape,
        "meters_per_tile": meters_per_tile,
        "width_tiles": proj.width,
        "height_tiles": proj.height,
        "cells_x": cells_x,
        "cells_y": cells_y,
        "spawn_density_max": spawn_density,
        "building_count": len(building_feats),
        "feature_count": sum(len(v) for v in buckets.values()),
        # How many homes came from an address with no building drawn for
        # it, so "it made none of mine" is a number rather than a guess.
        "houses_from_addresses": len(addressed),
        # And how many were put into gaps along a street.
        "houses_infilled": len(infilled),
        "sheds_infilled": len(sheds),
        "guide_reference": "Thuztor Mapping Guide v0.2",
    }, indent=2)

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
