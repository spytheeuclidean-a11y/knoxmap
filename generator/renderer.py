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

import os
from dataclasses import dataclass
from typing import Iterable

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
from .rendering.furniture import (CRACK_SHARE, DRAIN_EVERY,
                                  EDGE_LINE_MIN_WIDTH, GRIME_SHARE,
                                  HYDRANT_EVERY, LAMP_EVERY, LITTER_SHARE,
                                  ROAD_FURNITURE_INTERVALS, SPEED_BY_WIDTH,
                                  SPEED_SIGN_EVERY, _mod_tiles_ready,
                                  _paint_street_furniture)  # noqa: F401
from .rendering.geometry import (_draw_line, _draw_polygon, _feature_coords_px,
                                 _is_polygon, _paint_multipolygon,
                                 _pixel_width)  # noqa: F401
from .rendering.gridangle import (ALIGN_MIN_STRENGTH, DISTRICT_CELL_M,
                                  DISTRICT_CLUSTER_DEG, DISTRICT_MIN_ROAD_M,
                                  GRID_ROADS, _grid_delta, dominant_road_angle)  # noqa: F401
from .rendering.landcover import (AREA_CATEGORIES, DENSE_COVERAGE,
                                  GREEN_CATEGORIES, LANDSCAPE_FILL,
                                  LANDSCAPE_ORDER, VEG_CATEGORIES,
                                  WATERWAY_WIDTH_M)  # noqa: F401
from .rendering.outputs import (AREA_TAGS, LINE_TAGS, OPENING_PATHS,
                                _areas_geojson, _build_preview,
                                _build_spawn_map, _lines_geojson,
                                _openings_geojson, _places)  # noqa: F401
from .rendering.projection import (Projector, _ceil_to, _inside, cover_bbox,
                                   shape_px)  # noqa: F401
from .rendering.roads import (_paint_road_details, _pave_dense_ground,
                              _real_kerbs, _road_hierarchy_image,
                              _smooth_road_edges, _weather_roads)  # noqa: F401
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
                                   _paint_parks, _paint_vegetation,
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


# The Road layout setting (straight_roads) past Knox County's straight runs (1):
# routed on vanilla's lattice (roadgraph/modes.py).
ROAD_LAYOUTS = {2: "graph", 3: "cost"}


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
           straight_roads: int = 1,
           should_stop=None, progress=None) -> RenderResult:
    proj = Projector.build(south, west, north, east, meters_per_tile, rotation)
    # Read more than once below - the buildings pass goes back over the
    # address points - so never leave this as a generator.
    features = list(features)
    road_layout = int(straight_roads or 0)
    if road_layout == 1:
        # Every road in straight runs at 45-degree steps (octilinear.py).
        from .octilinear import straighten_roads
        straighten_roads(features, proj, classify, _is_polygon)
    elif road_layout >= 2:
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
    addressed = _houses_from_addresses(features, building_feats, proj)
    if addressed:
        building_feats = building_feats + addressed
        buckets["building"] = buckets.get("building", []) + addressed

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
            for road in ("road_service", "road_minor", "road_medium", "road_major"):
                for feat in buckets.get(road, []):
                    if _is_polygon(feat):
                        continue
                    margin = _sidewalk_width_m(feat, road)
                    width_px = _pixel_width(_way_width_m(feat, road) + 2 * margin,
                                            meters_per_tile)
                    _draw_line(l_draw, ground_rings(feat),
                               C.PALE_CONCRETE, width_px)
            for road in ("road_service", "road_minor", "road_medium", "road_major"):
                for feat in buckets.get(road, []):
                    if _is_polygon(feat):
                        continue
                    verge = _verge_width_m(feat, road)
                    width_px = _pixel_width(_way_width_m(feat, road) + 2 * verge,
                                            meters_per_tile)
                    _draw_line(l_draw, ground_rings(feat),
                               C.DARK_GRASS, width_px)
        fill = LANDSCAPE_FILL.get(cat)
        if fill is None:
            continue
        for feat in buckets.get(cat, []):
            rings = _feature_coords_px(feat, proj)
            if cat in ROAD_WIDTHS_M and not _is_polygon(feat):
                width_px = _pixel_width(_way_width_m(feat, cat), meters_per_tile)
                _draw_line(l_draw, ground_rings(feat), fill, width_px)
            elif feat.kind == "relation":
                _paint_multipolygon(landscape, feat, proj, fill)
            elif _is_polygon(feat):
                _draw_polygon(l_draw, rings, fill)
            else:
                # A river or canal mapped only as its centre line.
                metres = WATERWAY_WIDTH_M.get(feat.tags.get("waterway"), 3.0)
                _draw_line(l_draw, rings, fill, _pixel_width(metres, meters_per_tile))

    # Bridges over water squared to the tiles (generator/structures.py).
    for deck, cat in lifted.straight:
        l_draw.rectangle(deck.bounds, fill=LANDSCAPE_FILL.get(cat, C.MEDIUM_ASPHALT))
    _pave_dense_ground(landscape, building_feats, buckets, proj)
    for paved in lifted.paving:
        l_draw.polygon(list(paved.exterior.coords), fill=C.PAVING)
    if clip is not None:
        _clip_to_shape(landscape, clip, buckets, proj)
    _weather_roads(landscape, proj)

    knoxstop.check(should_stop, "the terrain")
    # The woods the mapper drew take both dials; the gardens and the scrub
    # over open ground take the overall one only.
    _paint_vegetation(vegetation, landscape, vegetation_feats, proj,
                      density=tree_density * forest_density)
    _paint_parks(vegetation, landscape, buckets.get("park", []), proj,
                 density=tree_density)
    _paint_gardens(vegetation, landscape, building_feats, proj, density=tree_density)
    _paint_wild_growth(vegetation, landscape, proj, density=tree_density)
    # Last of the planting: some of the trees now down become the big ones,
    # which need a square of their own and so can only be chosen once it is
    # settled what stands where.
    _plant_big_trees(vegetation, landscape, vegetation_feats,
                     buckets.get("park", []), building_feats, proj,
                     density=tree_density)
    _clear_building_vegetation(vegetation, building_feats, proj)
    _clear_road_vegetation(vegetation, landscape)
    _paint_road_details(vegetation, landscape, buckets, proj)
    road_hierarchy = _road_hierarchy_image(buckets, proj)
    _paint_street_furniture(vegetation, landscape, road_hierarchy)
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
    knoxfiles.save(road_hierarchy, road_hierarchy_path, format="BMP")
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
