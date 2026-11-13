"""Faithful OSM road cleaning for the "As mapped" road layout.

Raw OpenStreetMap ways often carry sub-tile digitization jitter, redundant
near-collinear nodes, and micro-kinks that rasterize into 1-tile staircase
teeth on Project Zomboid's 1 m tile grid. This pass cleans those artifacts in
pixel space while keeping every intersection, junction, and roundabout pinned
to its true mapped location.
"""
from __future__ import annotations

import math

from .osm import OSMFeature

ROAD_CATEGORIES = frozenset({
    "road_major", "road_medium", "road_minor", "road_service",
    "pedestrian", "paved_path", "dirt_path",
})

# Sub-tile jitter tolerance in tiles for Douglas-Peucker simplification.
SIMPLIFY_TOLERANCE_TILES = 0.6
LOOP_SIMPLIFY_TOLERANCE_TILES = 0.3
SMALL_LOOP_SPAN_TILES = 18.0
MAX_SMOOTH_SHIFT_TILES = 0.5


def _perp_dist(pt: tuple[float, float], a: tuple[float, float],
               b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return math.hypot(pt[0] - a[0], pt[1] - a[1])
    return abs(dx * (a[1] - pt[1]) - (a[0] - pt[0]) * dy) / length


def _douglas_peucker(pts: list[tuple[float, float]],
                     tol: float) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return list(pts)
    stack = [(0, len(pts) - 1)]
    keep = [False] * len(pts)
    keep[0] = True
    keep[-1] = True
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 <= 1:
            continue
        a, b = pts[i0], pts[i1]
        best_idx = -1
        best_dist = -1.0
        for i in range(i0 + 1, i1):
            d = _perp_dist(pts[i], a, b)
            if d > best_dist:
                best_dist = d
                best_idx = i
        if best_dist > tol and best_idx != -1:
            keep[best_idx] = True
            stack.append((i0, best_idx))
            stack.append((best_idx, i1))
    return [pt for pt, k in zip(pts, keep) if k]


def _smooth_micro_kinks(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Nudge gentle short-segment kinks toward the local chord, clamped <= 0.5 tiles."""
    if len(pts) < 3:
        return pts
    out = list(pts)
    for i in range(1, len(pts) - 1):
        ax, ay = out[i - 1]
        px, py = pts[i]
        bx, by = pts[i + 1]
        v1x, v1y = px - ax, py - ay
        v2x, v2y = bx - px, by - py
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 < 1e-6 or l2 < 1e-6 or min(l1, l2) >= 6.0:
            continue
        cos_t = (v1x * v2x + v1y * v2y) / (l1 * l2)
        if cos_t <= 0.75:
            continue
        mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
        dx, dy = (mx - px) * 0.5, (my - py) * 0.5
        shift = math.hypot(dx, dy)
        if shift > MAX_SMOOTH_SHIFT_TILES:
            scale = MAX_SMOOTH_SHIFT_TILES / shift
            dx *= scale
            dy *= scale
        out[i] = (px + dx, py + dy)
    return out


def _clean_stretch(pts: list[tuple[float, float]],
                   is_small_loop: bool = False) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return list(pts)
    tol = LOOP_SIMPLIFY_TOLERANCE_TILES if is_small_loop else SIMPLIFY_TOLERANCE_TILES
    simplified = _douglas_peucker(pts, tol)
    if is_small_loop:
        # Keep roundabouts round: do not collapse below 8 vertices if originally >= 8.
        if len(pts) >= 8 and len(simplified) < 8:
            return list(pts)
        return simplified
    return _smooth_micro_kinks(simplified)


def clean_mapped_roads(features: list[OSMFeature], proj, classify, is_polygon) -> int:
    """Clean OSM road centerlines in-place for the "As mapped" layout.

    Returns the number of road ways whose geometry was cleaned.
    """
    road_ways: list[tuple[OSMFeature, list[tuple[float, float]]]] = []
    node_degree: dict[tuple[float, float], int] = {}

    for feat in features:
        if feat.kind != "way" or is_polygon(feat) or len(feat.geometry) < 2:
            continue
        cat = classify(feat.tags)
        if cat not in ROAD_CATEGORIES:
            continue
        pts = [proj.to_px(lat, lon) for lat, lon in feat.geometry]
        road_ways.append((feat, pts))
        seen_in_way: set[tuple[float, float]] = set()
        for x, y in pts:
            key = (round(x, 2), round(y, 2))
            if key not in seen_in_way:
                seen_in_way.add(key)
                node_degree[key] = node_degree.get(key, 0) + 1

    cleaned_count = 0
    for feat, pts in road_ways:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.2
        small_loop = (
            closed
            and max(max(xs) - min(xs), max(ys) - min(ys)) < SMALL_LOOP_SPAN_TILES
        )

        # Pin endpoints and any vertex shared by 2+ ways so intersections stay exact.
        pinned = {0, len(pts) - 1}
        for i, (x, y) in enumerate(pts):
            if node_degree.get((round(x, 2), round(y, 2)), 0) >= 2:
                pinned.add(i)
        pin_indices = sorted(pinned)

        new_pts: list[tuple[float, float]] = []
        for a_idx, b_idx in zip(pin_indices, pin_indices[1:]):
            stretch = pts[a_idx:b_idx + 1]
            cleaned_stretch = _clean_stretch(stretch, is_small_loop=small_loop)
            if new_pts:
                new_pts.extend(cleaned_stretch[1:])
            else:
                new_pts.extend(cleaned_stretch)

        if len(new_pts) >= 2 and new_pts != pts:
            feat.geometry = [proj.to_latlon(x, y) for x, y in new_pts]
            cleaned_count += 1

    return cleaned_count
