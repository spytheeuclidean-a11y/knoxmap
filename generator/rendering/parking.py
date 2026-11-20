"""Square ragged/angled OSM parking lot polygons onto PZ's tile grid.

OpenStreetMap parking lots are frequently traced loosely around parked cars or
aligned to angled streets, which paints dark tarmac onto the tile bitmap as
irregular diagonal splotches and cuts off orthogonal stall rows. Replacing
compact lots with area-matched axis-aligned rectangles and quantising multi-wing
or long diagonal lots onto coarse orthogonal bays makes every parking lot crisp
without spilling onto buildings or street sidewalks.
"""
from __future__ import annotations

import math

from ..osm import OSMFeature
from .projection import Projector
from .widths import (_sidewalk_width_m, _verge_width_m, road_width_tiles)

MIN_LOT_AREA = 9.0          # tiles^2; skip tiny noise scraps
MIN_SIDE = 4                # narrowest squared lot dimension (tiles)
COMPACT_MRR_FILL = 0.62     # below this, lot has multiple wings (L / U shape)
AXIS_ALIGNED_FILL = 0.90    # already an orthogonal rectangle
MAX_SINGLE_ANGLE_DEG = 35.0
MAX_SINGLE_ASPECT = 2.8
MAX_SINGLE_LEN = 48.0
COARSE_CELL = 8             # bay step (tiles) for L/U shapes and long diagonals
CELL_FILL_SHARE = 0.45
MIN_FRAGMENT_AREA = 16.0
MIN_FRAGMENT_SHARE = 0.08
ROAD_CATEGORIES = ("road_minor", "road_medium", "road_major")


def _poly_parts(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom] if geom.area > 0 else []
    out = []
    for part in getattr(geom, "geoms", ()) or ():
        out.extend(_poly_parts(part))
    return out


def _feature_to_polygons(feat: OSMFeature, proj: Projector):
    """Return (outer_parts, inner_holes) in pixel coordinates for a parking feature."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    inners = []
    outers = []
    if feat.kind == "way":
        pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
        if len(pts) >= 3:
            poly = Polygon(pts)
            outers.extend(_poly_parts(poly if poly.is_valid else poly.buffer(0)))
    elif feat.kind == "relation":
        for role, ring in feat.role_geoms:
            if len(ring) < 3:
                continue
            pts = [proj.to_px(la, lo) for la, lo in ring]
            poly = Polygon(pts)
            parts = _poly_parts(poly if poly.is_valid else poly.buffer(0))
            if role == "inner":
                inners.extend(parts)
            else:
                outers.extend(parts)
    if not outers:
        return [], []
    outer_geom = unary_union(outers)
    if inners:
        inner_geom = unary_union(inners)
        outer_geom = outer_geom.difference(inner_geom)
    # Keep substantial interior holes (e.g. a courtyard/island >= 16 tiles^2)
    # squared to their bounding box so buildings/parks inside large lots stay clear.
    from shapely.geometry import box

    kept_holes = [
        box(int(round(h.bounds[0])), int(round(h.bounds[1])),
            int(round(h.bounds[2])), int(round(h.bounds[3])))
        for h in inners
        if h.area >= MIN_FRAGMENT_AREA
        and int(round(h.bounds[2])) > int(round(h.bounds[0]))
        and int(round(h.bounds[3])) > int(round(h.bounds[1]))
    ]
    return _poly_parts(outer_geom), kept_holes


def _square_compact(poly, width: int, height: int):
    """Square a single compact or tilted-rectangle parking polygon cleanly."""
    from shapely.geometry import box

    area = poly.area
    bx0, by0, bx1, by1 = poly.bounds
    bw, bh = bx1 - bx0, by1 - by0
    if area < MIN_LOT_AREA or bw < 2.0 or bh < 2.0:
        return poly

    if area / max(1e-6, bw * bh) >= AXIS_ALIGNED_FILL:
        rx0 = max(0, min(width - 1, int(round(bx0))))
        ry0 = max(0, min(height - 1, int(round(by0))))
        rx1 = max(rx0 + 1, min(width, int(round(bx1))))
        ry1 = max(ry0 + 1, min(height, int(round(by1))))
        return box(rx0, ry0, rx1, ry1)

    mrr = poly.minimum_rotated_rectangle
    if mrr.geom_type == "Polygon" and len(mrr.exterior.coords) >= 4:
        c = list(mrr.exterior.coords)
        e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
        e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
        d0, d1 = math.hypot(*e0), math.hypot(*e1)
        long_vec = e0 if d0 >= d1 else e1
        length, breadth = max(d0, d1), min(d0, d1)
        mrr_area = max(1e-6, length * breadth)
        mrr_fill = area / mrr_area
        along_x = abs(long_vec[0]) >= abs(long_vec[1])
        theta_deg = math.degrees(math.atan2(
            min(abs(long_vec[0]), abs(long_vec[1])),
            max(1e-9, max(abs(long_vec[0]), abs(long_vec[1]))),
        ))
        is_steep_strip = (
            theta_deg > MAX_SINGLE_ANGLE_DEG
            and length / max(1.0, breadth) > MAX_SINGLE_ASPECT
            and length > MAX_SINGLE_LEN
        )
        if mrr_fill >= COMPACT_MRR_FILL and not is_steep_strip:
            scale = math.sqrt(min(1.0, mrr_fill))
            len_px = max(MIN_SIDE, int(round(length * scale)))
            wid_px = max(MIN_SIDE, int(round(breadth * scale)))
            rw, rh = (len_px, wid_px) if along_x else (wid_px, len_px)
            rw = max(1, min(width, rw))
            rh = max(1, min(height, rh))
            cx, cy = poly.centroid.x, poly.centroid.y
            rx0 = max(0, min(width - rw, int(round(cx - rw / 2.0))))
            ry0 = max(0, min(height - rh, int(round(cy - rh / 2.0))))
            return box(rx0, ry0, rx0 + rw, ry0 + rh)

    return _square_coarse_bays(poly, width, height)


def _square_coarse_bays(poly, width: int, height: int):
    """Snap multi-wing (L/U) or long diagonal strips onto coarse orthogonal bays."""
    from shapely.geometry import box
    from shapely.ops import unary_union

    bx0, by0, bx1, by1 = poly.bounds
    x0 = max(0, int(round(bx0)))
    y0 = max(0, int(round(by0)))
    x1 = min(width, int(round(bx1)))
    y1 = min(height, int(round(by1)))
    if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
        return poly

    cells = []
    for gy in range(y0, y1, COARSE_CELL):
        cy1 = min(y1, gy + COARSE_CELL)
        for gx in range(x0, x1, COARSE_CELL):
            cx1 = min(x1, gx + COARSE_CELL)
            cell = box(gx, gy, cx1, cy1)
            if cell.area <= 0:
                continue
            overlap = poly.intersection(cell).area
            if overlap >= CELL_FILL_SHARE * cell.area:
                cells.append(cell)
    if not cells:
        return poly
    merged = unary_union(cells)
    parts = [p for p in _poly_parts(merged) if p.area >= MIN_FRAGMENT_AREA]
    if not parts:
        return poly
    return unary_union(parts)


def _road_corridor_half_width(feat: OSMFeature, cat: str, meters_per_tile: float) -> float:
    w_road = road_width_tiles(feat, cat, meters_per_tile)
    v_m = _verge_width_m(feat, cat)
    verge_side = max(1, int(v_m / meters_per_tile + 0.49)) if v_m > 0 else 0
    s_m = _sidewalk_width_m(feat, cat)
    if s_m > v_m:
        pave_side = max(1, round((s_m - v_m) / meters_per_tile))
        return w_road / 2.0 + verge_side + pave_side
    return w_road / 2.0 + verge_side


def _write_back_geometry(feat: OSMFeature, geom, proj: Projector) -> None:
    """Update `feat` coordinates in-place to match `geom` in lat/lon space."""
    parts = [p for p in _poly_parts(geom) if len(p.exterior.coords) >= 4]
    if not parts:
        return
    if len(parts) == 1 and not parts[0].interiors:
        ring = [proj.to_latlon(x, y) for x, y in parts[0].exterior.coords]
        feat.kind = "way"
        feat.geometry = ring
        feat.role_geoms = []
        return
    role_geoms = []
    for part in parts:
        role_geoms.append(("outer", [proj.to_latlon(x, y) for x, y in part.exterior.coords]))
        for hole in part.interiors:
            if len(hole.coords) >= 4:
                role_geoms.append(("inner", [proj.to_latlon(x, y) for x, y in hole.coords]))
    feat.kind = "relation"
    feat.geometry = []
    feat.role_geoms = role_geoms


def square_parking_lots(
    features: list[OSMFeature],
    proj: Projector,
    classify,
    is_polygon,
) -> int:
    """Replace ragged/angled parking polygons in `features` with crisp rectangular lots.

    Returns the number of parking features reshaped.
    """
    from shapely import STRtree
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    parking_items: list[OSMFeature] = []
    obstacles = []

    for feat in features:
        poly_flag = is_polygon(feat)
        cat = classify(feat.tags, poly_flag)
        if cat == "parking" and poly_flag:
            parking_items.append(feat)
        elif cat == "building" and poly_flag:
            if feat.kind == "way":
                pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
                if len(pts) >= 3:
                    p = Polygon(pts)
                    p = p if p.is_valid else p.buffer(0)
                    for part in _poly_parts(p):
                        obstacles.append(part.buffer(0.5))
            elif feat.kind == "relation":
                for role, ring in feat.role_geoms:
                    if role != "inner" and len(ring) >= 3:
                        p = Polygon([proj.to_px(la, lo) for la, lo in ring])
                        p = p if p.is_valid else p.buffer(0)
                        for part in _poly_parts(p):
                            obstacles.append(part.buffer(0.5))
        elif cat in ROAD_CATEGORIES and not poly_flag and len(feat.geometry) >= 2:
            pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
            hw = _road_corridor_half_width(feat, cat, proj.meters_per_tile)
            obstacles.append(LineString(pts).buffer(hw, cap_style="flat", join_style="mitre"))

    if not parking_items:
        return 0

    tree = STRtree(obstacles) if obstacles else None
    squared_count = 0

    for feat in parking_items:
        parts, kept_holes = _feature_to_polygons(feat, proj)
        if not parts:
            continue
        orig_area = sum(p.area for p in parts)
        if orig_area < MIN_LOT_AREA:
            continue

        squared_parts = [_square_compact(p, proj.width, proj.height) for p in parts]
        geom = unary_union(squared_parts)
        if kept_holes:
            geom = geom.difference(unary_union(kept_holes))
        if tree is not None and not geom.is_empty:
            hits = [obstacles[int(i)] for i in tree.query(geom)
                    if obstacles[int(i)].intersects(geom)]
            if hits:
                geom = geom.difference(unary_union(hits))

        kept = [
            p for p in _poly_parts(geom)
            if p.area >= max(MIN_FRAGMENT_AREA, orig_area * MIN_FRAGMENT_SHARE)
        ]
        if not kept:
            continue
        _write_back_geometry(feat, unary_union(kept), proj)
        squared_count += 1

    return squared_count
