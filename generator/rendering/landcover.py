"""What each kind of ground is: the draw order, the fill colours and the category sets."""
from __future__ import annotations

from .. import pz_colors as C


# ESA WorldCover class -> ground colour, painted under every OSM feature.
# The table is data (knoxdata/worldcover.py reads it), but the colours are the
# renderer's, so they live here with the rest of the palette.
WORLDCOVER_PAINT = {
    10: C.DARK_GRASS,      # tree cover -> forest ground
    20: C.MEDIUM_GRASS,    # shrubland
    30: C.MEDIUM_GRASS,    # grassland
    40: C.LIGHT_GRASS,     # cropland -> farmland
    50: C.MEDIUM_GRASS,    # built-up: yards, not pavement; roads/buildings over it
    60: C.DIRT,            # bare / sparse
    70: C.SAND,            # snow and ice (the tile palette has no snow)
    80: C.WATER,           # permanent water
    90: C.DARK_GRASS,      # herbaceous wetland -> marsh
    95: C.DARK_GRASS,      # mangroves
    100: C.DIRT,           # moss and lichen -> rocky tundra
}


# --- feature painting ------------------------------------------------------

# Paint order for landscape: later categories overwrite earlier ones, so this
# is effectively painted bottom-to-top.
LANDSCAPE_ORDER = [
    # Broad land use first, so anything more specific inside it - a pitch in a
    # schoolyard, a car park on an industrial estate - is painted over it.
    "residential",    # gardens and yards
    "commercial",     # pavement in front of shops
    "industrial",     # rough grass; the works' yards are paved later
    "military",
    "schoolyard",
    "hospital_grounds",
    "worship_grounds",
    "cemetery",
    "orchard",
    "farmland",       # light grass
    "grass",          # medium grass
    "park",           # medium grass w/ trees added by vegetation pass
    "sports",
    "wetland",
    "sand",
    "dirt",
    "playground",
    "track",
    # Water under the ways that cross it: a river polygon painted last erased
    # every bridge, leaving no way over. Above land use, which it still wins.
    "water",
    "pool",
    "railway",        # gravel track bed; roads cross it at level crossings
    "dirt_path",      # thin dirt line
    "paved_path",     # footway, pavement, cycleway
    "pier",           # jetties and breakwaters, over the water
    "parking",        # car park tarmac
    "plaza",          # paved pedestrian square
    "pedestrian",     # pedestrian zone, paved wall to wall
    "road_service",   # alleys and driveways
    "road_minor",
    "road_medium",
    "road_major",     # widest, so it wins at junctions
    # Building footprints are not painted at all. They used to be dirt, which
    # showed as a brown fringe wherever the placed building and the painted
    # footprint disagreed by a tile - and the building's own floor covers the
    # ground under it anyway.
]

# Waterways drawn from a centre line, when no area is mapped around them.
# A river is usually mapped with its banks too, which paints over this.
WATERWAY_WIDTH_M = {"river": 12.0, "canal": 8.0, "stream": 2.0}


LANDSCAPE_FILL = {
    "water": C.WATER,
    "sand": C.SAND,
    "dirt": C.DIRT,
    "dirt_path": C.DIRT,
    "paved_path": C.PALE_CONCRETE,
    "pier": C.PALE_CONCRETE,
    # Dirt, not lightgravel: a rail bed is bare earth and gravel, and the pale
    # gravel strip read as a sandy footpath across the whole map.
    "railway": C.DIRT,
    "grass": C.MEDIUM_GRASS,
    "park": C.MEDIUM_GRASS,
    "farmland": C.LIGHT_GRASS,
    # street/street2/street4 in Rules.txt. road_minor used to paint
    # lightgravel, which put a gravel track through the middle of every
    # residential street in town.
    # Service lanes were gravel, which next to slab pavements read as more
    # pavement. Main roads get the worn speckled tarmac so they stand apart
    # from the smooth tarmac of ordinary streets; both blend at the edges.
    "road_service": C.DARKEST_ASPHALT,
    "pedestrian": C.PAVING,
    "road_minor": C.MEDIUM_ASPHALT,
    "road_medium": C.MEDIUM_ASPHALT,
    "road_major": C.DARKEST_ASPHALT,
    "parking": C.DARK_ASPHALT,
    "plaza": C.PAVING,
    "residential": C.MEDIUM_GRASS,
    "commercial": C.PALE_CONCRETE,
    # Rough grass: each works gets its own tarmac yard round it
    # (knoxbuild/works.py). Gravel from fence to fence was a beige plain.
    "industrial": C.LIGHT_GRASS,
    "military": C.DIRT,
    "schoolyard": C.PALE_CONCRETE,
    "hospital_grounds": C.MEDIUM_GRASS,
    "worship_grounds": C.PAVING,
    "cemetery": C.LIGHT_GRASS,
    "orchard": C.MEDIUM_GRASS,
    "sports": C.MEDIUM_GRASS,
    "wetland": C.DARK_GRASS,
    "playground": C.SAND,
    "track": C.CLAY,
    "pool": C.WATER,
}

# Categories knoxbuild needs as areas, to tell what a building standing in
# them probably is: an untagged building on an industrial estate is a works,
# not a house.
AREA_CATEGORIES = {"residential", "commercial", "industrial", "military",
                   "schoolyard", "hospital_grounds", "worship_grounds",
                   "cemetery", "parking", "sports", "park", "playground"}
# Drawn onto the vegetation bitmap rather than the ground.
VEG_CATEGORIES = {"forest", "scrub", "tree_single", "hedge", "orchard",
                  "cemetery", "wetland"}


# A city block is paved when buildings cover at least this share of it - the
# same line knoxbuild draws between a city and a suburb.
# Measured: central Paris, Kadikoy and a Tokyo neighbourhood sit at 0.4-0.5, a
# US suburb and a French village around 0.16. Set to the bottom of that
# downtown band: at 0.28 every old town got slabs of concrete two blocks wide,
# standing where the yards and trees should be.
DENSE_COVERAGE = 0.40
# And a block whose area is bigger than this is not a city block at all. A
# rural road grid throws blocks a kilometre across - one farm, one works and a
# couple of houses clear the coverage line easily - and paving the whole of one
# is the big concrete field that reads as ground nobody landscaped. 200 x 200
# tiles is a long Manhattan block; past that the yards stay grass.
MAX_PAVED_BLOCK = 200 * 200
# Mapped green space keeps its grass however built-up the area around it is.
GREEN_CATEGORIES = {"park", "grass", "sports", "cemetery", "orchard", "farmland",
                    "wetland", "hospital_grounds"}
