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
        if style.get("curtains") is False:
            curtains_idx = 0
    # A depth-three flat roof walls in its storey with the cap entry's
    # CapGap tiles, which BuildingTemplates.txt sets to stucco - every top
    # floor came out stucco whatever the building was made of. Give each
    # building a cap entry whose gaps are its own exterior wall.
    ext_tiles = entries[exterior_idx - 1]["tiles"]
    if ext_tiles.get("West") and ext_tiles.get("North"):
        cap = dict(entries[C.ROOF_CAP - 1]["tiles"])
        cap["CapGapE3"], cap["CapGapS3"] = ext_tiles["West"], ext_tiles["North"]
        entries.append({"category": "roof_caps", "tiles": cap})
        roof_cap_idx = len(entries)

    # Which furniture roles this building actually uses, in first-use order.
    roles: list[str] = []
    for storey in storeys:
        for role, _x, _y, _o in storey.furniture:
            if role not in roles:
                roles.append(role)

    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']

    building_attrs = [
        ("version", VERSION),
        ("width", building.width),
        ("height", building.height),
        ("ExteriorWall", exterior_idx),
        ("ExteriorWallTrim", 0),
        ("Door", C.DOOR),
        ("DoorFrame", C.DOOR_FRAME),
        ("Window", window_idx),
        ("Curtains", curtains_idx),
        ("Shutters", 0),
        ("Stairs", C.STAIRS),
        ("RoofCap", roof_cap_idx),
        ("RoofSlope", C.ROOF_SLOPE),
        ("RoofTop", C.ROOF_TOP),
        ("GrimeWall", 0),
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

    for level, storey in enumerate(storeys):
        out.append(" <floor>")

        for x, y, direction in storey.doors:
            attrs = [("type", "door"), ("FrameTile", C.DOOR_FRAME),
                     ("x", x), ("y", y), ("dir", direction), ("Tile", C.DOOR)]
            out.append(f"  <object{_attrs(attrs)}/>")

        for x, y, direction in storey.windows:
            attrs = [("type", "window"), ("CurtainsTile", curtains_idx),
                     ("ShuttersTile", 0), ("x", x), ("y", y),
                     ("dir", direction), ("Tile", window_idx)]
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
        if level == len(storeys) - 1:
            for rx, ry, rw, rh, _caps in roof_rects(storey.grid):
                roof_attrs = [
                    ("type", "roof"),
                    ("width", rw),
                    ("height", rh),
                    ("RoofType", "FlatTop"),
                    # "Zero" puts a flat roof's tiles in this storey's own
                    # floor layer, where the rooms' floors then overwrite
                    # them: every building compiled roofless. "Three" is
                    # BuildingEd's flat roof over a full storey, laid in the
                    # floor layer of the floor above (see the empty roof floor
                    # written after the storeys).
                    ("Depth", "Three"),
                    # No caps: at depth three a cap is a storey-high wall of
                    # brick roof tiles laid over the top storey's own walls,
                    # which turned every house's top floor into brick.
                    ("cappedW", "false"),
                    ("cappedN", "false"),
                    ("cappedE", "false"),
                    ("cappedS", "false"),
                    ("CapTiles", roof_cap_idx),
                    ("SlopeTiles", C.ROOF_SLOPE),
                    ("TopTiles", C.ROOF_TOP),
                    ("x", rx), ("y", ry),
                ]
                out.append(f"  <object{_attrs(roof_attrs)}/>")

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

    # The roof floor: no rooms, no objects, only the flat roof tops BuildingEd
    # places here from the depth-three roofs on the storey below.
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
    out.append("  <rooms>" + escape("".join(empty)) + "</rooms>")
    out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
