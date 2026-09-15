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
# The road colours are named for what their tiles look like in Build 42, not
# for the labels in Rules.txt, which are older than the textures and wrong:
# Rules.txt calls 120 "Medium Asphalt" but its tiles (blends_street_01_96-103)
# are pale concrete slabs, and 150 "Smooth Asphalt" is the grey asphalt. With
# the labels believed, every residential street was paved in slabs and every
# pavement in tarmac.
DARK_ASPHALT = (100, 100, 100)   # street2 — dark tarmac; no edge blends, so car parks
MEDIUM_ASPHALT = (150, 150, 150) # street3 — smooth grey tarmac, blends at its edges
LIGHT_ASPHALT = (165, 160, 140)  # lightgravel — beige gravel: yards, track beds
DARKEST_ASPHALT = (80, 80, 80)   # street4 — speckled worn tarmac, blends
PALE_CONCRETE = (120, 120, 120)  # street — pale concrete slabs: pavements, kerbs
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
GRASS_ON_DARK = (0, 255, 0)             # long grass; Rules.txt has it for every grass
SHORT_GRASS = (0, 250, 0)               # short grass tufts, on any grass ground landscape
LOT_OF_GRASS_AND_TREES = (0, 128, 0)
BUSHES_TREES_DARK_GRASS = (255, 0, 255)
BUSHES = (250, 0, 160)                  # bushes, any ground — hedges
DENSE_BUSHES_GRASS = (200, 0, 200)      # must sit on DARK_GRASS — wetland
FLOWERS = (200, 100, 200)               # flowers, any ground — cemeteries
VEG_NOTHING = (0, 0, 0)

# Road details on the vegetation bitmap, placed by the rules that
# worlded/patch_rules_roads.py adds: a kerb on each edge of a pavement tile
# that meets the road, and centre lines along the edge between two lanes.
KERB_W = (12, 34, 200)
KERB_N = (12, 34, 201)
KERB_S = (12, 34, 202)
KERB_E = (12, 34, 203)
KERB_NW = (12, 34, 204)
KERB_SW = (12, 34, 205)
KERB_NE = (12, 34, 206)
KERB_SE = (12, 34, 207)
LINE_YELLOW_N = (12, 35, 200)
LINE_YELLOW_W = (12, 35, 201)
LINE_WHITE_N = (12, 35, 202)
LINE_WHITE_W = (12, 35, 203)
EDGE_LINE_W = (12, 35, 204)
EDGE_LINE_N = (12, 35, 205)
EDGE_LINE_E = (12, 35, 206)
EDGE_LINE_S = (12, 35, 207)
# Street furniture and wear (worlded/patch_rules_roads.py).
ASPHALT_GRIME = (12, 36, 200)
ASPHALT_CRACKS = (12, 36, 201)
LAMP_N = (12, 36, 202)
LAMP_E = (12, 36, 203)
LAMP_S = (12, 36, 204)
LAMP_W = (12, 36, 205)
HYDRANT = (12, 36, 206)
STORM_DRAIN = (12, 36, 207)
LITTER = (12, 36, 208)
MAILBOX = (12, 36, 209)
BIN = (12, 36, 210)
# Back yards (knoxbuild/yards.py): a grill, patio table and chairs, a
# clothesline and a raised planting bed, each tile of each its own colour.
GRILL = (12, 37, 200)
CHAIR_W = (12, 37, 201)
CHAIR_N = (12, 37, 202)
CHAIR_E = (12, 37, 203)
CHAIR_S = (12, 37, 204)
TABLE_X0 = (12, 37, 205)
TABLE_X1 = (12, 37, 206)
TABLE_Y0 = (12, 37, 207)
TABLE_Y1 = (12, 37, 208)
LINE_X0 = (12, 37, 209)
LINE_XM = (12, 37, 210)
LINE_X1 = (12, 37, 211)
LINE_Y0 = (12, 37, 212)
LINE_YM = (12, 37, 213)
LINE_Y1 = (12, 37, 214)
BED_NW = (12, 37, 215)
BED_W = (12, 37, 216)
BED_SW = (12, 37, 217)
BED_N = (12, 37, 218)
BED_S = (12, 37, 219)
BED_NE = (12, 37, 220)
BED_E = (12, 37, 221)
BED_SE = (12, 37, 222)
BED_SOIL = (12, 37, 223)
# Ground: the stone slabs of a front path or a stoop (Rules.txt "Paving Stone 4").
PAVING_STONE = (190, 180, 180)

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
