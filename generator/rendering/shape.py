"""Cutting a map to a drawn outline: roads that leave it and everything outside it."""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import pz_colors as C
from ..osm import OSMFeature
from .geometry import _draw_line, _draw_roads, _feature_coords_px, _is_polygon, _pixel_width
from .projection import Projector
from .widths import _sidewalk_width_m, _way_width_m


# Roads that carry on past the edge of a drawn shape. Cutting every road at the
# line would leave the town an island in a field; the main roads out of it
# stay, the side streets and driveways of places not chosen do not.
THROUGH_ROADS = ("road_major", "road_medium")


def _clip_to_shape(landscape: Image.Image, shape, buckets: dict[str, list[OSMFeature]],
                   proj: Projector) -> None:
    """Outside the drawn shape, the ground goes back to countryside.

    Water stays - a river does not stop at a line on the map - and so do the
    main roads through it, with their pavements. Everything else outside, the
    yards and car parks and side streets of the neighbourhood next door,
    becomes grass.
    """
    import numpy as np

    w, h = landscape.size
    inside = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(inside)
    for part in getattr(shape, "geoms", None) or [shape]:
        d.polygon(list(part.exterior.coords), fill=255)
        for hole in part.interiors:
            d.polygon(list(hole.coords), fill=0)
    keep = inside.copy()
    kd = ImageDraw.Draw(keep)
    mpt = proj.meters_per_tile
    strokes = []
    for cat in THROUGH_ROADS:
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            width = _pixel_width(_way_width_m(feat, cat)
                                 + 2 * _sidewalk_width_m(feat, cat), mpt)
            strokes.append((width, _feature_coords_px(feat, proj)))
    _draw_roads(keep, strokes, 255)
    for cat in ("water", "pool", "coastline"):
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                for ring in _feature_coords_px(feat, proj):
                    if len(ring) >= 3:
                        kd.polygon(ring, fill=255)
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        outside = np.asarray(keep.crop((0, y0, w, y1))) == 0
        if not outside.any():
            continue
        ground = np.asarray(landscape.crop((0, y0, w, y1)))
        water = (ground[:, :, 0] == C.WATER[0]) & (ground[:, :, 1] == C.WATER[1]) \
            & (ground[:, :, 2] == C.WATER[2])
        outside &= ~water
        if outside.any():
            grass = Image.new("RGB", (w, y1 - y0), C.DARK_GRASS)
            landscape.paste(grass, (0, y0), Image.fromarray(outside.astype(np.uint8) * 255))
