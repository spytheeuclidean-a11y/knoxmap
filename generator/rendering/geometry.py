"""Small geometry helpers and the pixel drawing primitives the passes share."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..osm import OSMFeature
from .projection import Projector


def _pixel_width(metres: float, metres_per_tile: float) -> int:
    """Convert a real width to the nearest whole bitmap tile, never zero."""
    return max(1, int(math.floor(metres / max(0.05, metres_per_tile) + 0.5)))


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


# A road that comes back to where it started is a ring road, a roundabout or a
# loop of lane - not a plot of ground. Filled as an area it paved everything
# inside it: a road drawn round a town, or a closed loop of roads, turned the
# whole town to tarmac. Only a mapper who says it is an area makes it one.
_LINEAR_HIGHWAYS = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary", "residential",
    "unclassified", "living_street", "service", "track", "path", "cycleway",
    "bridleway", "steps", "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link"})


def _is_polygon(feat: OSMFeature) -> bool:
    """Treat as polygon if first/last point match (way) or it's a relation -
    unless it is a road, which stays a line however it loops."""
    if feat.kind == "relation":
        return True
    if feat.kind == "way" and len(feat.geometry) >= 3:
        # Drawn on the map as a line, so a line it stays when it closes.
        if feat.tags.get("knox:line") == "yes":
            return False
        if (feat.geometry[0] == feat.geometry[-1]
                and feat.tags.get("highway") in _LINEAR_HIGHWAYS
                and feat.tags.get("area") != "yes"
                and "area:highway" not in feat.tags):
            return False
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


def _draw_roads(image: Image.Image, strokes, fill, crisp: bool = False) -> None:
    """Constant-width road strokes, joined across OSM ways with bevel or crisp mitre corners."""
    import numpy as np
    from shapely.geometry import LineString
    from shapely.ops import linemerge, unary_union

    groups = {}
    for width, rings in strokes:
        width = max(1, int(round(width)))
        for ring in rings:
            points = [(round(x, 6), round(y, 6)) for x, y in ring]
            if len(set(points)) > 1:
                groups.setdefault(width, []).append(points)
    scale = 4
    strip_h = 512
    for width, rings in groups.items():
        if width == 1:
            _draw_line(ImageDraw.Draw(image), rings, fill, width)
            continue
        shift = 0.5 if width % 2 == 0 else 0.0
        lines = [LineString([(x + shift, y + shift) for x, y in ring]) for ring in rings]
        network = unary_union(lines)
        if network.geom_type == "MultiLineString":
            network = linemerge(network)
        if crisp:
            surface = network.buffer(
                width / 2, cap_style="flat", join_style="mitre", mitre_limit=3.0
            )
        else:
            surface = network.buffer(width / 2, cap_style="round", join_style="bevel")
        if surface.is_empty:
            continue
        x0, y0, x1, y1 = surface.bounds
        left, top = max(0, math.floor(x0)), max(0, math.floor(y0))
        right, bottom = min(image.width, math.ceil(x1) + 1), min(image.height, math.ceil(y1) + 1)
        if right <= left or bottom <= top:
            continue
        polys = list(getattr(surface, "geoms", None) or [surface])
        span_w = right - left
        for sy0 in range(top, bottom, strip_h):
            sy1 = min(bottom, sy0 + strip_h)
            sh = sy1 - sy0
            hi = Image.new("L", (span_w * scale, sh * scale), 0)
            draw = ImageDraw.Draw(hi)
            drew = False
            for poly in polys:
                _, py0, _, py1 = poly.bounds
                if py1 < sy0 - 1 or py0 > sy1 + 1:
                    continue
                drew = True
                draw.polygon(
                    [(round((x - left + 0.5) * scale), round((y - sy0 + 0.5) * scale))
                     for x, y in poly.exterior.coords],
                    fill=255,
                )
                for hole in poly.interiors:
                    draw.polygon(
                        [(round((x - left + 0.5) * scale), round((y - sy0 + 0.5) * scale))
                         for x, y in hole.coords],
                        fill=0,
                    )
            if not drew:
                continue
            cov = np.asarray(hi.resize((span_w, sh), Image.Resampling.BOX))
            mask = Image.fromarray(np.where(cov >= 128, np.uint8(255), np.uint8(0)), mode="L")
            image.paste(fill, (left, sy0, right, sy1), mask)
