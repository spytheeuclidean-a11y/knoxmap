"""Serialise a Plan to BuildingEd's .tbx format.

Schema taken from BuildingWriter in timbaker/buildinged. Two index conventions
differ and are easy to get backwards:

    tile entries   1-based, and 0 means "none"   (entryIndex)
    furniture      0-based, no null form         (furnitureIndex)

Element order inside <building> follows the writer: tile entries, furniture,
used_tiles, used_furniture, the <room> list, then <floor>.
"""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from . import catalog as C
from .layout import ROOM_STYLE, Building, Plan, roof_rects

# Version 4 is the first that carries a per-room Ceiling tile. Writing 3 still
# loads - the reader accepts 1..7 - but then it silently back-fills ceilings
# itself, so we may as well state them.
VERSION = 4


def _attrs(pairs: list[tuple[str, object]]) -> str:
    # Nearly every value is a coordinate or an index. Quoting those through
    # quoteattr, nine million calls for a town, was 40% of the time spent
    # writing buildings; numbers never need escaping.
    return "".join(f' {k}="{v}"' if type(v) is int else f" {k}={quoteattr(str(v))}"
                   for k, v in pairs)


# A pitched roof needs room for two slopes; a narrower strip of a house (a
# porch, one step of a turned footprint) keeps a flat roof.
PEAK_MIN_TILES = 4
# The 30-degree roofs the game's own houses wear, which BuildingEd sizes to an
# odd number of tiles across, 3 to 11; a house up to two tiles wider takes an
# 11 and a flat strip. Wider than that, the steep 45-degree gable with a flat
# top in the middle is all the editor offers.
PEAK30_MAX_ACROSS = 11
HIP_MAX_ACROSS = 7
_PEAK_DEPTHS = {1: "Point5", 2: "One", 3: "OnePoint5", 4: "Two", 5: "TwoPoint5"}
_NO_CAPS = {"cappedW": False, "cappedN": False, "cappedE": False, "cappedS": False}


def _peak_depth(across: int) -> str:
    """BuildingEd's depth for a 45-degree peaked roof this many tiles across."""
    return _PEAK_DEPTHS.get(across, "Three")


def _roof_pieces(rects, peaked: bool, roof30: bool = True):
    """(RoofType, Depth, caps, (x, y, w, h)) for each roof over a footprint.

    Flat roofs are never capped: at depth three a cap is a storey-high wall of
    roof tiles laid over the top storey's own walls. A pitched roof is capped
    at its gable ends where they are the outside of the house, and left open
    where it runs into the next roof.

    30-degree roofs need an odd width across their slopes. On an even one the
    roof covers one tile less and a flat strip takes the last row, on the side
    away from the camera (north or west) where it shows least. A house that is
    a single rectangle gets a hip roof about half the time, as Knox County's
    do; an L-shape keeps gables, whose ends meet cleanly.
    """
    out = []
    single = len(rects) == 1
    for rx, ry, rw, rh, caps in rects:
        across = min(rw, rh)
        if not peaked or across < PEAK_MIN_TILES:
            out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw, rh)))
            continue
        along_x = rw >= rh
        if not roof30 or across > PEAK30_MAX_ACROSS + 2:
            cap = dict(_NO_CAPS)
            if along_x:
                cap["cappedW"], cap["cappedE"] = caps["cappedW"], caps["cappedE"]
                out.append(("PeakWE", _peak_depth(rh), cap, (rx, ry, rw, rh)))
            else:
                cap["cappedN"], cap["cappedS"] = caps["cappedN"], caps["cappedS"]
                out.append(("PeakNS", _peak_depth(rw), cap, (rx, ry, rw, rh)))
            continue
        odd = across if across % 2 else across - 1
        # Hips only on small houses: across a wide one the four slopes meet
        # in a tall point that looks like a hat.
        hip = single and odd <= HIP_MAX_ACROSS and (rx * 31 + ry * 17 + rw * 7 + rh) % 2 == 0
        cap = dict(_NO_CAPS)
        if along_x:
            box = (rx, ry + (rh - odd), rw, odd)
            if rh != odd:
                out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw, rh - odd)))
            if not hip:
                cap["cappedW"], cap["cappedE"] = caps["cappedW"], caps["cappedE"]
            out.append(("Peak30Quad" if hip else "Peak30WE", "Zero", cap, box))
        else:
            box = (rx + (rw - odd), ry, odd, rh)
            if rw != odd:
                out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw - odd, rh)))
            if not hip:
                cap["cappedN"], cap["cappedS"] = caps["cappedN"], caps["cappedS"]
            out.append(("Peak30Quad" if hip else "Peak30NS", "Zero", cap, box))
    return out


# Flat roofs carry plant: bare tar from edge to edge read as unfinished. One
# air-conditioning unit per ROOF_AC_EVERY tiles of roof, a vent per
# ROOF_VENT_EVERY, and a hatch, kept off the edges and off each other.
ROOF_MIN_TILES = 60
ROOF_AC_EVERY = 90
ROOF_VENT_EVERY = 60


def _rooftop(grid: list[list[int]], width: int, height: int) -> list[tuple[str, int, int, str]]:
    import random

    tiles = [(x, y) for y in range(1, height - 1) for x in range(1, width - 1)
             if all(grid[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1))]
    area = sum(1 for row in grid for v in row if v)
    if area < ROOF_MIN_TILES or not tiles:
        return []
    rng = random.Random(width * 7919 + height * 104729 + area)
    wanted = (["roof_hatch"] + ["roof_ac"] * max(1, area // ROOF_AC_EVERY)
              + ["roof_vent"] * (area // ROOF_VENT_EVERY))
    taken: set[tuple[int, int]] = set()
    out = []
    rng.shuffle(tiles)
    for role in wanted:
        for x, y in tiles:
            if any((x + dx, y + dy) in taken for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                continue
            taken.add((x, y))
            out.append((role, x, y, rng.choice(("W", "N"))))
            break
    return out


def _add(entries: list[dict], entry: dict | None) -> int:
    """The 1-based index of `entry` in the tile-entry table, appending it if it
    is not there yet; 0, BuildingEd's "none", for no entry."""
    if not entry:
        return 0
    if entry in entries:
        return entries.index(entry) + 1
    entries.append(entry)
    return len(entries)


def render_tbx(plan: Plan | Building, name: str,
               style: dict | None = None) -> str:
    """Return the complete .tbx document for a plan or a stack of them.

    `style` supplies this building's own exterior and interior wall materials,
    and optionally a floor that overrides the usual per-room palette. Each .tbx
    carries its own tile-entry table, so styles cost nothing globally: the
    style's entries are simply appended after the shared ones and referenced by
    their new indices.
    """
    building = plan if isinstance(plan, Building) else Building(
        width=plan.width, height=plan.height, storeys=[plan])
    storeys = building.storeys

    entries = list(C.TILE_ENTRIES)
    exterior_idx = C.EXTERIOR_WALL
    interior_idx = C.INTERIOR_WALL
    floor_override = None
    window_idx = C.WINDOW
    roof_cap_idx = C.ROOF_CAP
    curtains_idx = C.CURTAINS
    front_idx = front_curtains = None
    slope_idx, top_idx, peaked = C.ROOF_SLOPE, C.ROOF_TOP, False
    trim_idx = shutters_idx = grime_idx = 0
    roof30 = False

    if style:
        entries.append(style["exterior"])
        exterior_idx = len(entries)
        entries.append(style["interior"])
        interior_idx = len(entries)
        if style.get("floor"):
            entries.append(style["floor"])
            floor_override = len(entries)
        if style.get("window"):
            entries.append(style["window"])
            window_idx = len(entries)
        curtains_idx = _add(entries, style.get("curtains")) if "curtains" in style else C.CURTAINS
        # Taller buildings of a kind take bigger windows: the last row whose
        # storey count this building reaches.
        for levels, entry, curtains in style.get("windows_by_levels") or ():
            if len(storeys) >= levels and levels > 1:
                window_idx = _add(entries, entry)
                curtains_idx = _add(entries, curtains)
        trim_idx = _add(entries, style.get("trim"))
        shutters_idx = _add(entries, style.get("shutters"))
        grime_idx = _add(entries, style.get("grime"))
        if style.get("roof"):
            roof = style["roof"]
            if roof.get("slopes"):
                slope_idx = _add(entries, roof["slopes"])
            top_idx = _add(entries, roof["tops"])
            peaked = bool(roof.get("peaked"))
            # 30-degree roofs only where the gable ends have 30-degree tiles.
            roof30 = "CapPeak30S1" in ((roof.get("caps") or {}).get("tiles") or {})                 and "Slope30S1" in ((roof.get("slopes") or {}).get("tiles") or {})
        if style.get("shop_front"):
            entry, curtains = style["shop_front"]
            front_idx = _add(entries, entry)
            front_curtains = _add(entries, curtains)
    # A depth-three flat roof walls in its storey with the cap entry's
    # CapGap tiles, which BuildingTemplates.txt sets to stucco - every top
    # floor came out stucco whatever the building was made of. Give each
    # building a cap entry whose gaps are its own exterior wall.
    ext_tiles = entries[exterior_idx - 1]["tiles"]
    if ext_tiles.get("West") and ext_tiles.get("North"):
        base = ((style or {}).get("roof") or {}).get("caps") or entries[C.ROOF_CAP - 1]
        cap = dict(base["tiles"])
        cap["CapGapE3"], cap["CapGapS3"] = ext_tiles["West"], ext_tiles["North"]
        entries.append({"category": "roof_caps", "tiles": cap})
        roof_cap_idx = len(entries)

    rooftop = [] if peaked else _rooftop(storeys[-1].grid, building.width, building.height)
    # Which furniture roles this building actually uses, in first-use order.
    roles: list[str] = []
    for storey in storeys:
        for role, _x, _y, _o in storey.furniture:
            if role not in roles:
                roles.append(role)
    for role, _x, _y, _o in rooftop:
        if role not in roles:
            roles.append(role)

    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']

    building_attrs = [
        ("version", VERSION),
        ("width", building.width),
        ("height", building.height),
        ("ExteriorWall", exterior_idx),
        ("ExteriorWallTrim", trim_idx),
        ("Door", C.DOOR),
        ("DoorFrame", C.DOOR_FRAME),
        ("Window", window_idx),
        ("Curtains", curtains_idx),
        ("Shutters", shutters_idx),
        ("Stairs", C.STAIRS),
        ("RoofCap", roof_cap_idx),
        ("RoofSlope", slope_idx),
        ("RoofTop", top_idx),
        ("GrimeWall", grime_idx),
    ]
    out.append(f"<building{_attrs(building_attrs)}>")

    for entry in entries:
        out.append(f' <tile_entry category={quoteattr(entry["category"])}>')
        for enum_name, tile in entry["tiles"].items():
            out.append(f'  <tile enum={quoteattr(enum_name)} tile={quoteattr(tile)}/>')
        out.append(" </tile_entry>")

    for role in roles:
        # BuildingWriter only writes a layer when it is not the default. Leaving
        # it off a wall piece drops it onto the floor layer, which is how light
        # switches, paintings and mirrors ended up standing mid-room.
        layer = C.FURNITURE_LAYERS.get(role, "Furniture")
        out.append(" <furniture>" if layer == "Furniture"
                   else f" <furniture layer={quoteattr(layer)}>")
        # All four facings, in the order BuildingWriter emits them. Writing only
        # W and N leaves the E/S slots empty, so any object facing that way
        # renders as nothing at all.
        for orient in ("W", "N", "E", "S"):
            tiles = C.FURNITURE[role].get(orient)
            if not tiles:
                continue
            out.append(f'  <entry orient="{orient}">')
            for key, tile in tiles.items():
                dx, dy = key.split(",")
                out.append(f'   <tile x="{dx}" y="{dy}" name={quoteattr(tile)}/>')
            out.append("  </entry>")
        out.append(" </furniture>")

    used = " ".join(str(i) for i in range(1, len(entries) + 1))
    out.append(f" <used_tiles>{used}</used_tiles>")
    used_f = " ".join(str(i) for i in range(len(roles)))
    out.append(f" <used_furniture>{used_f}</used_furniture>")

    for room in building.rooms:
        floor_idx, _label, _ = ROOM_STYLE[room.kind]
        # The shipped templates set Name identical to InternalName; the room
        # name is what reaches the game's room definitions, so don't get
        # creative with it.
        room_attrs = [
            ("Name", room.kind),
            ("InternalName", room.kind),
            ("Color", C.ROOM_COLORS[room.kind]),
            ("InteriorWall", interior_idx),
            ("InteriorWallTrim", C.INTERIOR_WALL_TRIM),
            ("Floor", floor_override or floor_idx),
            ("GrimeFloor", 0),
            ("GrimeWall", 0),
            ("Ceiling", C.CEILING),
        ]
        out.append(f" <room{_attrs(room_attrs)}/>")

    attic: list[str] = []
    for level, storey in enumerate(storeys):
        out.append(" <floor>")

        for x, y, direction in storey.doors:
            attrs = [("type", "door"), ("FrameTile", C.DOOR_FRAME),
                     ("x", x), ("y", y), ("dir", direction), ("Tile", C.DOOR)]
            out.append(f"  <object{_attrs(attrs)}/>")

        for x, y, direction in storey.windows:
            tile, curtains = window_idx, curtains_idx
            if front_idx and (x, y, direction) in getattr(storey, "shop_front", ()):
                tile, curtains = front_idx, front_curtains
            attrs = [("type", "window"), ("CurtainsTile", curtains),
                     ("ShuttersTile", 0 if tile == front_idx else shutters_idx),
                     ("x", x), ("y", y),
                     ("dir", direction), ("Tile", tile)]
            out.append(f"  <object{_attrs(attrs)}/>")

        for role, x, y, orient in storey.furniture:
            attrs = [("type", "furniture"),
                     ("FurnitureTiles", roles.index(role)),
                     ("orient", orient), ("x", x), ("y", y)]
            out.append(f"  <object{_attrs(attrs)}/>")

        # A staircase belongs to the storey it rises from; the reader puts the
        # opening in the floor above by itself. Only N and W are valid
        # directions - Stairs::bounds returns an empty rect for anything else,
        # and an empty rect is treated as an invalid object.
        if level < len(building.stairs):
            sx, sy, sdir = building.stairs[level]
            attrs = [("type", "stairs"), ("x", sx), ("y", sy),
                     ("dir", sdir), ("Tile", C.STAIRS)]
            out.append(f"  <object{_attrs(attrs)}/>")

        # Roofs on the top storey only - one on each would bury every floor
        # below under a ceiling of roof tiles - and shaped to the footprint
        # rather than its bounding box, so an L-shaped building does not carry
        # a roof over its own back yard.
        # A roof over whatever of this storey has no storey above it: the
        # whole top floor, and the ledge where a tower steps back.
        above = storeys[level + 1].grid if level + 1 < len(storeys) else None
        exposed = [[v if above is None or not above[y][x] else 0
                    for x, v in enumerate(row)] for y, row in enumerate(storey.grid)]
        if any(any(row) for row in exposed):
            rects = roof_rects(exposed)
            for roof_type, depth, cap, (rx, ry, rw, rh) in _roof_pieces(
                    rects, peaked and above is None, roof30):
                roof_attrs = [
                    ("type", "roof"),
                    ("width", rw),
                    ("height", rh),
                    ("RoofType", roof_type),
                    ("Depth", depth),
                    ("cappedW", str(cap["cappedW"]).lower()),
                    ("cappedN", str(cap["cappedN"]).lower()),
                    ("cappedE", str(cap["cappedE"]).lower()),
                    ("cappedS", str(cap["cappedS"]).lower()),
                    ("CapTiles", roof_cap_idx),
                    ("SlopeTiles", slope_idx),
                    ("TopTiles", top_idx),
                    ("x", rx), ("y", ry),
                ]
                line = f"  <object{_attrs(roof_attrs)}/>"
                # BuildingEd measures a roof's height up from the floor it is
                # on. A flat roof at depth three on the top storey ends level
                # with its ceiling, which is right; a pitched roof there rose
                # through the top storey, its gable ends covering the upstairs
                # walls. Pitched roofs go on the roof floor above instead.
                (attic if roof_type != "FlatTop" else out).append(line)

        # Match BuildingWriter byte for byte: a comma follows every value
        # except the very last one, and each row ends with a newline.
        grid = building.grid_for(level)
        text = ["\n"]
        count, total = 0, building.width * building.height
        for y in range(building.height):
            for x in range(building.width):
                text.append(str(grid[y][x]))
                count += 1
                if count < total:
                    text.append(",")
            text.append("\n")
        out.append("  <rooms>" + escape("".join(text)) + "</rooms>")

        out.append(" </floor>")

    # The roof floor: no rooms. It holds the pitched roofs, and the flat roof
    # tops BuildingEd places here from the depth-three roofs below.
    empty = ["\n"]
    count, total = 0, building.width * building.height
    for _y in range(building.height):
        for _x in range(building.width):
            empty.append("0")
            count += 1
            if count < total:
                empty.append(",")
        empty.append("\n")
    out.append(" <floor>")
    out.extend(attic)
    for role, x, y, orient in rooftop:
        attrs = [("type", "furniture"), ("FurnitureTiles", roles.index(role)),
                 ("orient", orient), ("x", x), ("y", y)]
        out.append(f"  <object{_attrs(attrs)}/>")
    out.append("  <rooms>" + escape("".join(empty)) + "</rooms>")
    out.append(" </floor>")
    if attic:
        # A pitched roof's top rises a full storey above the roof floor, and
        # BuildingEd lays what is up there on the floor above that.
        out.append(" <floor>")
        out.append("  <rooms>" + escape("".join(empty)) + "</rooms>")
        out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
