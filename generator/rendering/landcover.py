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


# While OSM paints, WorldCover's ground stands in these colours, one per class,
# none of them a ground colour. Whatever is still a marker once OSM has painted
# is ground OSM left blank - which comparing colours after the fact cannot
# tell, since OSM's grass over WorldCover's grass is the same grass.
MARKER = {code: (3, 7, code) for code in WORLDCOVER_PAINT}
assert not set(MARKER.values()) & C.LANDSCAPE_COLORS

_STRIP = 1024


def grid_for_map(landcover_for, proj):
    """WorldCover's class for every tile of the map, `(height, width)`.

    The map's image covers more than the bbox (it is padded to whole cells),
    so the grid is read for what the image covers. A turned map's tiles do
    not run along lines of latitude: the grid is read for the box round the
    whole turned map, and each tile takes the class at its own position."""
    import math

    import numpy as np

    bounds = proj.latlon_bbox()
    if not proj.rotation:
        return landcover_for(proj.width, proj.height, bounds=bounds)
    a = math.radians(proj.rotation)
    c, s_ = abs(math.cos(a)), abs(math.sin(a))
    gw = max(1, int(math.ceil(proj.width * c + proj.height * s_)))
    gh = max(1, int(math.ceil(proj.width * s_ + proj.height * c)))
    source = landcover_for(gw, gh, bounds=bounds)
    if source is None:
        return None
    source = np.asarray(source)
    gh, gw = source.shape
    south, west, north, east = bounds
    out = np.zeros((proj.height, proj.width), dtype=source.dtype)
    xs = np.arange(proj.width, dtype=np.float64) + 0.5
    for top in range(0, proj.height, _STRIP):
        bottom = min(proj.height, top + _STRIP)
        ys = np.arange(top, bottom, dtype=np.float64) + 0.5
        px, py = np.meshgrid(xs, ys)
        lat, lon = proj.to_latlon_many(px, py)
        col = np.clip(((lon - west) / (east - west) * gw).astype(np.int64), 0, gw - 1)
        row = np.clip(((north - lat) / (north - south) * gh).astype(np.int64), 0, gh - 1)
        out[top:bottom] = source[row, col]
    return out


def resized_grid(grid, size):
    """The class grid at the image's size (width, height), nearest class."""
    import numpy as np
    from PIL import Image

    grid = np.asarray(grid, dtype="uint8")
    if (grid.shape[1], grid.shape[0]) == tuple(size):
        return grid
    return np.asarray(Image.fromarray(grid, "L").resize(tuple(size), Image.NEAREST))


def paint_markers(landscape, grid) -> None:
    """Paint each classified tile in its class's marker colour."""
    import numpy as np
    from PIL import Image

    grid = resized_grid(grid, landscape.size)
    w = landscape.size[0]
    for top in range(0, grid.shape[0], _STRIP):
        g = grid[top:top + _STRIP]
        if not g.any():
            continue
        rgb = np.array(landscape.crop((0, top, w, top + g.shape[0])))
        for code, colour in MARKER.items():
            rgb[g == code] = colour
        landscape.paste(Image.fromarray(rgb, "RGB"), (0, top))


def settle_markers(landscape, grid):
    """Turn marker colours into the classes' ground colours. Returns `owned`:
    a bool array, True where the tile is still WorldCover's (OSM left it)."""
    import numpy as np
    from PIL import Image

    grid = resized_grid(grid, landscape.size)
    w, h = landscape.size
    owned = np.zeros((h, w), dtype=bool)
    for top in range(0, h, _STRIP):
        g = grid[top:top + _STRIP]
        if not g.any():
            continue
        rgb = np.array(landscape.crop((0, top, w, top + g.shape[0])))
        for code, colour in MARKER.items():
            hit = (g == code) & np.all(rgb == colour, axis=2)
            if hit.any():
                rgb[hit] = WORLDCOVER_PAINT[code]
                owned[top:top + g.shape[0]] |= hit
        landscape.paste(Image.fromarray(rgb, "RGB"), (0, top))
    return owned


def refine_owned(landscape, grid, owned) -> None:
    """Drop from `owned` (in place) any tile no longer its class's colour:
    dense paving and the drawn shape's clipping repaint after OSM."""
    import numpy as np

    grid = resized_grid(grid, landscape.size)
    w, h = landscape.size
    for top in range(0, h, _STRIP):
        o = owned[top:top + _STRIP]
        if not o.any():
            continue
        g = grid[top:top + o.shape[0]]
        rgb = np.asarray(landscape.crop((0, top, w, top + o.shape[0])))
        same = np.zeros(o.shape, dtype=bool)
        for code, colour in WORLDCOVER_PAINT.items():
            same |= (g == code) & np.all(rgb == colour, axis=2)
        o &= same


# --- feature painting ------------------------------------------------------

# Paint order for landscape: later categories overwrite earlier ones, so this
# is effectively painted bottom-to-top.
LANDSCAPE_ORDER = [
    # Broad land use first, so anything more specific inside it - a pitch in a
    # schoolyard, a car park on an industrial estate - is painted over it.
    # An airfield is mown grass with everything else laid on top of it.
    "airfield",
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
    # A ditch, a drain, a dam or a weir: a dry channel of clay. Above the land
    # use, so a drain cut across a field shows; below every road and path, so
    # one crossing it is still a bridge and not a stripe down the middle.
    "drainage",
    "railway",        # gravel track bed; roads cross it at level crossings
    "dirt_path",      # thin dirt line
    "paved_path",     # footway, pavement, cycleway
    "pier",           # jetties, over the water
    "breakwater",     # rock groynes and breakwaters, over the water too
    "parking",        # car park tarmac
    "plaza",          # paved pedestrian square
    "pedestrian",     # pedestrian zone, paved wall to wall
    "road_service",   # alleys and driveways
    "road_minor",
    "road_medium",
    "road_major",     # widest, so it wins at junctions
    # The airport, over the service roads that run round it: the apron is
    # laid first, then the taxiways on it, then the runway over everything.
    # A road crossing a live runway is a road that was painted too late.
    "apron",
    "taxiway",
    "runway",
    # Building footprints are not painted at all. They used to be dirt, which
    # showed as a brown fringe wherever the placed building and the painted
    # footprint disagreed by a tile - and the building's own floor covers the
    # ground under it anyway.
]

# Waterways drawn from a centre line, when no area is mapped around them.
# A river is usually mapped with its banks too, which paints over this.
# Drainage is drawn from its centre line like a waterway and it is the
# narrowest water a town has: a storm drain is a pipe trench, a field ditch a
# step across. On the 3 m fallback they came out as wide as a lane.
WATERWAY_WIDTH_M = {"river": 12.0, "canal": 8.0, "stream": 2.0,
                    "ditch": 2.5, "drain": 1.5, "dam": 4.0, "weir": 3.0}

# The bed of a track that carries no trains: it keeps its shape and loses its
# steel, so it is ballast with grass through it rather than bare dirt.
#
# An existing colour on purpose. A new RGB would need a new rule in Rules.txt
# naming a tile, and a rule naming artwork the player's Build 42 does not have
# stops the BMP-to-TMX conversion outright
# (worlded/patch_rules_b42_trees.py); the palette is otherwise free.
DISUSED_RAIL_FILL = C.DIRT_GRASS


LANDSCAPE_FILL = {
    "water": C.WATER,
    "sand": C.SAND,
    "dirt": C.DIRT,
    "dirt_path": C.DIRT,
    "paved_path": C.PALE_CONCRETE,
    "pier": C.PALE_CONCRETE,
    # Rubble, not the pale concrete of a pier: a breakwater is a wall of stone
    # thrown into the sea, and it read as a promenade.
    "breakwater": C.GRAVEL_DIRT,
    # A dry channel. C.WATER would carry swimming, no spawns and no props.
    "drainage": C.CLAY,
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
    # Grass base rather than a wall-to-wall concrete plain; each building gets a
    # modest concrete apron and paths to the street (knoxbuild/yards.py).
    "commercial": C.MEDIUM_GRASS,
    # Rough grass: each works gets its own tarmac yard round it
    # (knoxbuild/works.py). Gravel from fence to fence was a beige plain.
    "industrial": C.LIGHT_GRASS,
    "military": C.DIRT,
    "schoolyard": C.MEDIUM_GRASS,
    "hospital_grounds": C.MEDIUM_GRASS,
    "worship_grounds": C.PAVING,
    "cemetery": C.LIGHT_GRASS,
    "orchard": C.MEDIUM_GRASS,
    "sports": C.MEDIUM_GRASS,
    "wetland": C.DARK_GRASS,
    "playground": C.SAND,
    "track": C.CLAY,
    "pool": C.WATER,
    # Taken from the game's own airfield, which is the thing a player will
    # compare this to: the runway and the taxiways are grey asphalt like any
    # road, with a pale shoulder either side of the runway and a dashed
    # white line down it; the apron is the big pale slab. Drawn the other
    # way round - a white runway on dark aprons - it reads as a car park
    # with a path through it.
    #
    # The grass is the ordinary green, as it is in the game's own airfield.
    # Nothing grows on it because the planting passes are handed the
    # aerodrome's own outline and keep off it, not because the colour was
    # chosen to dodge them - the pale grass they do dodge is a wheat field,
    # and the strip came out standing in a crop
    # (renderer._mown_mask, generator/rendering/vegetation.py).
    "airfield": C.MEDIUM_GRASS,
    "apron": C.PALE_CONCRETE,
    "taxiway": C.MEDIUM_ASPHALT,
    # The runway is the darkest surface the palette has, which is what makes
    # it read as a runway rather than a very wide street: painted the same
    # grey as a road, with the same markings, there was nothing left to tell
    # them apart. Dark strip, pale shoulder either side, pale bars at each
    # end - that silhouette is an airfield and nothing else. The taxiway
    # keeps its lighter grey, so those two are told apart as well.
    #
    # DARK_ASPHALT, not DARKEST_ASPHALT. The names here do not run the way
    # the tiles do - measured off blends_street_01, the mean brightness of
    # what each one maps to through Rules.txt is: PALE_CONCRETE 127 ("Medium
    # Asphalt", street), DARKEST_ASPHALT 122 ("Gravel Asphalt", street4),
    # MEDIUM_ASPHALT 112 ("Smooth Asphalt", street3), DARK_ASPHALT 102
    # ("Dark Asphalt (main roads)", street2). The darkest is DARK_ASPHALT,
    # and the palest thing on the map is the one called concrete.
    "runway": C.DARK_ASPHALT,
}

# Categories knoxbuild needs as areas, to tell what a building standing in
# them probably is: an untagged building on an industrial estate is a works,
# not a house.
AREA_CATEGORIES = {"residential", "commercial", "industrial", "military",
                   "schoolyard", "hospital_grounds", "worship_grounds",
                   "cemetery", "parking", "sports", "park", "playground",
                   "airfield", "apron"}
# A building site already built on is drawn as a neighbourhood, not bare
# dirt: OSM keeps landuse=construction on a new estate long after its houses
# are up and mapped, and Cambourne's finished streets stood in fields of
# earth. A site counts as built on with this many mapped buildings in it, or
# this share of it under them.
BUILT_SITE_BUILDINGS = 5
BUILT_SITE_COVERAGE = 0.05
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
                    "wetland", "hospital_grounds", "airfield"}


def built_sites(dirt_feats, building_feats, proj) -> list:
    """The landuse=construction areas in `dirt_feats` that are already built
    on (BUILT_SITE_BUILDINGS, BUILT_SITE_COVERAGE), from the mapped buildings."""
    from shapely import STRtree
    from shapely.geometry import Polygon

    from .geometry import _feature_coords_px, _is_polygon

    sites = [f for f in dirt_feats
             if f.tags.get("landuse") == "construction" and _is_polygon(f)]
    if not sites or not building_feats:
        return []
    shapes = []
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                poly = Polygon(ring)
                shapes.append(poly if poly.is_valid else poly.buffer(0))
    if not shapes:
        return []
    tree = STRtree(shapes)
    built = []
    for site in sites:
        for ring in _feature_coords_px(site, proj):
            if len(ring) < 3:
                continue
            area = Polygon(ring)
            area = area if area.is_valid else area.buffer(0)
            if area.is_empty or area.area <= 0:
                continue
            inside = [shapes[i] for i in tree.query(area)
                      if area.contains(shapes[i].representative_point())]
            covered = sum(s.area for s in inside)
            if (len(inside) >= BUILT_SITE_BUILDINGS
                    or covered >= BUILT_SITE_COVERAGE * area.area):
                built.append(site)
                break
    return built
