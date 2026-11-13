"""Street context, road weights, and OSM/drawn feature helpers for knoxbuild.build."""
from __future__ import annotations

import math
import os

import numpy as np
from shapely.geometry import Polygon

import knoxfiles

from .bitmaps import read_gray, read_rgb, same_colour
from .uses import USE_KEYS

# their own. Rooms a mapper drew inside a building (indoor=room) arrive with
# their tags, and where the tag names something Knox County knows, the room is
# built as that instead of guessed from its size (layout._mapped_rooms).
MAPPED_ROOM_KINDS = {
    "bedroom": "bedroom",
    "bathroom": "bathroom",
    "toilet": "bathroom",
    "kitchen": "kitchen",
    "living_room": "livingroom",
    "corridor": "hall",
    "hallway": "hall",
    "hall": "hall",
    "lobby": "lobby",
    "classroom": "classroom",
    "office": "office",
    "storage": "storage",
    "utility": "storage",
    "laundry": "laundry",
    "closet": "closet",
    "wardrobe": "closet",
    "library": "library",
    "laboratory": "schoollab",
    "stairs": "hall",
}


def _ring_points(geom: dict) -> list[list[float]]:
    """Every [lon, lat] in a Polygon or MultiPolygon outer ring."""
    if geom["type"] == "Polygon":
        return geom["coordinates"][0]
    pts: list[list[float]] = []
    for poly in geom["coordinates"]:
        pts.extend(poly[0])
    return pts


STREET_LOOK_TILES = 40
# How far off a wall counts as standing at the water's edge. A building this
# close to water on one side has its door on another.
SHORE_LOOK_TILES = 6
RETAIL_DENSITY = 0.28


def _street_finder(out_dir: str, map_name: str,
                   road_hierarchy: np.ndarray | None = None):
    """A function giving the side ("N", "S", "W" or "E") of a footprint that
    faces the nearest pavement or road, or None if none is near."""
    import numpy as np

    from generator import pz_colors as PC

    path = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    if not os.path.exists(path):
        path = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(path):
        return lambda *a: None
    g = read_rgb(path)
    paved = np.zeros(g.shape[:2], dtype=bool)
    for c in (PC.PALE_CONCRETE, PC.MEDIUM_ASPHALT, PC.DARKEST_ASPHALT):
        paved |= same_colour(g, c)
    water = same_colour(g, PC.WATER)
    H, W = paved.shape

    def side(x0: int, y0: int, w: int, h: int) -> str | None:
        best, best_score = None, STREET_LOOK_TILES + 1
        wet = {}
        for name, (dx, dy) in (("N", (0, -1)), ("S", (0, 1)), ("W", (-1, 0)), ("E", (1, 0))):
            if dx == 0:
                starts = [(x0 + w * f // 4, y0 if dy < 0 else y0 + h - 1) for f in (1, 2, 3)]
            else:
                starts = [(x0 if dx < 0 else x0 + w - 1, y0 + h * f // 4) for f in (1, 2, 3)]
            near_water = SHORE_LOOK_TILES + 1
            for sx, sy in starts:
                for d in range(1, STREET_LOOK_TILES + 1):
                    x, y = sx + dx * d, sy + dy * d
                    if not (0 <= x < W and 0 <= y < H):
                        break
                    if d <= SHORE_LOOK_TILES and water[y, x]:
                        near_water = min(near_water, d)
                    if paved[y, x]:
                        rank = (int(road_hierarchy[y, x])
                                if road_hierarchy is not None else 0)
                        score = d - min(5.0, rank * 0.6)
                        if score < best_score:
                            best, best_score = name, score
                        break
            wet[name] = near_water
        if best is not None:
            return best
        # Nothing paved within reach. If the building stands over or beside
        # water - a boathouse, a hut on a pier - the way in is whichever side
        # is not water; without this every door on a pier faced the lake,
        # because a building with no street found gets its door on the south
        # wall by default.
        if min(wet.values()) <= SHORE_LOOK_TILES:
            away = {"N": "S", "S": "N", "W": "E", "E": "W"}[
                min(wet, key=lambda name: (wet[name], name))]
            return max(wet, key=lambda name: (wet[name], name == away, name))
        return None

    return side


def _load_road_hierarchy(out_dir: str, map_name: str, proj) -> np.ndarray | None:

    path = os.path.join(out_dir, f"{map_name}_road_hierarchy.bmp")
    if not os.path.exists(path):
        return None
    return read_gray(path, crop=(proj.height, proj.width))


# Land whose ground is painted in a road's colours but is not a road: an
# industrial estate's gravel yard. A car park is left out - a building in the
# middle of one is a kiosk nobody mapped, and keeping footprints off car parks
# is right.
YARD_AREAS = {"industrial"}


def _road_weight(out_dir: str, map_name: str, proj,
                 road_hierarchy: np.ndarray | None = None,
                 areas=None) -> np.ndarray | None:
    """2 on carriageway, 1 on pavement, 0 elsewhere, from the ground as the
    renderer drew it.

    The ground alone cannot always tell a road from a yard: an industrial
    estate is painted in the same beige gravel as a track bed, so every
    footprint inside one was refused as standing on the road and the estate
    came out as empty gravel in the exact shape of its polygon. Where the land
    is what made the ground look like that, and no real road runs over it, it
    is ground a building may stand on.
    """

    from generator import pz_colors as C

    path = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    if not os.path.exists(path):
        path = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(path):
        return None
    ground = read_rgb(path, crop=(proj.height, proj.width))
    weight = np.zeros(ground.shape[:2], dtype=np.int8)
    for colour in (C.PALE_CONCRETE,):
        weight[same_colour(ground, colour)] = 1
    for colour in (C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                   C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE):
        weight[same_colour(ground, colour)] = 2
    classified = None
    if road_hierarchy is not None:
        # The mask includes each road's sidewalk width. Larger road classes
        # carry a stronger cost so footprints settle behind local streets.
        classified = road_hierarchy[:proj.height, :proj.width]
        weight[classified > 0] = classified[classified > 0]
    if areas is not None:
        yards = areas.mask(YARD_AREAS, weight.shape[1], weight.shape[0])
        if classified is not None:
            yards = yards & (classified == 0)
        weight[yards] = 0
    # Rail beds are transport corridors too; rooms must not erase their track tiles.
    from generator.rail_tiles import RAIL_RULES
    rail = (ground[:, :, 0] == 206) & np.isin(ground[:, :, 1], (1, 2))
    for colour in {colour for label, colour, tile in RAIL_RULES if colour[0] != 206}:
        rail |= same_colour(ground, colour)
    # An exterior wall can stand one square outside its room footprint.
    padded = np.pad(rail, 1)
    rail_clear = rail.copy()
    for dy in range(3):
        for dx in range(3):
            rail_clear |= padded[dy:dy + rail.shape[0], dx:dx + rail.shape[1]]
    weight[rail_clear] = 8
    return weight


def _drawn_features(out_dir: str, map_name: str) -> list:
    """What was drawn by hand for this map, as OSM features.

    The sheet from the drawing board, if there is one, and whatever was drawn
    over the world map. Both are stored as drawn so they can be drawn on
    again, and converted here the same way the generator converts them.
    """
    from generator import sketch

    # The sheet first, and only the sheet where there is one: building from a
    # sheet writes the drawing it becomes out as well, so reading both counted
    # every drawn thing twice - one petrol station came out as two.
    # A half-written one of these is said out loud rather than skipped: the
    # drawing is the whole map on a hand-drawn one, and a build that quietly
    # left it out handed back empty ground with no word of why.
    for name, convert, what in (
            (f"{map_name}_design.json", sketch.design_to_drawn, "the map you drew"),
            (f"{map_name}_sketch.geojson", lambda d: d, "what you added to the area")):
        drawn = knoxfiles.read(os.path.join(out_dir, name), what)
        if drawn is None:
            continue
        return sketch.features(convert(drawn))
    return []


def _points_of_use(out_dir: str, info: dict, map_name: str, proj) -> dict:
    """Point features from OSM, bucketed by tile for nearby-footprint lookup."""
    from generator import osm
    bbox = info.get("bbox") or {}
    cache = os.path.join(out_dir, info["osm_cache"]) if info.get("osm_cache")         else osm.cache_path(out_dir, map_name)
    wanted = tuple(info["osm_bbox"]) if info.get("osm_bbox") else         (bbox.get("south"), bbox.get("west"), bbox.get("north"), bbox.get("east"))
    grid: dict = {}
    # As the paper map does: this reads the download, it never fetches one.
    feats = osm.load_cache(cache, wanted, filters=None) or []
    feats = osm.proposed_roads(feats, info.get("include_proposed_roads", 0))
    # Points drawn by hand count too. They are kept beside the map rather than
    # in the download (web/mapfiles.py, _save_sketch), so reading only the cache left a
    # petrol station somebody placed themselves with no forecourt and no
    # pumps: "0 pumps at 0 stations, 0 canopies and 0 points".
    feats = feats + _drawn_features(out_dir, map_name)
    if info.get("straight_roads") and feats:
        # Where the renderer moved them to, with the roads straightened or routed.
        from generator.octilinear import replay
        from generator.renderer import _is_polygon, classify
        replay(feats, proj, classify, _is_polygon, info, out_dir, map_name)
    for feat in feats:
        if feat.kind != "node" or not (
            any(k in feat.tags for k in USE_KEYS) or "entrance" in feat.tags):
            continue
        lat, lon = feat.geometry[0]
        x, y = proj.to_px(lat, lon)
        grid.setdefault((int(x) // 16, int(y) // 16), []).append((x, y, feat.tags))
    return grid


def _points_inside(grid: dict, px: list, taken: set) -> list[dict]:
    """The tags of the points inside a footprint (or just outside its wall,
    where a mapper put the shop's entrance), each point used once."""
    if not grid:
        return []
    from shapely.geometry import Point
    poly = Polygon(px)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zone = poly.buffer(1.0)
    minx, miny, maxx, maxy = zone.bounds
    out = []
    for gx in range(int(minx) // 16, int(maxx) // 16 + 1):
        for gy in range(int(miny) // 16, int(maxy) // 16 + 1):
            for x, y, tags in grid.get((gx, gy), ()):
                key = (x, y)
                if (any(k in tags for k in USE_KEYS) and key not in taken
                        and zone.contains(Point(x, y))):
                    taken.add(key)
                    out.append((x, y, tags))
    return [tags for _x, _y, tags in out]


def _entrances_inside(grid: dict, px: list) -> list[tuple[float, float, dict]]:
    """Entrance nodes on or just outside a building outline, in map tiles."""
    if not grid:
        return []
    from shapely.geometry import Point
    poly = Polygon(px)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zone = poly.buffer(1.5)
    minx, miny, maxx, maxy = zone.bounds
    out = []
    for gx in range(int(minx) // 16, int(maxx) // 16 + 1):
        for gy in range(int(miny) // 16, int(maxy) // 16 + 1):
            for x, y, tags in grid.get((gx, gy), ()):
                if "entrance" in tags and zone.contains(Point(x, y)):
                    out.append((x, y, tags))
    return out


def _entrances_by_unit(entrances: list[tuple[float, float, dict]], units
                       ) -> list[list[tuple[float, float, dict]]]:
    """Assign each mapped entrance to its closest unit and make it local."""
    assigned = [[] for _ in units]
    for x, y, tags in entrances:
        closest = None
        for i, unit in enumerate(units):
            lx, ly = x - unit.x0, y - unit.y0
            ix0, iy0 = math.floor(lx), math.floor(ly)
            distance = float("inf")
            for iy in range(max(0, iy0 - 1), min(unit.height, iy0 + 2)):
                for ix in range(max(0, ix0 - 1), min(unit.width, ix0 + 2)):
                    if not unit.mask[iy, ix]:
                        continue
                    dx = max(ix - lx, 0.0, lx - ix - 1)
                    dy = max(iy - ly, 0.0, ly - iy - 1)
                    distance = min(distance, dx * dx + dy * dy)
            if closest is None or distance < closest[0]:
                closest = (distance, i, lx, ly)
        if closest is not None and closest[0] <= 2.25:
            _distance, i, lx, ly = closest
            assigned[i].append((lx, ly, tags))
    return assigned


def _rooms_by_unit(entries, fp, units, proj) -> list:
    """The building's mapped rooms (renderer._buildings_geojson), moved with
    the placed footprint and shared out between the units it was cut into.

    Returns one list per unit of (ring, kind): the ring in that unit's own
    tiles, kind from the OSM room tag where the game knows it (None = cut as
    drawn but furnished by the usual rules). A room whose centre falls in no
    unit - outside the footprint after squaring up - is left out.
    """
    out: list = [[] for _ in units]
    if not entries:
        return out
    turned = fp.point_rotation or fp.point_offset != (0.0, 0.0)
    for entry in entries:
        ring = entry.get("ring") or []
        if len(ring) < 3:
            continue
        pts = [proj.to_px(lat, lon) for lon, lat in ring]
        if turned:
            pts = [fp.transform_point(x, y) for x, y in pts]
        room = str(entry.get("room") or "").strip().lower()
        amenity = str(entry.get("amenity") or "").strip().lower()
        kind = MAPPED_ROOM_KINDS.get(room) or MAPPED_ROOM_KINDS.get(amenity)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        for n, unit in enumerate(units):
            if unit.x0 <= cx < unit.x0 + unit.width \
                    and unit.y0 <= cy < unit.y0 + unit.height:
                local = [(int(round(x - unit.x0)), int(round(y - unit.y0)))
                         for x, y in pts]
                out[n].append((local, kind))
                break
    return out


def _party_walls(owner: np.ndarray, me: int, x0: int, y0: int, mask: np.ndarray,
                 levels: list[int]) -> dict:
    """{(x, y, "N" or "W"): storeys of the neighbour} for each outside wall
    of building `me` with another building's tile beyond it, in the
    building's own coordinates, as doors and windows name wall edges."""
    out: dict = {}
    h, w = mask.shape
    mh, mw = owner.shape
    sub = owner[max(0, y0 - 1):min(mh, y0 + h + 1), max(0, x0 - 1):min(mw, x0 + w + 1)]
    if not ((sub >= 0) & (sub != me)).any():
        return out
    for ly in range(h):
        for lx in range(w):
            if not mask[ly, lx]:
                continue
            for dx, dy, edge in ((0, -1, (lx, ly, "N")), (0, 1, (lx, ly + 1, "N")),
                                 (-1, 0, (lx, ly, "W")), (1, 0, (lx + 1, ly, "W"))):
                nx, ny = lx + dx, ly + dy
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx]:
                    continue
                wx, wy = x0 + nx, y0 + ny
                if 0 <= wx < mw and 0 <= wy < mh:
                    other = owner[wy, wx]
                    if other >= 0 and other != me:
                        out[edge] = max(out.get(edge, 0), levels[other])
    return out
