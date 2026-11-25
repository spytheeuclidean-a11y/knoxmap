"""Turn OSM fence and wall lines into Project Zomboid fence tiles.

A fence in the game is a tile on a tile's west or north edge, the way a wall
is. The styles below are copied from the mapping tools' Fences.txt, which is
what WorldEd's own fence tool draws with, and placed by the same rule that
tool uses (FenceTool::getWestEdgeTiles and its north twin in TileZed): along a
west edge, west1 and west2 alternate; along a north edge, north1 and north2;
a tile carrying both takes the corner piece; a loose end gets a post.

The fences are written as furniture in a building with no rooms, one per map
cell, so they compile into the lots like anything else in a .tbx.
"""
from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from xml.sax.saxutils import quoteattr

import knoxfiles

from . import catalog as C

CELL = 300

# From PZ_Mapping_Tools/config/Fences.txt. Names are zero-padded to three
# digits, the form BuildingFurniture.txt uses; both parse to the same tile.
STYLES = {
    "short_wooden": dict(west1=35, west2=34, north1=32, north2=33, nw=36, post=37),
    "tall_wooden": dict(west1=11, west2=10, north1=8, north2=9, nw=12, post=13),
    "short_chainlink": dict(west1=27, west2=26, north1=24, north2=25, nw=28, post=29),
    "tall_chainlink": dict(west1=59, west2=58, north1=56, north2=57, nw=60, post=61),
    "white_picket": dict(west1=4, west2=4, north1=5, north2=5, nw=6, post=7),
    "cattle": dict(west1=20, west2=20, north1=21, north2=21, nw=18, post=19),
    "black_metal": dict(west1=2, west2=2, north1=1, north2=1, nw=3, post=0),
    # The full-height bars of the Rosewood base wall. The game has both and
    # OSM says which: metal bars two metres tall came out half that, because
    # a fence's height was never read.
    "tall_metal": dict(west1=67, west2=66, north1=64, north2=65, nw=68, post=69),
    "short_picket": dict(west1=121, west2=121, north1=120, north2=120,
                         nw=122, post=123),
    "tall_concrete": dict(west1=40, west2=40, north1=41, north2=41, nw=42, post=43),
    "military_wire": dict(west1=51, west2=50, north1=48, north2=49, nw=52, post=53),
    "tall_corrugated": dict(west1=72, west2=72, north1=73, north2=73, nw=75, post=74),
}
STYLES["short_corrugated"] = STYLES["short_wooden"]
STYLES["krest"] = STYLES["black_metal"]

# Which of a pair is the taller, and the height in metres at which a fence
# becomes it. OSM fence heights are mostly 0.9 to 2.4; the game's short
# fences are waist high and its tall ones are over your head.
TALLER = {
    "short_wooden": ("tall_wooden", 1.4),
    "short_chainlink": ("tall_chainlink", 1.7),
    "black_metal": ("tall_metal", 1.7),
    "short_picket": ("white_picket", 1.0),
    "short_corrugated": ("tall_corrugated", 1.4),
}
SHORTER = {tall: short for short, (tall, _m) in TALLER.items()}
HEIGHT = re.compile(
    r"""(?:(?P<metres>\d+(?:[.,]\d+)?)\s*(?:m|metres?|meters?)?"""
    r"""|(?P<feet>\d+(?:[.,]\d+)?)\s*(?:ft|['′])\s*(?:(?P<inches>\d+)\s*(?:in|["″]))?)"""
)


def height_m(tags: dict) -> float | None:
    """A fence's height in metres, from however the mapper wrote it.

    "2", "2 m", "2.5m" and "6'" all occur; anything else is no answer rather
    than a guess.
    """
    for key in ("height", "est_height"):
        match = HEIGHT.fullmatch(str(tags.get(key) or "").strip().lower())
        if match is None:
            continue
        if match["metres"] is not None:
            metres = float(match["metres"].replace(",", "."))
        else:
            inches = int(match["inches"] or 0)
            if inches >= 12:
                continue
            metres = float(match["feet"].replace(",", ".")) * 0.3048 + inches * 0.0254
        if 0.2 <= metres <= 12.0:
            return metres
    return None


def by_height(style: str, metres: float | None) -> str:
    """The same fence at the height the mapper gave it."""
    if metres is None:
        return style
    short = SHORTER.get(style, style)
    taller, at = TALLER.get(short, (None, 0.0))
    if taller is None:
        return style
    return taller if metres >= at else short


# Gates, for the fences drawn round back yards: (west-edge tile, north-edge tile).
GATES = {
    "short_wooden": ("fixtures_doors_fences_01_004", "fixtures_doors_fences_01_005"),
    "tall_wooden": ("fixtures_doors_fences_01_012", "fixtures_doors_fences_01_013"),
    "white_picket": ("fixtures_doors_fences_01_008", "fixtures_doors_fences_01_009"),
    "short_chainlink": ("fixtures_doors_fences_01_016", "fixtures_doors_fences_01_017"),
    "black_metal": ("fixtures_doors_fences_01_000", "fixtures_doors_fences_01_001"),
    "krest": ("fixtures_doors_fences_01_000", "fixtures_doors_fences_01_001"),
    "short_corrugated": ("fixtures_doors_fences_01_004", "fixtures_doors_fences_01_005"),
    "tall_corrugated": ("fixtures_doors_fences_01_012", "fixtures_doors_fences_01_013"),
}


def _tile(n: int) -> str:
    return f"fencing_01_{n:03d}"


FENCE_TILE_PROFILE = "fence_tiles.json"
FENCE_TILE_DEPENDENCIES = "fence_tile_dependencies.json"
TILE_ROLES = {"west1", "west2", "north1", "north2", "nw"}


def _palette(out_dir: str, allow_mod_tiles: bool) -> tuple[dict, dict, str | None, set[str]]:
    """Read a project's optional replacement tiles for individual fence styles."""
    styles = {style: {role: _tile(number) for role, number in tiles.items()}
              for style, tiles in STYLES.items()}
    gates = dict(GATES)
    path = os.path.join(out_dir, FENCE_TILE_PROFILE)
    if not allow_mod_tiles or not os.path.isfile(path):
        return styles, gates, None, set()
    try:
        config = knoxfiles.read(path, "custom fence tiles")
    except knoxfiles.Damaged as exc:
        raise knoxfiles.Damaged(f"Fix or remove {path}: {exc.__cause__}") from exc
    mod_id = config.get("mod_id") if isinstance(config, dict) else None
    overrides = config.get("styles") if isinstance(config, dict) else None
    if (not isinstance(mod_id, str) or not re.fullmatch(r"[\w.-]+", mod_id)
            or not isinstance(overrides, dict) or not overrides):
        raise knoxfiles.Damaged(f"{path} needs a mod_id and a non-empty styles object.")

    custom = set()
    for style, tiles in overrides.items():
        if style not in styles or not isinstance(tiles, dict):
            raise knoxfiles.Damaged(f"{path}: unknown fence style or invalid tiles: {style}.")
        if not TILE_ROLES <= tiles.keys() or tiles.keys() - (TILE_ROLES | {"post", "gate_w", "gate_n"}):
            raise knoxfiles.Damaged(f"{path}: {style} needs west1, west2, north1, north2 and nw.")
        if ("gate_w" in tiles) != ("gate_n" in tiles):
            raise knoxfiles.Damaged(f"{path}: {style} needs both gate_w and gate_n or neither.")
        for role, tile in tiles.items():
            prefix = "fixtures_doors_fences_" if role.startswith("gate_") else "fencing_"
            if not isinstance(tile, str) or not re.fullmatch(prefix + r"\w+_[0-9]+", tile):
                raise knoxfiles.Damaged(f"{path}: invalid {role} tile for {style}: {tile!r}.")
        styles[style] = {role: tile for role, tile in tiles.items() if not role.startswith("gate_")}
        gates.pop(style, None)
        if "gate_w" in tiles:
            gates[style] = (tiles["gate_w"], tiles["gate_n"])
        custom.update(tiles.values())
    return styles, gates, mod_id, custom


# Land uses that are fenced off in real life, and their smallest size in
# tiles - a hundred-tile "base" is a war memorial, not a barracks.
# An airfield is fenced right round in the game's own map, and it is the
# fence as much as the concrete that says what the place is. The least area
# is large because a fence round every private airstrip in a field would be
# a lot of fence for nothing.
FENCED_SITES = {"military": 400, "airfield": 20000}
CHAINLINK = {"chain_link", "chain", "mesh", "net", "welded_diamond_mesh", "temporary"}
WOODEN = {"wood", "wooden", "split_rail", "board", "paling", "slatted",
          "post_and_rail", "roundpole"}
METAL = {"metal", "railing", "railings", "metal_bars", "bars", "iron", "steel",
         "wrought_iron", "knee_rail"}
MASONRY = {"concrete", "brick", "stone", "masonry", "dry_stone", "gabion"}


def _fenced_sites(areas) -> list:
    """The land-use polygons that get a fence of their own."""
    out = []
    for shape, props in getattr(areas, "_items", []) or ():
        least = FENCED_SITES.get((props.get("category") or ""))
        if least is None or shape.is_empty or shape.area < least:
            continue
        if getattr(shape, "exterior", None) is not None:
            out.append(shape)
    return out


def _mapped_lines(runs: list[list]):
    """The fences somebody put there, as one geometry to ask about."""
    if not runs:
        return None
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    kept = [LineString(pts) for pts in runs if len(pts) >= 2]
    return unary_union(kept) if kept else None


def _crosses(pts: list, drawn) -> bool:
    """Whether this run of fence meets one that was mapped or drawn."""
    if drawn is None or len(pts) < 2:
        return False
    from shapely.geometry import LineString

    try:
        return LineString(pts).intersects(drawn)
    except Exception:          # noqa: BLE001 - a line that is not a line
        return False


def style_for(tags: dict, area: str | None) -> str:
    """Which fence a line gets: from its own tags first, its surroundings next.

    Where the mapper gave a height, that decides between the short and the
    tall version of the fence they asked for - the game has both of most of
    them, and two-metre metal bars used to come out as the waist-high railing.
    """
    barrier = tags.get("barrier")
    metres = height_m(tags)
    short_park = area in {"park", "playground"} and (metres is None or metres < 1.4)
    if barrier in {"wall", "retaining_wall", "city_wall"}:
        if short_park or (metres is not None and metres < 1.4 and barrier != "city_wall"):
            return "black_metal"
        return "tall_concrete"
    for tag in ("fence_type", "material"):
        kind = re.sub(r"[\s-]+", "_", str(tags.get(tag) or "").strip().lower())
        if kind in CHAINLINK:
            tall = kind == "temporary" or area in {"industrial", "military", "airfield"}
            return by_height("tall_chainlink" if tall else "short_chainlink", metres)
        if kind in WOODEN:
            return by_height("short_wooden" if short_park else "tall_wooden", metres)
        if kind in {"picket", "pales"}:
            return by_height("white_picket", metres)
        if kind == "corrugated_metal":
            return by_height("tall_corrugated", metres)
        if kind == "krest":
            return "krest"
        if kind in METAL:
            return by_height("black_metal", metres)
        if kind in {"barbed_wire", "electric", "wire"}:
            if (metres is not None and metres >= 1.7) or (metres is None and area == "military"):
                return "military_wire" if kind == "barbed_wire" else "tall_chainlink"
            return "cattle"
        if kind in MASONRY:
            return "black_metal" if short_park or (metres is not None and metres < 1.4) else "tall_concrete"
    if str(tags.get("fence_type") or "").strip().lower() == "panel":
        return "short_wooden" if short_park else by_height("tall_wooden", metres)
    return by_height({
        "industrial": "tall_chainlink", "military": "tall_chainlink",
        "airfield": "tall_chainlink",
        "schoolyard": "short_chainlink", "sports": "short_chainlink",
        "residential": "tall_wooden", "cemetery": "black_metal",
        "worship_grounds": "black_metal", "hospital_grounds": "black_metal",
    }.get(area or "", "short_wooden"), metres)


def _grid_path(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """A polyline as a walk along tile corners, one grid step at a time.

    Diagonal runs become staircases along tile edges - a fence can only stand
    on an edge - choosing at each corner the step that keeps closer to the
    real line.
    """
    path: list[tuple[int, int]] = []
    for start, finish in zip(points, points[1:]):
        # Snap a segment identically in both directions. Its rounded walk
        # depends on where the original segment crosses the grid.
        reverse = start > finish
        (ax, ay), (bx, by) = (finish, start) if reverse else (start, finish)
        segment: list[tuple[int, int]] = []
        steps = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) * 4)))
        for i in range(steps + 1):
            t = i / steps
            v = (int(round(ax + (bx - ax) * t)), int(round(ay + (by - ay) * t)))
            if not segment:
                segment.append(v)
                continue
            px, py = segment[-1]
            if v == (px, py):
                continue
            if v[0] != px and v[1] != py:
                # Two corners apart diagonally: go through whichever of the two
                # in-between corners sits nearer the true line.
                opt1, opt2 = (v[0], py), (px, v[1])
                mx, my = ax + (bx - ax) * t, ay + (by - ay) * t
                mid = min((opt1, opt2), key=lambda o: math.hypot(o[0] - mx, o[1] - my))
                segment.append(mid)
            segment.append(v)
        if reverse:
            segment.reverse()
        path.extend(segment[1:] if path and path[-1] == segment[0] else segment)
    return path


def _tarmac_mask(bmp_path: str, width: int, height: int):
    """True where the ground is a road, service lane or car park."""
    import numpy as np
    from generator import pz_colors as C

    from .bitmaps import read_rgb

    if not os.path.exists(bmp_path):
        return None
    ground = read_rgb(bmp_path)
    if ground.shape[:2] != (height, width):
        return None
    mask = np.zeros((height, width), dtype=bool)
    for colour in (C.LIGHT_ASPHALT, C.MEDIUM_ASPHALT, C.DARK_ASPHALT,
                   C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE):
        same = ground[:, :, 0] == colour[0]
        same &= ground[:, :, 1] == colour[1]
        same &= ground[:, :, 2] == colour[2]
        mask |= same
    return mask


# How far either side of a gate or a crossing path the fence is looked at, in
# tiles: the fence line and the node or path it meets rarely land on the same
# tile once both are on the grid.
OPENING_REACH = 1
FENCE_JOIN_REACH = 4


def mapped_fence_lines(out_dir, map_name, proj, fitted=()):
    """Project mapped fences and keep their ends attached to fitted apartment walls."""
    path = os.path.join(out_dir, f"{map_name}_fences.geojson")
    feats = (knoxfiles.read(path, "the fences", default={}) or {}).get("features", [])
    lines = [([proj.to_px(lat, lon) for lon, lat in feat["geometry"]["coordinates"]],
              feat.get("properties") or {})
             for feat in feats if feat.get("geometry", {}).get("type") == "LineString"
             and len(feat["geometry"]["coordinates"]) >= 2]
    if not lines or not fitted:
        return lines

    from shapely import STRtree
    from shapely.geometry import Point, Polygon, box

    originals = [Polygon(ring) for _fp, ring in fitted]
    tree = STRtree(originals)

    def attachment(point):
        x, y = point
        original = Point(point)
        candidates = []
        for i in tree.query(box(x - 0.5, y - 0.5, x + 0.5, y + 0.5)):
            if originals[i].distance(original) > 0.5:
                continue
            fp, _ring = fitted[i]
            for gy in range(max(fp.y0, math.ceil(y - FENCE_JOIN_REACH)),
                            min(fp.y0 + fp.height, math.floor(y + FENCE_JOIN_REACH)) + 1):
                for gx in range(max(fp.x0, math.ceil(x - FENCE_JOIN_REACH)),
                                min(fp.x0 + fp.width, math.floor(x + FENCE_JOIN_REACH)) + 1):
                    d = math.hypot(gx - x, gy - y)
                    if d > FENCE_JOIN_REACH:
                        continue
                    if any(0 <= ix < fp.width and 0 <= iy < fp.height and fp.mask[iy, ix]
                           for ix in (gx - fp.x0 - 1, gx - fp.x0)
                           for iy in (gy - fp.y0 - 1, gy - fp.y0)):
                        candidates.append((d, gx, gy))
        if not candidates:
            return []
        _distance, gx, gy = min(candidates)
        return [(gx, gy)] if (gx, gy) != (round(x), round(y)) else []

    return [(attachment(points[0]) + points + attachment(points[-1]), tags)
            for points, tags in lines]


def _openings(out_dir: str, map_name: str, proj):
    """Usable gates, crossing paths and closed gate positions in map tiles."""
    path = os.path.join(out_dir, f"{map_name}_fence_openings.geojson")
    data = knoxfiles.read(path, "the gates and paths through the fences", default={}) or {}
    gates, paths, roads, closed = [], [], [], set()
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        restricted = (props.get("foot", props.get("access")) in ("no", "private")
                      or props.get("locked") == "yes")
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "Point" and len(coords) == 2:
            p = proj.to_px(coords[1], coords[0])
            if restricted:
                closed.update(_nearby([p]))
            else:
                gates.append(p)
        elif geom.get("type") == "LineString" and len(coords) >= 2:
            points = [proj.to_px(lat, lon) for lon, lat in coords]
            if props.get("opening") == "road":
                roads.append((points, props["width_m"]))
            elif not restricted:
                paths.append(points)
    return gates, paths, closed, roads if data.get("road_geometry") else None


def _crossing_points(line, other, include_overlaps: bool = False) -> list:
    """Isolated intersections and, if requested, the centre of any shared run."""
    hits = line.intersection(other)
    points = []
    for hit in getattr(hits, "geoms", [hits]):
        if hit.is_empty:
            continue
        if hit.geom_type == "Point" or include_overlaps:
            spot = hit if hit.geom_type == "Point" else hit.centroid
            points.append((spot.x, spot.y))
    return points


def _nearby(points, reach=OPENING_REACH):
    for px, py in points:
        x, y = round(px), round(py)
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                yield (x + dx, y + dy)


def build_fences(out_dir: str, map_name: str, proj, occupied, areas,
                 bdir: str, extra: list | None = None,
                 keep_clear: set | None = None, *, mapped_lines=None,
                 core: tuple[int, int, int, int] | None = None,
                 allow_mod_tiles: bool = True, road_hierarchy=None) -> tuple[list, int]:
    """Write one fence .tbx per map cell that has fences. Returns placements.

    `keep_clear` is a set of (x, y) tiles - the ground in front of each door - that no fence
    edge may touch: a fence across a doorway is a gap in the fence instead.
    A build quadrant resolves edges in its halo too, then emits only its core."""
    clear = keep_clear or ()
    from .world import Placement

    lines = mapped_lines if mapped_lines is not None else mapped_fence_lines(out_dir, map_name, proj)
    sites = _fenced_sites(areas)
    dependencies = os.path.join(out_dir, FENCE_TILE_DEPENDENCIES)
    if not lines and not extra and not sites:
        if os.path.isfile(dependencies):
            knoxfiles.write(dependencies, {})
        return [], 0

    styles, gate_tiles, mod_id, custom_tiles = _palette(out_dir, allow_mod_tiles)
    map_h, map_w = occupied.shape

    def building_at(x: int, y: int) -> bool:
        return 0 <= x < map_w and 0 <= y < map_h and bool(occupied[y, x])

    # Mappers draw a fence as one line and put the gate in as a separate point,
    # so a schoolyard fence crosses its own driveway and a factory fence the
    # road into the works. Built as drawn, the fence walls the road off. An
    # edge with tarmac on both sides of a surveyed road is left open. Use
    # the road raster to distinguish a road from a paved yard or car park.
    tarmac = _tarmac_mask(os.path.join(out_dir, f"{map_name}.bmp"), map_w, map_h)

    def crossing(ax: int, ay: int, bx: int, by: int) -> bool:
        if tarmac is None:
            return False
        inside = (0 <= ax < map_w and 0 <= ay < map_h and
                  0 <= bx < map_w and 0 <= by < map_h)
        if not inside or not (tarmac[ay, ax] and tarmac[by, bx]):
            return False
        return road_hierarchy is None or (road_hierarchy[ay, ax] >= 2 and road_hierarchy[by, bx] >= 2)

    # (x, y) -> {"W": (style, run), "N": (style, run)}
    edges: dict[tuple[int, int], dict[str, tuple[str, int]]] = {}
    ends: set[tuple[int, int]] = set()
    # Mapped fences, then the ones drawn round back yards (knoxbuild/yards.py),
    # which come as tile points with their style. Each carries whether it is a
    # fence somebody put there - mapped in OpenStreetMap or drawn in the
    # editor - or one made up here, because where the two meet the real one
    # wins.
    todo: list[tuple[list, str, bool]] = []
    for pts, tags in lines:
        area = None
        if areas:
            from shapely.geometry import LineString
            midpoint = LineString(pts).interpolate(0.5, normalized=True)
            area = areas.category_at(midpoint.x, midpoint.y)
        todo.append((pts, style_for(tags, area), True))
    # Sites that are fenced in the world whether or not anyone drew the fence.
    # OpenStreetMap maps an army base as landuse=military far more often than
    # it maps the wire round it, so a base was open ground you could walk
    # across; the outline of the site is the fence. Road crossings are left
    # open by the rule above, which is what makes the gates.
    for shape in sites:
        ring = list(shape.exterior.coords)
        if len(ring) >= 4:
            todo.append(([(float(x), float(y)) for x, y in ring],
                         "tall_chainlink", False))
    mapped_and_site_runs = len(todo)
    yard_gates: dict[tuple[int, int], int] = {}
    # A yard fence is this program's guess at what is round a house. Where
    # somebody has mapped or drawn a fence or a hedge that crosses it, theirs
    # is what is there, and the guess is dropped rather than laid over it.
    drawn = _mapped_lines([pts for pts, _style, _real in todo])
    for item in extra or ():
        pts, style = item[0], item[1]
        if _crosses(pts, drawn):
            continue
        for gx, gy in (item[2] if len(item) > 2 else ()):
            yard_gates[(gx, gy)] = len(todo)
        todo.append((pts, style, False))

    # A gate on the fence, or a footpath through it: the mapper drew the way
    # in, and a fence built from the line alone stood across it. Each opening
    # takes its tiles out of the fence; where the game has a gate for that
    # fence, one of those tiles becomes the gate rather than a hole.
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    gate_points, path_lines, closed_gates, road_lines = _openings(out_dir, map_name, proj)
    paths = None
    if path_lines:
        paths = unary_union([LineString(line) for line in path_lines
                             if len(line) >= 2])
    roads = [LineString(points) for points, _width in road_lines or ()]
    road_tree = STRtree(roads) if roads else None
    scale = getattr(proj, "meters_per_tile", 1)
    for run, (pts, style, real) in enumerate(todo):
        if len(pts) < 2:
            continue
        line = LineString(pts) if paths is not None or road_tree is not None else None
        openings = set(_nearby(_crossing_points(line, paths))) if paths is not None else ()
        road_gaps = set()
        if road_tree is not None:
            for index in road_tree.query(line, predicate="intersects"):
                reach = math.ceil(road_lines[index][1] / (2 * scale)) + 1
                road_gaps.update(_nearby(_crossing_points(line, roads[index]), reach))
        walk = _grid_path(pts)
        for (x1, y1), (x2, y2) in zip(walk, walk[1:]):
            x, y = min(x1, x2), min(y1, y2)
            side, other = ("N", (x, y - 1)) if y1 == y2 else ("W", (x - 1, y))
            at = (x, y)
            if not (0 <= x < map_w and 0 <= y < map_h):
                continue
            if building_at(*at) or building_at(*other):
                continue
            if at not in closed_gates:
                if at in clear or other in clear or at in openings:
                    continue
                if (road_lines is None or at in road_gaps) and crossing(*at, *other):
                    continue
            sides = edges.setdefault(at, {})
            if real or side not in sides:
                sides[side] = (style, run)
        if len(walk) > 1:
            ends.update((walk[0], walk[-1]))

    # Fit a surveyed gate to the nearest surviving edge, once per node. A
    # different fence in the same block keeps its own segments.
    gates: dict[tuple[tuple[int, int], str], str] = {}
    cuts = set()
    for px, py in gate_points:
        candidates = []
        for at in _nearby([(px, py)]):
            if at in closed_gates:
                continue
            x, y = at
            for side, (style, run) in edges.get(at, {}).items():
                if run >= mapped_and_site_runs or (at, side) in gates or (at, side) in cuts:
                    continue
                distance = (px - x - 0.5 * (side == "N"))**2 + (py - y - 0.5 * (side == "W"))**2
                anchor = (px - x)**2 + (py - y)**2
                candidates.append((distance, anchor, at, side, style))
        if candidates:
            _distance, _anchor, at, side, style = min(candidates)
            if style in gate_tiles:
                gates[at, side] = gate_tiles[style][side == "N"]
            else:
                cuts.add((at, side))
    for at, side in cuts:
        del edges[at][side]
        if not edges[at]:
            del edges[at]
    for at, run in yard_gates.items():
        sides = edges.get(at, {})
        if len(sides) == 1:
            side, (style, owner) = next(iter(sides.items()))
            if owner == run and style in gate_tiles and at not in closed_gates:
                gates[at, side] = gate_tiles[style][side == "N"]

    # Tile pieces, by the same rules as WorldEd's fence tool.
    offset_x = getattr(proj, "offset_x", 0)
    offset_y = getattr(proj, "offset_y", 0)
    pieces: dict[tuple[int, int], tuple[str, ...]] = {}
    for at, sides in edges.items():
        x, y = at
        if (len(sides) == 2 and sides["W"][0] == sides["N"][0]
                and (at, "W") not in gates and (at, "N") not in gates):
            pieces[at] = (styles[sides["N"][0]]["nw"],)
            continue
        # A corner with different materials or a gate needs both edges.
        tiles = []
        for side, role in (("W", f"west{1 + (y + offset_y) % 2}"),
                           ("N", f"north{1 + (x + offset_x) % 2}")):
            if side in sides:
                tiles.append(gates.get((at, side), styles[sides[side][0]][role]))
        pieces[at] = tuple(tiles)
    for x, y in ends:
        if (x, y) in pieces or not (0 <= x < map_w and 0 <= y < map_h):
            continue
        if building_at(x, y) or (x, y) in clear:
            continue
        touching = [edges[key][side] for key, side in (((x, y - 1), "W"), ((x - 1, y), "N"))
                    if side in edges.get(key, {})]
        if len(touching) == 1:
            post = styles[touching[0][0]].get("post")
            if post:
                pieces[x, y] = (post,)

    if core is not None:
        left, top, right, bottom = core
        pieces = {at: tiles for at, tiles in pieces.items()
                  if left <= at[0] < right and top <= at[1] < bottom}
    by_cell = defaultdict(dict)
    for (x, y), tiles in pieces.items():
        by_cell[((x + offset_x) // CELL, (y + offset_y) // CELL)][x, y] = tiles

    placements = []
    for (cx, cy), cell_pieces in sorted(by_cell.items()):
        xs = [x for x, _ in cell_pieces]
        ys = [y for _, y in cell_pieces]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
        fname = f"{map_name}_fences_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_fence_tbx(w, h, {(x - x0, y - y0): tiles
                                            for (x, y), tiles in cell_pieces.items()}))
        placements.append(Placement(f"buildings/{fname}", x0, y0, w, h))
    if mod_id or os.path.isfile(dependencies):
        used = sorted(custom_tiles.intersection(tile for tiles in pieces.values() for tile in tiles))
        knoxfiles.write(dependencies, {mod_id: used} if used else {})
    return placements, sum(map(len, pieces.values()))


def render_fence_tbx(width: int, height: int,
                     pieces: dict[tuple[int, int], tuple[str, ...]]) -> str:
    """A building with no rooms whose only contents are fence tiles.

    Each distinct fence tile is its own single-tile furniture piece, defined for
    all four facings so the reader accepts it, and placed facing west.
    """
    from .tbx import _roomless_tbx_header

    tiles = sorted({tile for square in pieces.values() for tile in square})
    index = {t: i for i, t in enumerate(tiles)}
    out = _roomless_tbx_header(width, height)
    for tile in tiles:
        out.append(" <furniture>")
        for orient in ("W", "N", "E", "S"):
            out.append(f'  <entry orient="{orient}">')
            out.append(f'   <tile x="0" y="0" name={quoteattr(tile)}/>')
            out.append("  </entry>")
        out.append(" </furniture>")
    out.append(" <used_tiles>" + " ".join(str(i) for i in range(1, len(C.TILE_ENTRIES) + 1))
               + "</used_tiles>")
    out.append(" <used_furniture>" + " ".join(str(i) for i in range(len(tiles)))
               + "</used_furniture>")
    out.append(" <floor>")
    for (x, y), square in sorted(pieces.items()):
        for tile in square:
            out.append(f'  <object type="furniture" FurnitureTiles="{index[tile]}" '
                       f'orient="W" x="{x}" y="{y}"/>')
    grid = "\n" + "\n".join(",".join("0" for _ in range(width)) + ("," if y < height - 1 else "")
                            for y in range(height)) + "\n"
    out.append("  <rooms>" + grid + "</rooms>")
    out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
