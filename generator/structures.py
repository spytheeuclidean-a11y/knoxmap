"""Bridges, overpasses and monuments: the parts of a town that are not flat.

The terrain bitmap is one storey: everything painted into it lies on the
ground. A road on a bridge over another road used to be painted there too, so
the two met in a junction that does not exist, and an interchange was a knot of
tarmac. Here a way that OpenStreetMap puts above another (bridge=yes or a
layer above zero) is lifted where it crosses: a deck one storey up over the
road or railway beneath, reached by ramps of Build 42's sloped tiles
(ramps_01), which carry players and vehicles. The deck is railed, and stands on
concrete posts wherever a post does not land in the road below.

A bridge over water alone stays on the ground, as the game's own bridges do,
and gets railings along the water.

Monuments come out as what they are rather than as houses: an arch of stone
piers with a span across the top, an obelisk or column rising from a plinth, a
statue on a paved square, a tiered fountain.

The result is a list of tiles, each (x, y, level, layer, tile), which
knoxbuild/structures.py writes into lots like any building.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

# --- ramps -----------------------------------------------------------------

# ramps_01 (B42ChunkCaching2x.pack): four runs of twenty segments, each a
# twentieth of a storey higher than the last. From the game's tile
# definitions: SlopedSurfaceDirection N is highest at the north edge of the
# tile (IsoGridSquare.getSlopedSurfaceHeight lerps to the maximum at y = 0), so
# an "N" ramp climbs northwards; likewise S, W and E.
RAMP_FIRST = {"N": 0, "S": 24, "W": 48, "E": 72}
RAMP_STEPS = 20                      # segments, and so tiles, to climb a storey
MAX_LEVEL = 2


def ramp_tile(direction: str, segment: int) -> str:
    """The ramp piece `segment` (1..20) of a run climbing towards `direction`."""
    return f"ramps_01_{RAMP_FIRST[direction] + segment - 1}"


# A full-height ramp segment is a solid block of concrete one storey tall with
# a flat top: what the piers of an arch and the shaft of a column are built of.
BLOCK = ramp_tile("N", 20)
PLINTH = ramp_tile("N", 6)           # a block about a third of a storey tall

DECK_FLOOR = "blends_street_01_64"   # street3, the tarmac of ordinary streets
PAVING = "floors_exterior_tilesandstone_01_0"
# fencing_01, black metal railing (knoxbuild/fences.py STYLES["black_metal"])
RAIL_W, RAIL_N, RAIL_NW = "fencing_01_002", "fencing_01_001", "fencing_01_003"
POST = "fencing_01_043"              # tall concrete post
STATUES = ["location_community_cemetary_01_11", "location_community_cemetary_01_12",
           "location_community_cemetary_01_13", "location_community_cemetary_01_14"]
FOUNTAIN = "location_community_park_01_48"
POST_EVERY = 8

ROAD_CATS = {"road_major", "road_medium", "road_minor", "road_service",
             "pedestrian"}
PATH_CATS = {"paved_path", "dirt_path"}
# What a deck has to clear. Footpaths pass under a bridge at its abutment
# often enough that lifting a road over each would raise half the bridges in a
# park for nothing.
CLEARS = ROAD_CATS | {"railway"}
LIFTS = ROAD_CATS | PATH_CATS | {"railway"}


def level_of(tags: dict) -> int:
    """How many storeys above the ground OpenStreetMap puts a way, 0..2."""
    raw = str(tags.get("layer", "0")).split(";")[0].strip()
    try:
        layer = int(float(raw))
    except (ValueError, OverflowError):      # OverflowError: "inf", "1e999"
        layer = 0
    bridge = tags.get("bridge") not in (None, "no")
    if bridge:
        layer = max(layer, 1)
    return max(0, min(MAX_LEVEL, layer))


@dataclass
class Plan:
    tiles: dict = field(default_factory=dict)      # (x, y, level, layer) -> tile
    cut: dict = field(default_factory=dict)        # feature id -> geometry to leave unpainted
    clear_veg: set = field(default_factory=set)    # (x, y) with no tree or bush
    water_rails: list = field(default_factory=list)  # footprints to rail along water
    paving: list = field(default_factory=list)     # polygons to pave on the ground
    not_buildings: set = field(default_factory=set)  # building ids made monuments
    posts: list = field(default_factory=list)      # (x, y, top level) under decks
    straight: list = field(default_factory=list)   # (rectangle, category) squared bridges
    bridges: int = 0
    monuments: int = 0

    def put(self, x: int, y: int, level: int, layer: str, tile: str) -> None:
        self.tiles[(x, y, level, layer)] = tile

    def rows(self) -> list:
        return [[x, y, z, layer, t] for (x, y, z, layer), t in sorted(self.tiles.items())]


# --- bridges ---------------------------------------------------------------

def _line_px(feat, proj) -> LineString | None:
    if feat.kind != "way" or len(feat.geometry) < 2:
        return None
    pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
    line = LineString(pts)
    return line if line.length > 0 else None


def _key(pt) -> tuple[int, int]:
    return (round(pt[0] * 4), round(pt[1] * 4))


def _chains(upper: list) -> list[list]:
    """Upper ways of one level joined end to end into runs."""
    by_end: dict = {}
    for i, (feat, line, level, cat, width) in enumerate(upper):
        for end in (line.coords[0], line.coords[-1]):
            by_end.setdefault((_key(end), level), []).append(i)
    seen: set = set()
    runs = []
    for i in range(len(upper)):
        if i in seen:
            continue
        stack, group = [i], []
        seen.add(i)
        while stack:
            j = stack.pop()
            group.append(j)
            line, level = upper[j][1], upper[j][2]
            for end in (line.coords[0], line.coords[-1]):
                for k in by_end.get((_key(end), level), ()):
                    if k not in seen:
                        seen.add(k)
                        stack.append(k)
        runs.append(group)
    return runs


def _join(lines: list[LineString]) -> list[LineString]:
    from shapely.ops import linemerge
    merged = linemerge(lines)
    return list(getattr(merged, "geoms", [merged]))


def _extend(line: LineString, ground_ends: dict, need: float, used: set) -> LineString:
    """The run carried on at both ends along the ground ways it joins, until
    there is room for its ramps."""
    coords = list(line.coords)
    for at_start in (True, False):
        added = 0.0
        while added < need:
            end = coords[0] if at_start else coords[-1]
            prev = coords[1] if at_start else coords[-2]
            heading = math.atan2(end[1] - prev[1], end[0] - prev[0])
            best, best_turn = None, None
            for idx, gline in ground_ends.get(_key(end), ()):
                if idx in used:
                    continue
                g = list(gline.coords)
                if _key(g[-1]) == _key(end):
                    g.reverse()
                if len(g) < 2:
                    continue
                h2 = math.atan2(g[1][1] - g[0][1], g[1][0] - g[0][0])
                turn = abs((h2 - heading + math.pi) % (2 * math.pi) - math.pi)
                if turn < math.radians(50) and (best_turn is None or turn < best_turn):
                    best, best_turn = (idx, g), turn
            if best is None:
                break
            idx, g = best
            used.add(idx)
            seg = LineString(g)
            added += seg.length
            if at_start:
                coords = list(reversed(g[1:])) + coords
            else:
                coords = coords + g[1:]
    return LineString(coords)


def _profile(zones: list[tuple[float, float]], level: int, length: float):
    """Height along a run: `level` over the zones, falling one storey every
    RAMP_STEPS tiles either side. None when the run is too short for its
    ramps."""
    # One deck from the first crossing to the last: the whole run is a bridge,
    # and one that came down to the ground between two roads it crosses would
    # put a ramp in the middle of a viaduct.
    merged = [[min(a for a, _ in zones), max(b for _, b in zones)]]
    reach = RAMP_STEPS * level
    if merged[0][0] < reach or length - merged[-1][1] < reach:
        return None

    def h(s: float) -> float:
        best = 0.0
        for a, b in merged:
            d = a - s if s < a else s - b if s > b else 0.0
            best = max(best, level - d / RAMP_STEPS)
        return max(0.0, min(float(level), best))
    return h, merged


def plan_bridges(buckets: dict, proj, meters_per_tile: float, way_width, plan: Plan) -> None:
    ways = []
    # Ramps run on past the map's edge into what was downloaded around it.
    frame = box(-60, -60, proj.width + 60, proj.height + 60)
    for cat in LIFTS:
        for feat in buckets.get(cat, []):
            line = _line_px(feat, proj)
            if line is None or feat.geometry[0] == feat.geometry[-1] and len(feat.geometry) > 3:
                continue
            if not line.intersects(frame):
                continue
            width = max(1.0, way_width(feat, cat) / meters_per_tile)
            ways.append((feat, line, level_of(feat.tags), cat, width))
    upper = [w for w in ways if w[2] >= 1]
    if not upper:
        return
    ground = [w for w in ways if w[2] == 0]
    ground_ends: dict = {}
    for i, w in enumerate(ground):
        if w[3] in ROAD_CATS or w[3] in PATH_CATS or w[3] == "railway":
            for end in (w[1].coords[0], w[1].coords[-1]):
                ground_ends.setdefault(_key(end), []).append((i, w[1]))

    from shapely.strtree import STRtree
    below_lines = [w[1] for w in ways if w[3] in CLEARS]
    below_info = [w for w in ways if w[3] in CLEARS]
    tree = STRtree(below_lines) if below_lines else None

    used: set = set()
    for group in _chains(upper):
        parts = [upper[i] for i in group]
        level = parts[0][2]
        cat = parts[0][3]
        width = max(p[4] for p in parts)
        for run in _join([p[1] for p in parts]):
            if run.length < 2:
                continue
            zones = []
            for j in (tree.query(run) if tree is not None else []):
                other = below_info[j]
                if other[2] >= level or other[0] in (p[0] for p in parts):
                    continue
                cross = run.intersection(other[1])
                points = [g for g in getattr(cross, "geoms", [cross])
                          if g.geom_type == "Point"]
                ends = [Point(run.coords[0]), Point(run.coords[-1]),
                        Point(other[1].coords[0]), Point(other[1].coords[-1])]
                for pt in points:
                    # A way that only joins this one at an end is its approach,
                    # not something passing under it.
                    if any(pt.distance(e) < 1.0 for e in ends):
                        continue
                    s = run.project(pt)
                    # Clear the road beneath and its pavements, measured along
                    # this run: a shallow crossing is a long one.
                    a = run.interpolate(max(0, s - 1)).coords[0]
                    b = run.interpolate(min(run.length, s + 1)).coords[0]
                    oc = other[1].project(pt)
                    c = other[1].interpolate(max(0, oc - 1)).coords[0]
                    d = other[1].interpolate(min(other[1].length, oc + 1)).coords[0]
                    v1 = (b[0] - a[0], b[1] - a[1])
                    v2 = (d[0] - c[0], d[1] - c[1])
                    n1, n2 = math.hypot(*v1), math.hypot(*v2)
                    sin = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (n1 * n2) if n1 and n2 else 1
                    half = (other[4] / 2 + 3) / max(sin, 0.35) + width / 2
                    zones.append((s - half, s + half))
            if not zones:
                deck = _squared(run, width)
                if deck is not None:
                    # Laid square to the tiles, as the game's own bridges are:
                    # painted along its real angle a bridge over a river was a
                    # staircase of tarmac with jagged edges.
                    plan.straight.append((deck, cat))
                    for p in parts:
                        plan.cut[id(p[0])] = run.buffer(width / 2 + 6, cap_style=2)
                    plan.water_rails.append(deck)
                else:
                    plan.water_rails.append(run.buffer(width / 2, cap_style=2))
                continue
            # A flyover is only walkable where its ramps line up with the tile
            # grid. Laid along a diagonal the ramp tiles step one at a time and
            # never join the deck, so the player sees a bridge over the street
            # and cannot get onto it. A diagonal crossing is left at ground
            # level instead: it meets the road below as a junction, which a
            # player can use. Axis-aligned flyovers keep their ramps.
            (ax, ay), (bx, by) = run.coords[0], run.coords[-1]
            dx, dy = abs(bx - ax), abs(by - ay)
            if zones and min(dx, dy) > 0.2 * max(dx, dy):
                continue
            offset_line = _extend(run, ground_ends, RAMP_STEPS * level + 4, used)
            # Where the run starts inside the extended line.
            shift = offset_line.project(Point(run.coords[0]))
            zones = [(a + shift, b + shift) for a, b in zones]
            prof = _profile(zones, level, offset_line.length)
            if prof is None:
                continue
            h, merged = prof
            _lay_run(plan, offset_line, h, level, width, cat, proj)
            plan.bridges += 1
            # Leave the deck out of the ground painting.
            lifted = []
            for a, b in merged:
                lo = max(0.0, a - RAMP_STEPS * (level - 1) - 1)
                hi = min(offset_line.length, b + RAMP_STEPS * (level - 1) + 1)
                lifted.append(_substring(offset_line, lo, hi).buffer(width / 2 + 4, cap_style=2))
            cut = unary_union(lifted)
            for p in parts:
                key = id(p[0])
                plan.cut[key] = cut if key not in plan.cut else plan.cut[key].union(cut)


# How far a bridge may be off square and still be laid square: the ends of the
# squared deck have to meet the roads at both banks, so the deck widens by how
# far the ends are apart across it, up to this many times the road's width.
SQUARE_WIDEN = 1.5


def _squared(run: LineString, width: float):
    """The run as a rectangle along the nearer axis, or None when it is too
    far off square to be laid that way."""
    (ax, ay), (bx, by) = run.coords[0], run.coords[-1]
    along_x = abs(bx - ax) >= abs(by - ay)
    offset = abs(by - ay) if along_x else abs(bx - ax)
    if offset > SQUARE_WIDEN * width or run.length < 4:
        return None
    half = width / 2
    if along_x:
        lo, hi = sorted((ax, bx))
        c0, c1 = sorted((ay, by))
        return box(math.floor(lo), math.floor(c0 - half), math.ceil(hi), math.ceil(c1 + half))
    lo, hi = sorted((ay, by))
    c0, c1 = sorted((ax, bx))
    return box(math.floor(c0 - half), math.floor(lo), math.ceil(c1 + half), math.ceil(hi))


def _substring(line: LineString, a: float, b: float) -> LineString:
    from shapely.ops import substring
    return substring(line, a, b)


def _covered_tiles(shape, x0, y0, x1, y1):
    """Tile centres inside the shape, in row order, without per-tile Points."""
    import numpy as np
    from shapely import contains_xy

    xs = np.arange(x0, x1, dtype=float) + 0.5
    for y in range(y0, y1):
        for offset in np.flatnonzero(contains_xy(shape, xs, y + 0.5)):
            yield x0 + int(offset), y


def _lay_run(plan: Plan, line: LineString, h, level: int, width: float, cat: str, proj) -> None:
    half = width / 2
    area = line.buffer(half, cap_style=2)
    x0, y0, x1, y1 = (int(math.floor(v)) for v in area.bounds)
    deck: dict[int, set] = {}
    ramps: set = set()
    tops: list = []
    for x, y in _covered_tiles(area, max(0, x0), max(0, y0),
                               min(proj.width, x1 + 1), min(proj.height, y1 + 1)):
        centre = Point(x + 0.5, y + 0.5)
        s = line.project(centre)
        height = h(s)
        if height <= 0:
            continue
        steps = int(round(height * RAMP_STEPS))
        z, seg = divmod(steps, RAMP_STEPS)
        if steps == 0:
            continue
        plan.clear_veg.add((x, y))
        if seg == 0:
            plan.put(x, y, z, "Floor", DECK_FLOOR)
            deck.setdefault(z, set()).add((x, y))
            continue
        ahead = line.interpolate(min(line.length, s + 1)).coords[0]
        behind = line.interpolate(max(0.0, s - 1)).coords[0]
        dx, dy = ahead[0] - behind[0], ahead[1] - behind[1]
        if h(min(line.length, s + 1)) < h(max(0.0, s - 1)):
            dx, dy = -dx, -dy
        if abs(dx) >= abs(dy):
            direction = "E" if dx > 0 else "W"
        else:
            direction = "S" if dy > 0 else "N"
        plan.put(x, y, z, "Floor", ramp_tile(direction, seg))
        ramps.add((x, y))
        if seg == RAMP_STEPS - 1:
            tops.append((x, y, z, direction))
    _cap_tops(plan, tops, deck, proj)
    footprint = set(ramps).union(*deck.values()) if deck else set(ramps)
    for z, tiles in deck.items():
        _rail(plan, tiles, footprint, z)
        _posts(plan, tiles, footprint, z)


def _cap_tops(plan: Plan, tops: list, deck: dict, proj) -> None:
    """Lay the deck a ramp climbs to when rounding left it short.

    A last segment at 19/20 storey with nothing at the next level is a ramp
    that tops out in mid-air: the player walks up and cannot step off.
    """
    ahead = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}
    for x, y, z, direction in tops:
        if any((x + dx, y + dy) in deck.get(z + 1, ())
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            continue
        dx, dy = ahead[direction]
        nx, ny = x + dx, y + dy
        if not (0 <= nx < proj.width and 0 <= ny < proj.height):
            nx, ny = x, y
        plan.put(nx, ny, z + 1, "Floor", DECK_FLOOR)
        deck.setdefault(z + 1, set()).add((nx, ny))
        plan.clear_veg.add((nx, ny))


def _rail(plan: Plan, tiles: set, footprint: set, z: int) -> None:
    edges: dict = {}
    for x, y in tiles:
        if (x - 1, y) not in footprint:
            edges.setdefault((x, y), set()).add("W")
        if (x + 1, y) not in footprint:
            edges.setdefault((x + 1, y), set()).add("W")
        if (x, y - 1) not in footprint:
            edges.setdefault((x, y), set()).add("N")
        if (x, y + 1) not in footprint:
            edges.setdefault((x, y + 1), set()).add("N")
    for (x, y), sides in edges.items():
        tile = RAIL_NW if len(sides) == 2 else RAIL_W if "W" in sides else RAIL_N
        plan.put(x, y, z, "Furniture", tile)


def _posts(plan: Plan, tiles: set, footprint: set, z: int) -> None:
    edge = sorted((x, y) for x, y in tiles
                  if any(n not in footprint for n in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))))
    for x, y in edge:
        if (x * 7 + y * 13) % POST_EVERY:
            continue
        plan.posts.append((x, y, z))


def rail_water(plan: Plan, landscape, water_colour) -> None:
    """Railings along the sides of bridges over water, and posts that would
    stand in a road taken back out."""
    px = landscape.load()
    w, h = landscape.size
    for shape in plan.water_rails:
        x0, y0, x1, y1 = (int(math.floor(v)) for v in shape.bounds)
        tiles = set(_covered_tiles(shape, max(0, x0), max(0, y0),
                                   min(w, x1 + 1), min(h, y1 + 1)))
        for x, y in tiles:
            for (nx, ny), (ex, ey, side) in (((x - 1, y), (x, y, "W")), ((x + 1, y), (x + 1, y, "W")),
                                             ((x, y - 1), (x, y, "N")), ((x, y + 1), (x, y + 1, "N"))):
                if (nx, ny) in tiles or not (0 <= nx < w and 0 <= ny < h):
                    continue
                if px[nx, ny] != water_colour:
                    continue
                prev = plan.tiles.get((ex, ey, 0, "Furniture"))
                sides = {side}
                if prev in (RAIL_W, RAIL_NW):
                    sides.add("W")
                if prev in (RAIL_N, RAIL_NW):
                    sides.add("N")
                tile = RAIL_NW if len(sides) == 2 else RAIL_W if "W" in sides else RAIL_N
                plan.put(ex, ey, 0, "Furniture", tile)


def settle_posts(plan: Plan, is_clear) -> None:
    """Stand the posts under the decks, except where one would land in the
    road, railway or water beneath."""
    for x, y, top in plan.posts:
        if not is_clear(x, y):
            continue
        for level in range(top):
            plan.put(x, y, level, "Furniture2", POST)


# --- monuments -------------------------------------------------------------

NOT_MONUMENT_MEMORIALS = {"building", "plaque", "blue_plaque", "bench", "tree",
                          "ghost_bike", "stolperstein", "grave"}
MONUMENT_BUILDINGS = {"triumphal_arch", "monument", "memorial", "obelisk"}
MAX_MONUMENT_M2 = 900

# Towers. These are the things a town is navigated by and nobody walks into:
# the water tower on the ridge, the lighthouse, the mill, the clock tower over
# the square. classify_building() has no kind for any of them, so they were
# ordinary housing - thinned like a house, grown like a house and furnished
# with a sofa and two bedrooms. They are built as what they are instead, and
# taken off the building list the way an obelisk already is.
TOWER_MAN_MADE = {"water_tower", "lighthouse", "windmill", "tower", "silo",
                 "grain_elevator"}
# man_made=tower is also every phone mast and floodlight there is, and a
# hundred concrete blocks up the hillside is not a landmark. Only the towers
# somebody would give directions by.
TOWER_TYPES = {"clock", "bell_tower", "observation", "watchtower", "defensive",
               "campanile", "cooling", "water_tower", "spire"}
# A bell tower is a church's, and is called what it is: a steeple, so that it
# gets a spire and not the flat top every other man_made=tower gets.
STEEPLE_TYPES = {"bell_tower", "campanile", "spire"}
# How tall each stands when OpenStreetMap does not say, in storeys.
TOWER_LEVELS = {"water_tower": 6, "lighthouse": 7, "windmill": 4, "tower": 5,
                "steeple": 6, "silo": 6, "pylon": 5}
# A tower is tall, not broad: past this the footprint is the base it stands on
# and the shaft rises from the middle of it.
TOWER_SHAFT = 3


def tower_kind(tags: dict) -> str | None:
    """water_tower, lighthouse, windmill, tower, steeple, silo or pylon; None else.

    The last two are not towers of a town but landmarks all the same: a grain
    silo stands over the yard it is on, and a transmission tower is one of the
    few things seen over a county line, so they are built as their own
    silhouettes rather than left out of the map (an untagged silo is on
    knoxbuild/build.py's list of things that are not buildings).
    """
    if (tags.get("power") or "").lower() == "tower":
        return "pylon"                     # a transmission tower, power=tower
    made = (tags.get("man_made") or "").lower()
    if made not in TOWER_MAN_MADE:
        made = (tags.get("building") or "").lower()
        if made not in TOWER_MAN_MADE:
            return None
    if made in {"silo", "grain_elevator"}:
        return "silo"
    if made == "tower":
        kind = (tags.get("tower:type") or "").lower()
        if kind in STEEPLE_TYPES:
            return "steeple"
        if kind not in TOWER_TYPES:
            return None
    return made


def monument_kind(tags: dict) -> str | None:
    """arch, column, statue, fountain, stone or tower; None for anything else."""
    historic = tags.get("historic")
    memorial = (tags.get("memorial") or tags.get("monument") or "").lower()
    artwork = (tags.get("artwork_type") or "").lower()
    name = (tags.get("name") or "").lower()
    building = tags.get("building")
    if tags.get("amenity") == "fountain":
        return "fountain"
    if tower_kind(tags):
        return "tower"
    if tags.get("man_made") == "obelisk" or memorial in {"obelisk", "column"}:
        return "column"
    if building == "triumphal_arch" or memorial == "arch" or (
            historic in {"monument", "memorial"} and ("arch" in name.split() or " arch" in name)):
        return "arch"
    if historic in {"monument", "memorial"}:
        if memorial in NOT_MONUMENT_MEMORIALS:
            return None
        if memorial in {"statue", "bust", "sculpture"}:
            return "statue"
        if memorial in {"stone", "war_memorial", "stele", "cross"}:
            return "stone"
        return "statue"
    if tags.get("tourism") == "artwork" and artwork in {"statue", "bust", "sculpture", "stone", ""}:
        if tags.get("leisure") or tags.get("landuse"):
            return None
        return "statue" if artwork != "stone" else "stone"
    return None


def _storeys(tags: dict, default: int, meters_per_level: float = 3.0) -> int:
    try:
        metres = float(str(tags.get("height", "")).split()[0])
        return max(1, min(8, int(round(metres / meters_per_level))))
    except (ValueError, IndexError, OverflowError):    # "inf" and "1e999" read as numbers
        return default


def plan_piers(buckets: dict, proj, meters_per_tile: float, way_width,
               plan: Plan) -> None:
    """Railings along a pier, where it stands over the water.

    A jetty is painted onto the ground like a path and left there, as the
    game's own bridges over water are - the terrain bitmap is one storey, and
    a deck raised over water in a game with no swimming is a deck nobody can
    reach the underneath of. What it was missing is the railing: a pier ran
    out into a river with nothing along either side, so it read as a concrete
    strip laid on the water rather than as something built over it, and you
    walked off the end of it without a thing in the way.

    The same pass that rails a bridge over water does this one (rail_water):
    it puts a rail on every edge whose neighbour is water, so the landward end
    where the pier meets the bank is left open by itself.
    """
    for feat in buckets.get("pier", []):
        line = _line_px(feat, proj)
        if line is None or line.length < 2:
            continue
        width = max(1.0, way_width(feat, "pier") / meters_per_tile)
        plan.water_rails.append(line.buffer(width / 2, cap_style=2))


def plan_monuments(feats: list, proj, meters_per_tile: float, plan: Plan) -> None:
    for feat in feats:
        kind = monument_kind(feat.tags)
        if kind is None:
            continue
        if feat.kind == "node":
            x, y = proj.to_px(*feat.geometry[0])
            shape = box(x - 1.5, y - 1.5, x + 1.5, y + 1.5)
        elif feat.kind == "way" and len(feat.geometry) >= 4 and feat.geometry[0] == feat.geometry[-1]:
            shape = Polygon([proj.to_px(la, lo) for la, lo in feat.geometry])
            if not shape.is_valid or shape.area * meters_per_tile ** 2 > MAX_MONUMENT_M2:
                continue
            levels = feat.tags.get("building:levels")
            if levels and kind not in ("arch", "tower"):
                try:
                    if float(levels) > 1:
                        continue
                except ValueError:
                    pass
        else:
            continue
        if not (0 <= shape.centroid.x < proj.width and 0 <= shape.centroid.y < proj.height):
            continue
        if kind == "fountain" and feat.kind == "way":
            # A fountain drawn as its basin is painted as water already; the
            # tiers stand in the middle of it.
            c = shape.centroid
            if shape.area >= 9:
                plan.put(int(c.x), int(c.y), 0, "Furniture", FOUNTAIN)
                plan.monuments += 1
            continue
        if "building" in feat.tags:
            plan.not_buildings.add(id(feat))
        if kind == "tower" and tower_kind(feat.tags) not in ("silo", "pylon"):
            # A silo stands on the yard it serves and a mast on the verge: a
            # paved square round either would be a plaza in a wheat field.
            plan.paving.append(shape.buffer(1.0, join_style=2))
        {"arch": _arch, "column": _column, "statue": _statue,
         "fountain": _fountain, "stone": _stone, "tower": _tower}[kind](plan, shape, feat.tags)
        plan.monuments += 1


def _cells(shape) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = (int(math.floor(v)) for v in shape.bounds)
    cells = list(_covered_tiles(shape, x0, y0, x1 + 1, y1 + 1))
    if not cells:
        c = shape.centroid
        cells = [(int(c.x), int(c.y))]
    return cells


def _arch(plan: Plan, shape, tags: dict) -> None:
    cells = _cells(shape)
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    along_x = (x1 - x0) >= (y1 - y0)
    length = (x1 - x0 + 1) if along_x else (y1 - y0 + 1)
    pier = max(2, min(4, length // 3))
    # Tall enough that the opening reads as one: a storey of span over at
    # least two of open air.
    height = max(3, min(6, _storeys(tags, 4, 3.0)))
    for x, y in cells:
        t = (x - x0) if along_x else (y - y0)
        in_pier = t < pier or t >= length - pier
        for z in range(height):
            if in_pier or z == height - 1:
                plan.put(x, y, z, "Floor", BLOCK)
        if not in_pier:
            plan.put(x, y, 0, "Floor", PAVING)


def _column(plan: Plan, shape, tags: dict) -> None:
    c = shape.centroid
    cx, cy = int(c.x), int(c.y)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            plan.put(cx + dx, cy + dy, 0, "Floor", PLINTH)
    height = max(2, min(8, _storeys(tags, 4)))
    for z in range(height):
        plan.put(cx, cy, z, "Floor", BLOCK)


def _tower(plan: Plan, shape, tags: dict) -> None:
    """A shaft rising from its footprint, topped the way its kind is known by.

    Seen from the far side of town - which is how these are seen, since nobody
    walks into one - the silhouette is the whole of it: a tank on legs, a lamp
    room on a shaft, a mill under its cap, a spire, a domed silo, a lattice
    mast with its arms out. The same shaft is drawn for all of them with a
    different top, so what a tower reads as is decided by its kind and nothing
    else.
    """
    kind = tower_kind(tags) or "tower"
    cells = _cells(shape)
    cx, cy = int(shape.centroid.x), int(shape.centroid.y)
    half = TOWER_SHAFT // 2
    shaft = [(x, y) for x, y in cells
             if abs(x - cx) <= half and abs(y - cy) <= half] or [(cx, cy)]
    height = max(2, min(8, _storeys(tags, TOWER_LEVELS.get(kind, 5))))
    if kind == "pylon":
        # A transmission tower is a mast, not a building: one square from the
        # ground to the top, and two pairs of arms out along both axes below
        # the highest wire, which is what makes it a pylon and not a flagpole.
        for z in range(height):
            plan.put(cx, cy, z, "Floor", BLOCK)
        for z in (height - 3, height - 2):
            if z < 0:
                continue
            for x in range(cx - half, cx + half + 1):
                if x != cx:
                    plan.put(x, cy, z, "Furniture", RAIL_W)
            for y in range(cy - half, cy + half + 1):
                if y != cy:
                    plan.put(cx, y, z, "Furniture", RAIL_N)
        return
    # A spire narrows above the shaft, so the shaft itself stops short and the
    # needle is drawn on top of nothing.
    body = height - 2 if kind == "steeple" else height
    for z in range(body):
        for x, y in shaft:
            plan.put(x, y, z, "Floor", BLOCK)
    if kind == "silo":
        # A cylinder with a domed cap: wider than the shaft all the way up, so
        # it stands as a drum over the farmyard rather than a needle.
        for z in range(height):
            for x, y in cells:
                plan.put(x, y, z, "Floor", BLOCK)
        plan.put(cx, cy, height, "Floor", PLINTH)
    elif kind == "steeple":
        # A spire: the shaft, then one square that rises to a point over the
        # roof it stands beside.
        for z in range(body, height):
            plan.put(cx, cy, z, "Floor", BLOCK)
        plan.put(cx, cy, height, "Floor", PLINTH)
    elif kind == "water_tower":
        # The tank, wider than the legs it stands on.
        for z in range(max(0, height - 2), height):
            for x, y in cells:
                plan.put(x, y, z, "Floor", BLOCK)
    else:
        # A lighthouse or a mill: a shaft on its base, and a cap on top that a
        # sawmill or a lamp room sits under.
        for x, y in cells:
            if (x, y) not in shaft:
                plan.put(x, y, 0, "Floor", PLINTH)
        plan.put(cx, cy, height, "Floor", PLINTH)


def _statue(plan: Plan, shape, tags: dict) -> None:
    c = shape.centroid
    cx, cy = int(c.x), int(c.y)
    plan.put(cx, cy, 0, "Furniture", STATUES[(cx * 3 + cy) % len(STATUES)])


def _fountain(plan: Plan, shape, tags: dict) -> None:
    c = shape.centroid
    cx, cy = int(c.x), int(c.y)
    plan.put(cx, cy, 0, "Furniture", FOUNTAIN)


def _stone(plan: Plan, shape, tags: dict) -> None:
    c = shape.centroid
    cx, cy = int(c.x), int(c.y)
    plan.put(cx, cy, 0, "Floor", ramp_tile("N", 10))
