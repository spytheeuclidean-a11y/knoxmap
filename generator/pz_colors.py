"""Project Zomboid map color palette.

Values taken directly from Thuztor's "Mapping Guide v0.2". These colors are
interpreted pixel-for-pixel by WorldEd's BMP-to-TMX converter via the
rules.txt that ships with the ZomboidMapTools.

A PZ cell is 300x300 pixels/tiles. The landscape, vegetation, and zombie
spawn bitmaps must all line up 1:1 (the spawn map is 10x smaller — one pixel
per 10 world tiles).
"""
from __future__ import annotations

# Landscape (floor) colors — used in the base landscape bitmap.
DARK_GRASS = (90, 100, 35)
MEDIUM_GRASS = (117, 117, 47)
LIGHT_GRASS = (145, 135, 60)
SAND = (210, 200, 160)
DARK_ASPHALT = (100, 100, 100)
MEDIUM_ASPHALT = (120, 120, 120)
LIGHT_ASPHALT = (165, 160, 140)
DARKEST_ASPHALT = (80, 80, 80)   # street4 — widest roads
PALE_CONCRETE = (150, 150, 150)  # street3 — kerbs and pavement
PAVING = (170, 160, 130)         # sandstone slabs — squares, plazas
CLAY = (110, 80, 60)             # clay — running tracks
DIRT = (120, 70, 20)
WATER = (0, 138, 255)
DARK_POTHOLE = (110, 100, 100)
LIGHT_POTHOLE = (130, 120, 120)

# Vegetation colors — used in the `_veg.bmp` bitmap. Several of these are
# only valid when painted on top of a specific landscape color (see guide).
TREES = (255, 0, 0)
TREES_DARK_GRASS = (127, 0, 0)          # fewer trees + more dark grass
SPARSE_TREES = (64, 0, 0)               # sparse trees + mostly dark grass
GRASS_ON_DARK = (0, 255, 0)             # must sit on DARK_GRASS landscape
LOT_OF_GRASS_AND_TREES = (0, 128, 0)
BUSHES_TREES_DARK_GRASS = (255, 0, 255)
BUSHES = (250, 0, 160)                  # bushes, any ground — hedges
DENSE_BUSHES_GRASS = (200, 0, 200)      # must sit on DARK_GRASS — wetland
FLOWERS = (200, 100, 200)               # flowers, any ground — cemeteries
VEG_NOTHING = (0, 0, 0)

# Zombie spawn map: grayscale, 10x smaller than landscape/vegetation.
# (0,0,0) = no spawns, (255,255,255) = max spawn density.

# Valid color sets used for rules.txt-style validation if needed.
LANDSCAPE_COLORS = {
    DARK_GRASS, MEDIUM_GRASS, LIGHT_GRASS, SAND,
    DARK_ASPHALT, MEDIUM_ASPHALT, LIGHT_ASPHALT, DARKEST_ASPHALT,
    PALE_CONCRETE, PAVING, CLAY, DIRT,
    WATER, DARK_POTHOLE, LIGHT_POTHOLE,
}
VEGETATION_COLORS = {
    TREES, TREES_DARK_GRASS, SPARSE_TREES, GRASS_ON_DARK,
    LOT_OF_GRASS_AND_TREES, BUSHES_TREES_DARK_GRASS, VEG_NOTHING,
    BUSHES, DENSE_BUSHES_GRASS, FLOWERS,
}

CELL_SIZE = 300  # tiles per cell side — fixed by the game engine
SPAWN_MAP_SCALE = 10  # spawn map is 1/10th the resolution
