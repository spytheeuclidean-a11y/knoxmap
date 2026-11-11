"""What grows on each WorldCover class, on ground OpenStreetMap left blank.

The class was painted as a ground colour and nothing else knew it, so a
WorldCover wood was dark grass with no trees, and shrubland and grassland were
the same lawn with random scrub thrown on both. Here each class gets the
growth that belongs to it. Tree cover is not planted here: it is handed back
as a mask for the woodland pass, so it grows exactly as a mapped wood does,
with a thinner edge, big trees and the Forest density dial.

Cropland (fields), bare ground and moss (rock fields) and the wetland's pools
are ground, painted before this in generator/rendering/fields.py. Built-up
land gets the garden pass's planting, like any other yard.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .. import pz_colors as C
from .fields import _hash01, _strips

SHRUB_CLUMP_M = 40.0           # how far a thicket or an opening runs
SHRUB_IN = 0.35                # chance per tile inside a thicket
SHRUB_OUT = 0.08               # ...and in the open between them
SHRUB_BUSH = 0.65              # of what grows on shrubland: bushes,
SHRUB_YOUNG = 0.25             # young trees, and the rest sparse trees
GRASS_TUFTS = 0.20             # grassland: a tuft of grass
GRASS_BUSH = 0.01              # ...or a bush
MARSH = 0.6                    # wetland: dense bush and marsh grass
MARSH_TREE = 0.03              # ...or a stunted tree
VEG_SEED = 6203

FOREST = 10
SHRUB = 20
GRASS = 30
WETLAND = (90, 95)


def plant_landcover(veg, landscape, grid, owned, proj, density: float = 1.0):
    """Plant shrubland, grassland and wetland on `owned` tiles whose
    vegetation is still empty. Returns `(forest, counts)`: the tree-cover
    tiles for the woodland pass, and tiles planted per class."""
    from .noise import lattices, smooth_noise
    from .vegetation import tree_rules_ready

    h, w = owned.shape
    forest = owned & (grid == FOREST)
    counts = {SHRUB: 0, GRASS: 0, 90: 0}
    if density <= 0:
        return forest, counts
    young = C.TREE_SMALL if tree_rules_ready() else C.SPARSE_TREES
    clump = max(3, int(round(SHRUB_CLUMP_M / proj.meters_per_tile)))
    lats = lattices(h, w, [(clump, 1.0)], VEG_SEED)
    xs = np.arange(w, dtype=np.float32)
    shrub_in = min(1.0, SHRUB_IN * density)
    shrub_out = min(1.0, SHRUB_OUT * density)
    tufts = min(1.0, GRASS_TUFTS * density)
    grass_bush = min(1.0, GRASS_BUSH * density)
    marsh = min(1.0, MARSH * density)
    marsh_tree = min(1.0, MARSH_TREE * density)
    for top, bottom in _strips(h):
        o = owned[top:bottom]
        g = grid[top:bottom]
        live = o & ((g == SHRUB) | (g == GRASS) | np.isin(g, WETLAND))
        if not live.any():
            continue
        vegp = np.array(veg.crop((0, top, w, bottom)))
        land = np.array(landscape.crop((0, top, w, bottom)))
        empty = np.all(vegp == 0, axis=2)
        tile_ids = (np.arange(top, bottom, dtype=np.int64)[:, None] * w
                    + np.arange(w, dtype=np.int64)[None, :])
        roll = _hash01(tile_ids, VEG_SEED)
        pick = _hash01(tile_ids, VEG_SEED + 1)

        shrub = live & empty & (g == SHRUB)
        if shrub.any():
            thick = smooth_noise(np.arange(top, bottom, dtype=np.float32), xs, lats) > 0.5
            grows = shrub & (roll < np.where(thick, shrub_in, shrub_out))
            bush = grows & (pick < SHRUB_BUSH)
            small = grows & (pick >= SHRUB_BUSH) & (pick < SHRUB_BUSH + SHRUB_YOUNG)
            sparse = grows & ~bush & ~small
            vegp[bush] = C.BUSHES
            vegp[small] = young
            vegp[sparse] = C.SPARSE_TREES
            # Sparse trees are a dark-grass rule, as in the woods.
            land[(sparse | small) if young == C.SPARSE_TREES else sparse] = C.DARK_GRASS
            counts[SHRUB] += int(grows.sum())

        grass = live & empty & (g == GRASS)
        if grass.any():
            bush = grass & (roll < grass_bush)
            tuft = grass & ~bush & (roll < grass_bush + tufts)
            vegp[bush] = C.BUSHES
            vegp[tuft] = C.SHORT_GRASS
            counts[GRASS] += int((bush | tuft).sum())

        wet = live & empty & np.isin(g, WETLAND)
        if wet.any():
            tree = wet & (roll < marsh_tree)
            reed = wet & ~tree & (roll < marsh_tree + marsh)
            vegp[tree] = C.SPARSE_TREES
            vegp[reed] = C.DENSE_BUSHES_GRASS
            land[tree | reed] = C.DARK_GRASS
            counts[90] += int((tree | reed).sum())

        veg.paste(Image.fromarray(vegp, "RGB"), (0, top))
        landscape.paste(Image.fromarray(land, "RGB"), (0, top))
    return forest, counts
