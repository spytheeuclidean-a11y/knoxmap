"""A sample of forest drawn by the real forest code, for the settings panel.

300 x 300 m at a metre a tile: forest over most of it with a meadow cut out of
its north-west, a road across, a field along the east side. Small enough to
draw in well under a second, so the picture can follow the sliders.
"""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
from PIL import Image

from .. import pz_colors as C

SIZE = 300
FIELD_X = 235          # the field starts here
ROAD = (146, 153)      # rows of the road


def _sample():
    land = np.full((SIZE, SIZE, 3), C.MEDIUM_GRASS, dtype=np.uint8)
    land[:, FIELD_X:] = C.LIGHT_GRASS
    forest = np.zeros((SIZE, SIZE), dtype=bool)
    forest[:, :FIELD_X - 5] = True
    yy, xx = np.mgrid[:SIZE, :SIZE]
    forest &= (yy - 60) ** 2 + (xx - 70) ** 2 > 40 ** 2      # a meadow
    veg = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
    veg[forest] = C.TREES
    land[forest] = C.DARK_GRASS
    return land, veg, forest


# What a grade looks like from above: the chance a tile shows a crown. The map
# preview gives two grades the same green and leaves a clearing the colour of
# the ground under trees, so the sliders' effect is hard to see in it.
CROWN = {C.TREES: 0.9, C.TREES_DARK_GRASS: 0.5, C.SPARSE_TREES: 0.15}
CROWN_RGB = np.array([(34, 66, 28), (44, 82, 34), (28, 56, 24)], dtype=np.uint8)
GROUND_RGB = {C.DARK_GRASS: (98, 110, 52), C.MEDIUM_GRASS: (126, 128, 62),
              C.LIGHT_GRASS: (160, 150, 82), C.MEDIUM_ASPHALT: (120, 120, 120)}
SCALE = 2


def _trees_from_above(land, veg):
    """Ground in soft colours, and a dark crown on a share of each forest
    tile by its grade, scaled up so a crown is a dot."""
    h, w = land.shape[:2]
    out = np.zeros((h, w, 3), dtype=np.uint8)
    for colour, rgb in GROUND_RGB.items():
        out[np.all(land == colour, axis=2)] = rgb
    rng = np.random.default_rng(7)
    roll = rng.random((h, w))
    pick = rng.integers(0, len(CROWN_RGB), (h, w))
    for colour, chance in CROWN.items():
        crown = np.all(veg == colour, axis=2) & (roll < chance)
        out[crown] = CROWN_RGB[pick[crown]]
    return Image.fromarray(out, "RGB").resize((SCALE * w, SCALE * h), Image.NEAREST)


@lru_cache(maxsize=64)
def preview_png(density: float, stand_m: float, edge_m: float) -> bytes:
    from .forest_shape import shape_forest

    land, veg, forest = _sample()
    land_img = Image.fromarray(land, "RGB")
    veg_img = Image.fromarray(veg, "RGB")
    shape_forest(veg_img, land_img, forest, density, stand_m, edge_m, 1.0)
    # The road goes over the trees, as roads clear the woods on a map.
    g = np.array(land_img)
    v = np.array(veg_img)
    g[ROAD[0]:ROAD[1], :] = C.MEDIUM_ASPHALT
    v[ROAD[0]:ROAD[1], :] = C.VEG_NOTHING
    picture = _trees_from_above(g, v)
    out = io.BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()
