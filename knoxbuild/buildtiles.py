"""Tiles for a building, from its .tbx (BuildingEd's building file).

What each part of a building becomes was worked out from WorldEd's own output for
small hand-made buildings (see the notes at each rule), then checked against real buildings.

A .tbx holds:
  tile_entry (many)   a numbered list (from 1) of tile sets; each maps names like West,
                      North, NorthWest, SouthEast to a tile; category says what it is for
  room (many)         numbered from 1: which tile entry is its floor and its interior walls
  floor (one a level) a grid of room numbers (0 for outside) and the objects on the level
The building itself names its exterior wall, trim and grime entries.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .buildroofs import upper_layers


@dataclass
class Floor:
    rooms: list[list[int]]                  # [y][x]; 0 = outside
    objects: list[dict] = field(default_factory=list)
    tile_layers: list[tuple[str, list[list[str]]]] = field(default_factory=list)   # (layer, [y][x] tile or "")


@dataclass
class Building:
    width: int
    height: int
    attrs: dict
    entries: list[dict]                     # 1-based: entries[n - 1], {enum: tile name}
    rooms: list[dict]                       # 1-based: rooms[n - 1]
    floors: list[Floor]
    # 0-based: furniture[n], {"layer": name or "", "orients": {orient: [(dx, dy, tile name)]}}
    furniture: list[dict] = field(default_factory=list)


def tile_name(name: str) -> str:
    """BuildingEd writes numbers padded to three digits, the lot files do not:
    walls_exterior_house_02_064 is walls_exterior_house_02_64 there."""
    m = re.match(r"^(.*_)(\d+)$", name)
    return f"{m.group(1)}{int(m.group(2))}" if m else name


def _tile_grid(text: str, user_tiles: list[str], w: int, h: int) -> list[list[str]]:
    """A floor's painted tile layer: numbers into <user_tiles>, 1-based, 0 = nothing."""
    values = [int(v) for v in re.split(r"[,\s]+", (text or "").strip()) if v]
    if len(values) != (w + 1) * (h + 1):        # a layer is one square wider and taller
        raise ValueError(f"a tile layer has {len(values)} values, expected {(w + 1) * (h + 1)}")
    names = [user_tiles[v - 1] if 0 < v <= len(user_tiles) else "" for v in values]
    return [names[y * (w + 1):(y + 1) * (w + 1)] for y in range(h + 1)]   # the extra column and row hold wall tiles


def parse_tbx(text: str) -> Building:
    root = ET.fromstring(text)
    entries = [{t.get("enum"): tile_name(t.get("tile")) for t in e} for e in root if e.tag == "tile_entry"]
    rooms = [dict(r.attrib) for r in root if r.tag == "room"]
    user_tiles = [tile_name(t.get("tile")) for u in root if u.tag == "user_tiles" for t in u]
    w, h = int(root.get("width")), int(root.get("height"))
    floors = []
    for f in root:
        if f.tag != "floor":
            continue
        grid_el = f.find("rooms")
        values = [int(v) for v in re.split(r"[,\s]+", (grid_el.text or "").strip()) if v] if grid_el is not None else []
        if len(values) != w * h:
            raise ValueError(f"a floor has {len(values)} room numbers, expected {w * h}")
        grid = [values[y * w:(y + 1) * w] for y in range(h)]
        floors.append(Floor(grid, [dict(o.attrib) for o in f if o.tag == "object"], [
            (t.get("layer", ""), _tile_grid(t.text, user_tiles, w, h)) for t in f if t.tag == "tiles"]))
    furniture = [{"layer": f.get("layer", ""),
                  "orients": {e.get("orient"): [(int(t.get("x")), int(t.get("y")), tile_name(t.get("name")))
                                                for t in e if t.tag == "tile"]
                              for e in f if e.tag == "entry"}}
                 for f in root if f.tag == "furniture"]
    return Building(w, h, dict(root.attrib), entries, rooms, floors, furniture)


_WINDOW_FAMILIES = ("white", "metal", "wood", "church")
_SPECIAL_WINDOWS = {40: 17, 42: 17, 48: 17, 50: 17, 41: 18, 43: 18, 49: 18, 51: 18}


def _window_variant(window_tile: str) -> int:
    """Which numbered Window variant of a wall holds this window: the wall art has a window
    cut for each sprite pair, numbered from 1 (white_16 and white_17 are variant 9, 10 and 11
    are 6, 24 and 25 are 13). The legacy 01 family uses calibrated variants 17/18; unknown sprites use the plain window wall (0)."""
    legacy = re.match(r"^fixtures_windows_01_(\d+)$", window_tile)
    if legacy:
        return _SPECIAL_WINDOWS.get(int(legacy[1]), 0)
    m = re.match(r"^fixtures_windows_(?:%s)_(\d+)$" % "|".join(_WINDOW_FAMILIES), window_tile)
    return int(m.group(1)) // 2 + 1 if m else 0


def _stair_squares(o: dict) -> list[tuple[int, int]]:
    """The three squares a flight of stairs stands on, from the lowest step's end: a
    west-facing flight starts one square east of its own and runs east, a north-facing one
    starts one square south and runs south."""
    x, y = int(o["x"]), int(o["y"])
    if o.get("dir") == "N":
        return [(x, y + 1 + i) for i in range(3)]
    return [(x + 1 + i, y) for i in range(3)]


def _entry(b: Building, number) -> dict:
    n = int(number)
    return b.entries[n - 1] if 1 <= n <= len(b.entries) else {}


def level_layers(b: Building, z: int) -> dict[tuple[int, int], list[tuple[str, str]]]:
    """{(x, y): [(layer, tile)]}, bottom first, over the building and the ring of
    squares outside its south and east sides, where its exterior walls stand.

    Rules (each seen in WorldEd's output):
    - A square with a room has that room's floor tile.
    - Walls stand on the north and west edge of a square, and exist where the room
      number on the other side of the edge differs. A square with a room uses that
      room's interior wall tile (and its trim, if the room has one), an empty square the building's exterior wall tile, with
      its trim and grime tiles on top (on the ground level only).
    - A square with both a north and a west wall has the NorthWest tile instead of the two.
    - An exterior post (SouthEast) stands on an empty square with no wall of its own
      where a wall ends on the square to its north and another on the square to its west.
    - A door on an edge makes the wall its Door variant and adds the door frame and door.
    - A window makes the wall the Window variant cut for its sprite (see _window_variant; an
      exterior wall has no trim or grime then) and adds the window. Curtains stand on the inside square; shutters
      only on exterior walls, two on the window's square and one on each side of it.
    """
    floor = b.floors[z]
    w, h = b.width, b.height

    def room(x: int, y: int) -> int:
        return floor.rooms[y][x] if 0 <= x < w and 0 <= y < h else 0

    ext = _entry(b, b.attrs.get("ExteriorWall", 0))
    trim = _entry(b, b.attrs.get("ExteriorWallTrim", 0))
    grime = _entry(b, b.attrs.get("GrimeWall", 0))
    ground = z == 0

    custom_walls = {}
    custom_ends = {}
    for o in floor.objects:
        if o.get("type") == "wall":
            horizontal = o.get("dir", "W") == "W"
            for i in range(int(o.get("length", 1))):
                x, y = int(o["x"]) + (i if horizontal else 0), int(o["y"]) + (0 if horizontal else i)
                custom_walls[(x, y, "North" if horizontal else "West")] = o
            length = int(o.get("length", 1))
            custom_ends[(int(o["x"]) + (length if horizontal else 0),
                         int(o["y"]) + (0 if horizontal else length))] = o

    def west(x, y):
        return (x, y, "West") in custom_walls or room(x - 1, y) != room(x, y)

    def north(x, y):
        return (x, y, "North") in custom_walls or room(x, y - 1) != room(x, y)

    floors: dict[tuple[int, int], list[str]] = {}
    walls: dict[tuple[int, int], list[str]] = {}
    extra: dict[tuple[int, int], list[str]] = {}
    kind_at: dict[tuple[int, int], str] = {}

    def wall_tiles(x: int, y: int, kind: str, fallback: str = "", end=False) -> list[str]:
        r = room(x, y)
        direction = "North" if kind.startswith("North") else "West"
        custom = custom_walls.get((x, y, direction))
        if kind == "SouthEast":
            custom = custom_ends.get((x, y)) if end else None
        if custom:
            e = _entry(b, custom.get("InteriorTile" if r else "Tile", 0))
            t = _entry(b, custom.get("InteriorTrim" if r else "ExteriorTrim", 0))
            return [e.get(kind) or e.get(fallback, ""), t.get(kind if e.get(kind) else fallback, "")] + ([grime.get(kind, "")] if not r and ground else [])
        if r > 0:
            room_def = b.rooms[r - 1]
            e = _entry(b, room_def["InteriorWall"])
            tiles = [e.get(kind) or e.get(fallback, "")]
            if int(room_def.get("InteriorWallTrim", 0)):
                tiles.append(_entry(b, room_def["InteriorWallTrim"]).get(kind if e.get(kind) else fallback, ""))
            return tiles
        return [ext.get(kind, "")] + ([trim.get(kind, ""), grime.get(kind, "")] if ground else [])

    # Stairs: three stair tiles on this level, and a hole (no floor tile) over them on the
    # level above. A west-facing flight runs east from its square, a north-facing one south.
    holes: set[tuple[int, int]] = set()
    if z >= 1:
        for o in b.floors[z - 1].objects:
            if o.get("type") == "stairs":
                holes.update(_stair_squares(o))

    wall_furniture: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for o in floor.objects:
        if o.get("type") != "furniture":
            continue
        idx = int(o.get("FurnitureTiles", -1))
        if 0 <= idx < len(b.furniture) and b.furniture[idx]["layer"] == "Walls":
            for dx, dy, tile in b.furniture[idx]["orients"].get(o.get("orient", "N"), []):
                pos = (int(o["x"]) + dx, int(o["y"]) + dy)
                wall_furniture.setdefault(pos, []).append((o.get("orient", "N"), tile))

    for y in range(0, h + 1):
        for x in range(0, w + 1):
            r = room(x, y)
            if r > 0 and (x, y) not in holes:
                floors[(x, y)] = [_entry(b, b.rooms[r - 1]["Floor"]).get("Floor", "")]
            wl, nl = west(x, y), north(x, y)
            for orient, _ in wall_furniture.get((x, y), []):
                if orient == "W":
                    wl = False
                elif orient == "N":
                    nl = False
            kind = "NorthWest" if wl and nl else ("West" if wl else ("North" if nl else ""))
            if kind:
                kind_at[(x, y)] = kind
                if kind == "NorthWest" and any((x, y, d) in custom_walls for d in ("North", "West")):
                    cd = "North" if (x, y, "North") in custom_walls else "West"
                    custom = wall_tiles(x, y, cd)
                    other = wall_tiles(x, y, "West" if cd == "North" else "North")
                    walls[(x, y)] = custom[:1] + other + custom[1:]
                else:
                    walls[(x, y)] = wall_tiles(x, y, kind)
            elif (x, y) not in wall_furniture and west(x, y - 1) and north(x - 1, y):
                walls[(x, y)] = wall_tiles(x, y, "SouthEast")
            elif (x, y) in custom_ends:
                walls[(x, y)] = wall_tiles(x, y, "SouthEast", end=True)

    for pos, items in wall_furniture.items():
        walls[pos] = walls.get(pos, []) + [tile for _, tile in items]

    def add(x, y, tile):
        extra.setdefault((x, y), []).append(tile)

    curtains: dict[tuple[int, int], list[str]] = {}
    curtains_before: dict[tuple[int, int], list[str]] = {}
    stair_tiles: dict[tuple[int, int], list[str]] = {}

    def add_curtain(x, y, tile, before=False):
        target = curtains_before if before else curtains
        target.setdefault((x, y), []).append(tile)

    for o in floor.objects:
        if o.get("type") == "stairs":
            steps = _entry(b, o.get("Tile", b.attrs.get("Stairs", 0)))
            name = "North" if o.get("dir") == "N" else "West"
            for i, pos in enumerate(_stair_squares(o)):
                stair_tiles.setdefault(pos, []).append(steps.get(f"{name}{3 - i}", ""))

    openings = {(o["type"], o["x"], o["y"], o.get("dir", "N")): o
                for o in floor.objects if o.get("type") in ("door", "window")}
    for o in openings.values():
        kind = o["type"]
        x, y, d = int(o["x"]), int(o["y"]), o.get("dir", "N")
        dname = "North" if d == "N" else "West"
        if (x, y) not in kind_at and kind_at.get((x, y)) is None:
            continue                                   # nothing to put it in
        r = room(x, y)
        def preserve_corner(tiles):
            if kind_at[(x, y)] != "NorthWest":
                return tiles
            other = wall_tiles(x, y, "West" if d == "N" else "North")
            if r == 0 and len(tiles) == 3 and len(other) == 3:
                return other[:2] + tiles + other[2:]
            return other + tiles

        if kind == "door":
            walls[(x, y)] = preserve_corner(wall_tiles(x, y, dname + "Door"))
            add(x, y, _entry(b, o.get("FrameTile", b.attrs.get("DoorFrame", 0))).get(dname, ""))
            add(x, y, _entry(b, o.get("Tile", b.attrs.get("Door", 0))).get(dname, ""))
            continue
        win = _entry(b, o.get("Tile", b.attrs.get("Window", 0))).get(dname, "")
        v = _window_variant(win)
        variant = f"{dname}Window{v}" if v else dname + "Window"
        if r > 0:
            walls[(x, y)] = preserve_corner(wall_tiles(x, y, variant, fallback=dname + "Window"))
        else:
            kind = variant if ext.get(variant) else dname + "Window"
            walls[(x, y)] = preserve_corner([ext.get(kind, "")] + ([trim.get(kind, ""), grime.get(kind, "")] if ground else []))
        if r == 0:
            sh = _entry(b, o.get("ShuttersTile", 0))
            if sh:
                names = (("NorthLeft", "NorthRight") if d == "N" else ("WestAbove", "WestBelow"))
                add(x, y, sh.get(names[0], ""))
                add(x, y, sh.get(names[1], ""))
        add(x, y, _entry(b, o.get("Tile", b.attrs.get("Window", 0))).get(dname, ""))
        cur = _entry(b, o.get("CurtainsTile", 0))
        if cur:
            if r > 0:
                add_curtain(x, y, cur.get(dname, ""), before=True)
            else:                                       # the inside square is the one before
                ix, iy = (x, y - 1) if d == "N" else (x - 1, y)
                add_curtain(ix, iy, cur.get("South" if d == "N" else "East", ""))
        if r == 0 and _entry(b, o.get("ShuttersTile", 0)):
            sh = _entry(b, o.get("ShuttersTile", 0))
            if d == "N":
                if x > 0 and room(x - 1, y) == 0:
                    add(x - 1, y, sh.get("NorthLeft", ""))
                if x < w and room(x + 1, y) == 0:
                    add(x + 1, y, sh.get("NorthRight", ""))
            else:
                if y > 0 and room(x, y - 1) == 0:
                    add(x, y - 1, sh.get("WestAbove", ""))
                if y < h and room(x, y + 1) == 0:
                    add(x, y + 1, sh.get("WestBelow", ""))

    # Furniture goes onto the square in the order of BuildingEd's layers: floor furniture
    # under the walls; wall furniture facing north or west before ordinary furniture, facing
    # east or south after it; roof furniture last. Within a layer, in file order.
    furn_floor: dict[tuple[int, int], list[str]] = {}
    furn: dict[tuple[int, int], list[tuple[float, str]]] = {}
    for o in floor.objects:
        if o.get("type") != "furniture":
            continue
        idx = int(o.get("FurnitureTiles", -1))
        if not 0 <= idx < len(b.furniture):
            continue
        d = b.furniture[idx]
        if d["layer"] == "Walls":
            continue
        orient = o.get("orient", "N")
        rank = {"FloorFurniture": -1, "Roof": 3}.get(d["layer"], 0)
        if d["layer"] == "WallFurniture":
            rank = 0 if orient in ("N", "W") else 2
        elif rank == 0:
            rank = 1
        for k, (dx, dy, name) in enumerate(d["orients"].get(orient, [])):
            pos = (int(o["x"]) + dx, int(o["y"]) + dy)
            # Further tiles follow primary furniture tiles, before east/south curtains.
            r = 1.5 if rank == 1 and k > 0 else rank
            if r < 0:
                furn_floor.setdefault(pos, []).append(name)
            else:
                furn.setdefault(pos, []).append((r, name))
    furn_before = {pos: [n for r, n in items if r == 0] for pos, items in furn.items()}     # wall, north/west
    furn_mid = {pos: [n for r, n in sorted((i for i in items if 1 <= i[0] < 2), key=lambda i: i[0])]
                for pos, items in furn.items()}        # ordinary, then further tiles, before east/south curtains
    furn_after = {pos: [n for r, n in items if r == 2]
                  for pos, items in furn.items()}       # wall furniture east/south
    furn_roof = {pos: [n for r, n in items if r == 3] for pos, items in furn.items()}

    upper_floor, upper = upper_layers(lambda n: _entry(b, n), b.attrs, w, h, b.rooms, b.floors, z)
    trim_names = set(trim.values())
    for rd in b.rooms:
        trim_names.update(_entry(b, rd.get("InteriorWallTrim", 0)).values())
    for o in custom_walls.values():
        for key in ("InteriorTrim", "ExteriorTrim"):
            trim_names.update(_entry(b, o.get(key, 0)).values())
    grime_names = set(grime.values())
    north_trim = {tile for e in b.entries for enum, tile in e.items() if tile in trim_names
                  and (enum == "SouthEast" or (enum.startswith("North") and enum != "NorthWest"))}
    north_grime = {tile for enum, tile in grime.items() if enum.startswith("North") and enum != "NorthWest"}
    out: dict[tuple[int, int], list[tuple[str, str]]] = {}
    # bottom to top: floor, rugs, walls, wall furniture (north/west), door frames, doors,
    # windows, ordinary furniture, curtains, wall furniture (east/south), roof furniture
    painted: dict[tuple[int, int], list[str]] = {}
    for _layer, grid in floor.tile_layers:        # tiles painted on the floor, with the wall furniture
        for y, row in enumerate(grid):
            for x, tile in enumerate(row):
                if tile:
                    painted.setdefault((x, y), []).append(tile)
    groups = [("floor", floors), ("floor", upper_floor), ("floor_furniture", furn_floor),
              ("walls", walls), ("wall_furniture_nw", furn_before), ("painted", painted), ("openings", extra),
              ("curtains_nw", curtains_before), ("stairs", stair_tiles), ("furniture", furn_mid),
              ("curtains_se", curtains), ("wall_furniture_se", furn_after), ("roof", upper),
              ("roof_furniture", furn_roof)]
    for pos in set().union(*(g for _, g in groups)):
        stack = []
        for layer, group in groups:
            for tile in group.get(pos, []):
                if not tile:
                    continue
                channel = layer
                if layer == "walls":
                    if tile in trim_names:
                        channel = "wall_trim_north" if tile in north_trim else "wall_trim_west"
                    elif tile in grime_names:
                        channel = "wall_grime_north" if tile in north_grime else "wall_grime_west"
                stack.append((channel, tile))
        if stack:
            out[pos] = stack
    return out


def level_tiles(b: Building, z: int) -> dict[tuple[int, int], list[str]]:
    """Building tiles in drawing order; retains the original flat-stack interface."""
    return {pos: [tile for _, tile in items] for pos, items in level_layers(b, z).items()}


def compose_lots(lots) -> dict[tuple[int, int, int], list[str]]:
    """Compose (building, x, y, base level) placements in project order.

    Rooms replace earlier lot squares. Outside rooms, only populated layers replace
    matching earlier layers; empty squares preserve the underlying lot.
    """
    world = {}
    for b, tx, ty, base in lots:
        for z, floor in enumerate(b.floors):
            layers = level_layers(b, z)
            rooms = {(x, y) for y, row in enumerate(floor.rooms) for x, r in enumerate(row) if r > 0}
            for x, y in rooms | layers.keys():
                pos = (tx + x, ty + y, base + z)
                new = layers.get((x, y), [])
                if (x, y) in rooms:
                    world[pos] = new
                else:
                    channels = {layer for layer, _ in new}
                    old = world.get(pos, [])
                    if "floor" in channels:     # a floor tile (a flat roof is one) takes the square
                        old = []
                    world[pos] = [(layer, tile) for layer, tile in old if layer not in channels] + new
    return {pos: [tile for _, tile in items] for pos, items in world.items() if items}
