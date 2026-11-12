"""A sample of land drawn by the real forest code, for the Forest card.

300 x 300 m at a metre a tile: a blotchy wood with arms and a small wood
apart, a meadow, a strip of shrubland, a road across with a lane off it into
the wood, a house on the lane in the wood, two along the road at the wood's
edge, and a field along the east side. It goes through the passes the card's
sliders reach, in the renderer's order, so what is seen is what is got.
Land cover covers all of it, as WorldCover does a map: Scrub on open ground
and Made-up woods grow only where there is none, so neither shows here.
"""
from __future__ import annotations

import io
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from .. import pz_colors as C
from .forest_params import ForestParams

SIZE = 300
SCALE = 2
FIELD_X = 240                   # the field starts here
ROAD = (146, 153)               # rows of the road
LANE = (98, 103, 60)            # columns of the lane, and the row it ends at
WOOD_HOUSE = ((106, 66), (120, 80))           # (x0, y0), (x1, y1)
HOUSES = (WOOD_HOUSE, ((150, 160), (164, 171)), ((182, 160), (196, 171)))
SHRUB = (250, 272, 20, 140)     # rows, columns of the shrubland strip
WOOD_SEED = 4242

GROUND_RGB = {C.DARK_GRASS: (98, 110, 52), C.MEDIUM_GRASS: (126, 128, 62),
              C.LIGHT_GRASS: (160, 150, 82), C.MEDIUM_ASPHALT: (120, 120, 120),
              C.DARK_ASPHALT: (84, 84, 84)}
# What a tile shows from above: the chance of a crown on it.
CROWN = {C.TREES: 0.9, C.TREES_DARK_GRASS: 0.5, C.SPARSE_TREES: 0.15,
         C.BUSHES_TREES_DARK_GRASS: 0.5}
CROWN_RGB = np.array([(34, 66, 28), (44, 82, 34), (28, 56, 24)], dtype=np.uint8)
YOUNG_RGB = (96, 142, 62)
YOUNG_CHANCE = 0.5
SHRUB_RGB = (150, 112, 58)       # hedge and scrub bushes, warmer than the wood
SHRUB_CHANCE = 0.8
BUSH_RGB = (70, 104, 44)
BIG_RGB = (30, 60, 26)
ROOF_RGB, ROOF_EDGE = (150, 92, 72), (90, 52, 40)


def _wood_mask() -> np.ndarray:
    """Where the wood is: a fixed blotchy field, with the woods the houses
    need made sure of."""
    from .noise import lattices, smooth_noise

    ys = np.arange(SIZE, dtype=np.float32)
    v = smooth_noise(ys, ys, lattices(SIZE, SIZE, [(110, 0.65), (35, 0.25), (10, 0.10)],
                                      WOOD_SEED))
    wood = v > np.quantile(v, 0.40)
    yy, xx = np.mgrid[:SIZE, :SIZE]
    wood |= (yy - 73) ** 2 + (xx - 113) ** 2 < 42 ** 2          # round the house in it
    wood |= (yy - 205) ** 2 + (xx - 175) ** 2 < 40 ** 2         # behind the road's houses
    wood &= ~((yy - 225) ** 2 + (xx - 60) ** 2 < 28 ** 2)       # a meadow
    r0, r1, c0, c1 = SHRUB
    wood[r0:r1, c0:c1] = False                                  # the shrubland's open ground
    wood[:, FIELD_X - 5:] = False
    return wood


@lru_cache(maxsize=1)
def _sample():
    """The land before any pass: ground, an empty vegetation layer, the wood,
    the land cover classes, the footprints and the roads (pixel lines)."""
    land = np.full((SIZE, SIZE, 3), C.MEDIUM_GRASS, dtype=np.uint8)
    land[:, FIELD_X:] = C.LIGHT_GRASS
    wood = _wood_mask()
    grid = np.full((SIZE, SIZE), 30, dtype=np.uint8)        # grassland
    grid[wood] = 10                                          # tree cover
    r0, r1, c0, c1 = SHRUB
    grid[r0:r1, c0:c1] = 20                                  # shrubland (the wood leaves it open)
    grid[:, FIELD_X:] = 40                                   # cropland
    land[ROAD[0]:ROAD[1], :] = C.MEDIUM_ASPHALT
    x0, x1, end = LANE
    land[end:ROAD[0], x0:x1] = C.MEDIUM_ASPHALT
    rings = [[(a, b), (c, b), (c, d), (a, d), (a, b)] for (a, b), (c, d) in HOUSES]
    roads = [[(0, (ROAD[0] + ROAD[1]) / 2), (SIZE - 1, (ROAD[0] + ROAD[1]) / 2)],
             [((x0 + x1) / 2, ROAD[0]), ((x0 + x1) / 2, end)]]
    return land, wood, grid, rings, roads


def _projector():
    from .projection import Projector

    south, west = 45.0, -65.0
    north = south + SIZE / 111320
    east = west + SIZE / (111320 * math.cos(math.radians(south)))
    return Projector.build(south, west, north, east, 1.0, 0.0)


def preview_layers(tree_density: float, forest_density: float,
                   params: ForestParams) -> tuple[np.ndarray, np.ndarray, list]:
    """The sample after every pass the card reaches: (ground, vegetation,
    footprint rings)."""
    from .forest_shape import shape_forest
    from .homesteads import clear_homesteads
    from .landcover_veg import plant_landcover
    from .vegetation import _plant_big_trees

    land0, _, grid, rings, roads = _sample()
    land_img = Image.fromarray(land0.copy(), "RGB")
    veg_img = Image.new("RGB", (SIZE, SIZE), C.VEG_NOTHING)
    proj = _projector()
    owned = ~np.all(land0 == C.MEDIUM_ASPHALT, axis=2)
    forest, _ = plant_landcover(veg_img, land_img, grid, owned, proj,
                                density=tree_density * params.shrubland)
    # The woodland pass, as the renderer runs it before the shaping: every
    # wood tile a tree on dark grass.
    v = np.array(veg_img)
    g = np.array(land_img)
    v[forest] = C.TREES
    g[forest] = C.DARK_GRASS
    veg_img, land_img = Image.fromarray(v, "RGB"), Image.fromarray(g, "RGB")
    shape_forest(veg_img, land_img, forest, tree_density * forest_density,
                 params.stand_m, params.edge_m, 1.0, params, young_trees=True)
    clear_homesteads(veg_img, land_img, rings, roads, 1.0,
                     clear_max_m=params.house_clearing_m)
    _plant_big_trees(veg_img, land_img, [], [], [], proj, density=tree_density,
                     wood_mult=params.big_trees)
    # The renderer's road clearing (vegetation._clear_road_vegetation) scans
    # every road colour in 256-row bands, 200 ms here; the sample's paving is
    # only these two, so the same job is one scan.
    g = np.array(land_img)
    v = np.array(veg_img)
    v[np.all((g == C.MEDIUM_ASPHALT) | (g == C.DARK_ASPHALT), axis=2)] = C.VEG_NOTHING
    for (a, b), (c, d) in HOUSES:
        v[b:d, a:c] = C.VEG_NOTHING
    return g, v, rings


def _key(a: np.ndarray) -> np.ndarray:
    """One integer per colour, so a colour is one comparison, not three."""
    a = a.astype(np.uint32)
    return (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]


def _from_above(land: np.ndarray, veg: np.ndarray, rings: list) -> Image.Image:
    """Ground in soft colours, a crown on a share of each tree tile by its
    grade, young trees and bushes as dots, big trees as big crowns, houses as
    roofs - scaled up so a crown is a dot."""
    h, w = land.shape[:2]
    lk, vk = _key(land), _key(veg)
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[:] = GROUND_RGB[C.MEDIUM_GRASS]
    for colour, rgb in GROUND_RGB.items():
        out[lk == _key(np.array(colour, dtype=np.uint8))] = rgb
    rng = np.random.default_rng(7)
    roll = rng.random((h, w))
    pick = rng.integers(0, len(CROWN_RGB), (h, w))
    for colour, chance in CROWN.items():
        crown = (vk == _key(np.array(colour, dtype=np.uint8))) & (roll < chance)
        out[crown] = CROWN_RGB[pick[crown]]
    out[(vk == _key(np.array(C.BUSHES_TREES_DARK_GRASS, dtype=np.uint8))) & (roll >= 0.5)] = BUSH_RGB
    for colour in (C.BUSHES, C.DENSE_BUSHES_GRASS):
        out[(vk == _key(np.array(colour, dtype=np.uint8))) & (roll < SHRUB_CHANCE)] = SHRUB_RGB
    # Young trees are small light crowns among the dark ground, not a lawn.
    out[(vk == _key(np.array(C.TREE_SMALL, dtype=np.uint8))) & (roll < YOUNG_CHANCE)] = YOUNG_RGB
    img = Image.fromarray(out, "RGB").resize((SCALE * w, SCALE * h), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    for colour, side in C.BIG_TREE_ROOM.items():
        ys, xs = np.nonzero(vk == _key(np.array(colour, dtype=np.uint8)))
        r = SCALE * side / 2
        for x, y in zip(xs.tolist(), ys.tolist()):
            cx, cy = SCALE * (x + 0.5), SCALE * (y + 0.5)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BIG_RGB)
    for ring in rings:
        (a, b), (c, d) = ring[0], ring[2]
        draw.rectangle((SCALE * a, SCALE * b, SCALE * c - 1, SCALE * d - 1),
                       fill=ROOF_RGB, outline=ROOF_EDGE)
    return img


@lru_cache(maxsize=64)
def preview_png(tree_density: float, forest_density: float, params: ForestParams) -> bytes:
    land, veg, rings = preview_layers(tree_density, forest_density, params)
    out = io.BytesIO()
    _from_above(land, veg, rings).save(out, format="PNG")
    return out.getvalue()
