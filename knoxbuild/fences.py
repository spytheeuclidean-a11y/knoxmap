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

import json
import math
import os
from xml.sax.saxutils import quoteattr

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
    "tall_concrete": dict(west1=40, west2=40, north1=41, north2=41, nw=42, post=43),
}


# Gates, for the fences drawn round back yards: (west-edge tile, north-edge tile).
GATES = {
    "short_wooden": ("fixtures_doors_fences_01_004", "fixtures_doors_fences_01_005"),
    "tall_wooden": ("fixtures_doors_fences_01_012", "fixtures_doors_fences_01_013"),
    "white_picket": ("fixtures_doors_fences_01_008", "fixtures_doors_fences_01_009"),
    "short_chainlink": ("fixtures_doors_fences_01_016", "fixtures_doors_fences_01_017"),
}


def _tile(n: int) -> str:
    return f"fencing_01_{n:03d}"


def style_for(tags: dict, area: str | None) -> str:
    """Which fence a line gets: from its own tags first, its surroundings next."""
    barrier = tags.get("barrier")
    if barrier in {"wall", "retaining_wall", "city_wall"}:
        return "tall_concrete"
    kind = (tags.get("fence_type") or tags.get("material") or "").lower()
    if kind in {"chain_link", "chain", "mesh"}:
        return "tall_chainlink" if area in {"industrial", "military"} else "short_chainlink"
    if kind in {"wood", "wooden", "split_rail", "board", "panel"}:
        return "tall_wooden"
    if kind in {"picket", "pales"}:
        return "white_picket"
    if kind in {"metal", "railing", "metal_bars", "bars", "iron", "steel"}:
        return "black_metal"
    if kind in {"barbed_wire", "electric", "wire"}:
        return "cattle"
    if kind in {"concrete", "brick", "stone", "masonry"}:
        return "tall_concrete"
    return {
        "industrial": "tall_chainlink", "military": "tall_chainlink",
        "schoolyard": "short_chainlink", "sports": "short_chainlink",
        "residential": "tall_wooden", "cemetery": "black_metal",
        "worship_grounds": "black_metal", "hospital_grounds": "black_metal",
    }.get(area or "", "short_wooden")


def _grid_path(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """A polyline as a walk along tile corners, one grid step at a time.

    Diagonal runs become staircases along tile edges - a fence can only stand
    on an edge - choosing at each corner the step that keeps closer to the
    real line.
    """
    path: list[tuple[int, int]] = []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        steps = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) * 4)))
        for i in range(steps + 1):
            t = i / steps
            v = (int(round(ax + (bx - ax) * t)), int(round(ay + (by - ay) * t)))
            if not path:
                path.append(v)
                continue
            px, py = path[-1]
            if v == (px, py):
                continue
            if v[0] != px and v[1] != py:
                # Two corners apart diagonally: go through whichever of the two
                # in-between corners sits nearer the true line.
                opt1, opt2 = (v[0], py), (px, v[1])
                mx, my = ax + (bx - ax) * t, ay + (by - ay) * t
                mid = min((opt1, opt2), key=lambda o: math.hypot(o[0] - mx, o[1] - my))
                path.append(mid)
            path.append(v)
    return path


def _tarmac_mask(bmp_path: str, width: int, height: int):
    """True where the ground is a road, service lane or car park."""
    import numpy as np
    from PIL import Image

    from generator import pz_colors as C

    if not os.path.exists(bmp_path):
        return None
    ground = np.asarray(Image.open(bmp_path).convert("RGB"))
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


def build_fences(out_dir: str, map_name: str, proj, occupied, areas,
                 bdir: str, extra: list | None = None) -> tuple[list, int]:
    """Write one fence .tbx per map cell that has fences. Returns placements."""
    from .world import Placement

    path = os.path.join(out_dir, f"{map_name}_fences.geojson")
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = json.load(f).get("features", [])
    if not lines and not extra:
        return [], 0

    map_h, map_w = occupied.shape

    def building_at(x: int, y: int) -> bool:
        return 0 <= x < map_w and 0 <= y < map_h and bool(occupied[y, x])

    # Mappers draw a fence as one line and put the gate in as a separate point,
    # so a schoolyard fence crosses its own driveway and a factory fence the
    # road into the works. Built as drawn, the fence walls the road off. An
    # edge with tarmac on both sides is a road crossing, and is left open; a
    # fence along the side of a car park has tarmac on one side only and stays.
    tarmac = _tarmac_mask(os.path.join(out_dir, f"{map_name}.bmp"), map_w, map_h)

    def crossing(ax: int, ay: int, bx: int, by: int) -> bool:
        if tarmac is None:
            return False
        inside = (0 <= ax < map_w and 0 <= ay < map_h and
                  0 <= bx < map_w and 0 <= by < map_h)
        return inside and bool(tarmac[ay, ax]) and bool(tarmac[by, bx])

    # (x, y) -> {"W": style, "N": style}
    edges: dict[tuple[int, int], dict[str, str]] = {}
    ends: dict[tuple[int, int], str] = {}
    # Mapped fences, then the ones drawn round back yards (knoxbuild/yards.py),
    # which come as tile points with their style.
    todo = []
    for feat in lines:
        coords = feat.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        pts = [proj.to_px(lat, lon) for lon, lat in coords]
        mid = pts[len(pts) // 2]
        todo.append((pts, style_for(feat.get("properties") or {},
                                    areas.category_at(*mid) if areas else None)))
    gates: dict[tuple[int, int], str] = {}
    for item in extra or ():
        pts, style = item[0], item[1]
        todo.append((pts, style))
        for gx, gy in (item[2] if len(item) > 2 else ()):
            gates[(gx, gy)] = style
    for pts, style in todo:
        walk = _grid_path(pts)
        for (x1, y1), (x2, y2) in zip(walk, walk[1:]):
            if y1 == y2:                      # along a north edge
                x = min(x1, x2)
                # A fence never runs through a building: that edge is a wall.
                if building_at(x, y1) or building_at(x, y1 - 1):
                    continue
                if crossing(x, y1, x, y1 - 1):
                    continue
                edges.setdefault((x, y1), {})["N"] = style
            else:                             # along a west edge
                y = min(y1, y2)
                if building_at(x1, y) or building_at(x1 - 1, y):
                    continue
                if crossing(x1, y, x1 - 1, y):
                    continue
                edges.setdefault((x1, y), {})["W"] = style
        if walk:
            ends[walk[0]] = style
            ends[walk[-1]] = style

    # Tile pieces, by the same rules as WorldEd's fence tool.
    pieces: dict[tuple[int, int], str] = {}
    for (x, y), sides in edges.items():
        if not (0 <= x < map_w and 0 <= y < map_h):
            continue
        if "W" in sides and "N" in sides:
            pieces[(x, y)] = _tile(STYLES[sides["N"]]["nw"])
        elif "W" in sides:
            s = STYLES[sides["W"]]
            pieces[(x, y)] = _tile(s["west1"] if y % 2 == 0 else s["west2"])
        else:
            s = STYLES[sides["N"]]
            pieces[(x, y)] = _tile(s["north1"] if x % 2 == 0 else s["north2"])
    for (x, y), style in ends.items():
        if (x, y) in pieces or not (0 <= x < map_w and 0 <= y < map_h):
            continue
        if building_at(x, y):
            continue
        touching = sum(1 for key, side in (((x, y), "W"), ((x, y), "N"),
                                           ((x, y - 1), "W"), ((x - 1, y), "N"))
                       if side in edges.get(key, {}))
        if touching == 1:
            pieces[(x, y)] = _tile(STYLES[style]["post"])

    # A gate replaces the fence piece on its square, facing the same way.
    for (x, y), style in gates.items():
        sides = edges.get((x, y), {})
        if style in GATES and len(sides) == 1:
            pieces[(x, y)] = GATES[style][0 if "W" in sides else 1]

    by_cell: dict[tuple[int, int], dict[tuple[int, int], str]] = {}
    for (x, y), tile in pieces.items():
        by_cell.setdefault((x // CELL, y // CELL), {})[(x, y)] = tile

    placements = []
    for (cx, cy), cell_pieces in sorted(by_cell.items()):
        xs = [x for x, _ in cell_pieces]
        ys = [y for _, y in cell_pieces]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
        fname = f"{map_name}_fences_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_fence_tbx(w, h, {(x - x0, y - y0): t
                                            for (x, y), t in cell_pieces.items()}))
        placements.append(Placement(f"buildings/{fname}", x0, y0, w, h))
    return placements, len(pieces)


def render_fence_tbx(width: int, height: int,
                     pieces: dict[tuple[int, int], str]) -> str:
    """A building with no rooms whose only contents are fence tiles.

    Each distinct fence tile is its own single-tile furniture piece, defined for
    all four facings so the reader accepts it, and placed facing west.
    """
    tiles = sorted(set(pieces.values()))
    index = {t: i for i, t in enumerate(tiles)}
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    attrs = [("version", 4), ("width", width), ("height", height),
             ("ExteriorWall", C.EXTERIOR_WALL), ("ExteriorWallTrim", 0),
             ("Door", C.DOOR), ("DoorFrame", C.DOOR_FRAME), ("Window", C.WINDOW),
             ("Curtains", C.CURTAINS), ("Shutters", 0), ("Stairs", C.STAIRS),
             ("RoofCap", C.ROOF_CAP), ("RoofSlope", C.ROOF_SLOPE),
             ("RoofTop", C.ROOF_TOP), ("GrimeWall", 0)]
    out.append("<building" + "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs) + ">")
    for entry in C.TILE_ENTRIES:
        out.append(f' <tile_entry category={quoteattr(entry["category"])}>')
        for enum_name, tile in entry["tiles"].items():
            out.append(f'  <tile enum={quoteattr(enum_name)} tile={quoteattr(tile)}/>')
        out.append(" </tile_entry>")
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
    for (x, y), tile in sorted(pieces.items()):
        out.append(f'  <object type="furniture" FurnitureTiles="{index[tile]}" '
                   f'orient="W" x="{x}" y="{y}"/>')
    grid = "\n" + "\n".join(",".join("0" for _ in range(width)) + ("," if y < height - 1 else "")
                            for y in range(height)) + "\n"
    out.append("  <rooms>" + grid + "</rooms>")
    out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
