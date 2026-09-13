"""Generate knoxbuild/catalog.py from the PZ mapping tools' own config files.

Point this at the `config` folder of a PZ_Mapping_Tools install, so the tile
names come from the same data BuildingEd itself loads:

    python tools/make_catalog.py ../PZMappingTools/config knoxbuild/catalog.py

Entries are selected by tile NAME, never by position. An earlier version indexed
into BuildingTemplates.txt numerically, which silently pointed at the wrong
entries when run against a different revision of the file - and picked
`walls_interior_house_01_020`, which the Build 42 config does not contain at
all. A missing anchor is now a hard error.
"""
from __future__ import annotations

import collections
import os
import pprint
import re
import sys


def parse_tile_entries(path: str) -> list[dict]:
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for m in re.finditer(r'TileEntry\s*\{(.*?)\n\}', txt, re.S):
        d = {}
        for line in m.group(1).strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
        out.append(d)
    return out


def parse_furniture(path: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    g = fur = ent = None
    for raw in open(path, encoding="utf-8", errors="replace").read().splitlines():
        s = raw.strip()
        if s == "group":
            g = {"label": None, "furniture": []}
        elif s.startswith("label = ") and g is not None and g["label"] is None:
            g["label"] = s[8:]
            groups[g["label"]] = g["furniture"]
        elif s == "furniture" and g is not None:
            fur = {"entries": [], "layer": "Furniture"}
            g["furniture"].append(fur)
            ent = None
        elif s.startswith("layer = ") and fur is not None and ent is None:
            fur["layer"] = s[8:]
        elif s == "entry" and fur is not None:
            ent = {"orient": None, "tiles": {}}
            fur["entries"].append(ent)
        elif s.startswith("orient = ") and ent is not None:
            ent["orient"] = s[9:]
        elif re.match(r"^\d+,\d+ = ", s) and ent is not None:
            k, v = s.split(" = ", 1)
            ent["tiles"][k] = v
    return groups


def parse_room_names(path: str) -> dict[str, str]:
    """internal name -> 'r g b', from the tools' RoomNames.txt."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    for m in re.finditer(r'internal = (\S+)\s*\n\s*label = [^\n]*\n\s*color = #([0-9A-Fa-f]{6})', txt):
        name, hexv = m.group(1), m.group(2)
        r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
        out[name] = f"{r} {g} {b}"
    return out


def main(argv: list[str]) -> int:
    cfg_dir, out_path = argv[1], argv[2]
    entries = parse_tile_entries(os.path.join(cfg_dir, "BuildingTemplates.txt"))
    groups = parse_furniture(os.path.join(cfg_dir, "BuildingFurniture.txt"))
    room_colors = parse_room_names(os.path.join(cfg_dir, "RoomNames.txt"))
    print(f"parsed {len(entries)} tile entries, {len(groups)} furniture groups, "
          f"{len(room_colors)} room names")

    def tile_keys(e: dict) -> dict:
        """Just the enum -> tile-name pairs.

        Roof entries also carry `offset = SlopePt5S 1 1`, which is a property,
        not a tile. Copying it through made BuildingEd reject every building
        with "Unknown roof_slopes enum 'offset'". A real tile value is a single
        token, so anything with whitespace is not one.
        """
        return {k: v for k, v in e.items()
                if k not in ("category", "offset") and v and " " not in v}

    def pick(category: str, anchor: str) -> dict:
        """The entry of `category` whose first tile value is `anchor`."""
        for e in entries:
            if e.get("category") != category:
                continue
            out = tile_keys(e)
            vals = list(out.values())
            if vals and vals[0] == anchor:
                return {"category": category, "tiles": out}
        raise SystemExit(f"ERROR: no {category} entry anchored at {anchor!r}. "
                         f"The config may have changed - pick a new anchor from "
                         f"tools/make_catalog.py.")

    # Order defines the 1-based index the .tbx refers to.
    WANTED = [
        ("exterior_walls", "walls_exterior_house_01_032"),
        ("doors", "fixtures_doors_01_000"),
        ("door_frames", "fixtures_doors_frames_01_000"),
        ("windows", "fixtures_windows_01_000"),
        ("curtains", "fixtures_windows_curtains_01_032"),
        ("stairs", "fixtures_stairs_01_000"),
        ("interior_walls", "walls_interior_house_01_016"),
        ("floors", "floors_interior_carpet_01_000"),
        ("floors", "floors_interior_carpet_01_008"),
        ("floors", "floors_interior_tilesandwood_01_043"),
        ("floors", "floors_interior_tilesandwood_01_011"),
        ("floors", "floors_interior_tilesandwood_01_016"),
        ("floors", "floors_interior_tilesandwood_01_041"),
        ("roof_caps", "walls_exterior_roofs_01_096"),
        ("roof_slopes", "roofs_01_000"),
        ("roof_tops", "roofs_01_054"),
        ("ceiling", "ceilings_01_000"),
        ("interior_wall_trim", "walls_interior_detailing_01_004"),
    ]
    tile_entries = [pick(cat, anchor) for cat, anchor in WANTED]

    ROLES = {
        "bed": "furniture_bedding_01_002",
        "bed_alt": "furniture_bedding_01_010",
        "sofa": "furniture_seating_indoor_01_003",
        # Anchors below were corrected after rendering them (see
        # tools/preview_catalog.py). The originals were, respectively, an
        # armchair filed as a plain chair, an ottoman filed as an armchair, a
        # cardboard box filed as a wardrobe, and a second toilet filed as a
        # bath. Re-render the contact sheet before changing any of them.
        "chair": "furniture_seating_indoor_02_004",
        "armchair": "furniture_seating_indoor_01_013",
        "table": "furniture_tables_low_01_002",
        "wardrobe": "furniture_storage_01_001",
        "crate": "furniture_storage_02_024",
        "dresser": "furniture_storage_01_008",
        "shelf": "furniture_shelving_01_002",
        "fridge": "appliances_refrigeration_01_001",
        "stove": "appliances_cooking_01_000",
        "toilet": "fixtures_bathroom_01_001",
        "bath": "fixtures_bathroom_01_026",
        "sink": "fixtures_sinks_01_001",
        "counter": "fixtures_counters_01_003",
        "tv": "appliances_television_01_000",
        # Extra dressing so rooms are not four items in a big empty box.
        # All verified present; the four-facing ones are marked.
        # A wall light switch, despite the old name "lamp": the first piece of
        # the "Lighting - Indoor" group. It is what the game hangs a room's
        # ceiling light off, so every room gets one.
        "switch": "lighting_indoor_01_001",        # E N S W
        "bookshelf": "furniture_shelving_01_041",  # E N S W
        "sidetable": "furniture_tables_low_01_011",
        "plant": "d_plants_1_016",                 # E N S W
        "mirror": "walls_decoration_01_003",       # E N S W
        "painting": "walls_decoration_01_034",
        "wardrobe2": "furniture_storage_01_037",
    }

    def find_furniture(anchor: str) -> dict:
        """All four facings for a piece, keyed by orientation.

        Keeping only W and N was a real bug: a sofa placed against the south
        wall with orient N has its back to the room, which is what "the props
        are rotated wrong" looks like in game. The source defines E and S for
        most pieces (1301 and 1231 entries), so take whatever is there.
        """
        for furs in groups.values():
            for f in furs:
                for e in f["entries"]:
                    if e["orient"] == "W" and e["tiles"].get("0,0") == anchor:
                        out = {}
                        for e2 in f["entries"]:
                            if e2["orient"] in ("W", "N", "E", "S") \
                                    and e2["orient"] not in out:
                                out[e2["orient"]] = e2["tiles"]
                        if "W" in out and "N" in out:
                            layers[anchor] = f["layer"]
                            return out
        raise SystemExit(f"ERROR: furniture anchor not found: {anchor!r}")

    layers: dict[str, str] = {}
    furniture = {role: find_furniture(a) for role, a in ROLES.items()}
    # Which layer each piece lives on. A light switch, a painting or a mirror
    # belongs on the WallFurniture layer; written without a layer it becomes
    # floor furniture standing in the middle of the tile.
    furniture_layers = {role: layers[a] for role, a in ROLES.items()}

    # Wall and floor palettes. Every building used to share one exterior wall
    # and one interior wall, so a whole town came out identical. Houses now draw
    # from HOUSE_STYLES (picked per neighbourhood block, so a street stays
    # coherent while the next one differs), and anything OSM tags as a school,
    # church, shop, diner or works gets its own materials from SPECIAL_STYLES.
    HOUSE_STYLE_SPEC = [
        ("clapboard", "walls_exterior_house_01_032", "walls_interior_house_01_016"),
        ("brick", "walls_exterior_house_01_016", "walls_interior_house_02_000"),
        ("painted", "walls_exterior_house_01_052", "walls_interior_house_03_000"),
        ("stucco", "walls_exterior_house_02_004", "walls_interior_house_02_032"),
        ("panel", "walls_exterior_house_02_016", "walls_interior_house_03_020"),
        ("timber", "walls_exterior_wooden_01_024", "walls_interior_house_01_052"),
        ("logs", "walls_logs_000", "walls_interior_house_03_032"),
        ("trailer", "location_trailer_01_000", "location_trailer_01_024"),
        # BuildingTemplates.txt offers 24 exterior wall families and the first
        # eight entries here used a third of them, so a long street ran out of
        # variety and started repeating itself.
        ("render", "walls_exterior_house_02_064", "walls_interior_house_03_036"),
        ("plaster", "walls_interior_house_02_032", "walls_interior_bathroom_01_000"),
    ]
    house_styles = []
    for style_name, ext, inte in HOUSE_STYLE_SPEC:
        house_styles.append({
            "name": style_name,
            "exterior": pick("exterior_walls", ext),
            "interior": pick("interior_walls", inte),
        })

    # kind -> materials, and the floor that overrides the usual palette.
    SPECIAL_SPEC = {
        "school":     ("walls_commercial_01_048", "location_community_school_01_000",
                       "location_shop_generic_01_004"),
        "church":     ("location_community_church_small_01_000",
                       "location_community_church_small_01_004", None),
        "restaurant": ("location_restaurant_diner_01_000",
                       "location_restaurant_diner_01_000",
                       "location_restaurant_diner_01_040"),
        "shop":       ("location_shop_gas2go_01_000", "location_shop_gas2go_01_000",
                       "location_shop_generic_01_004"),
        "industrial": ("industry_01_000", "industry_01_000", "carpentry_02_056"),
        "barn":       ("location_barn_01_000", "walls_exterior_wooden_01_024", None),
        "medical":    ("walls_commercial_01_048", "location_community_school_01_000",
                       "floors_interior_tilesandwood_01_011"),
        "civic":      ("walls_commercial_01_048", "walls_commercial_01_048",
                       "location_shop_generic_01_004"),
        # Blocks of flats want to read as neither house nor office: rendered
        # masonry outside, painted plaster and carpet in the shared parts.
        "apartment":  ("walls_interior_house_03_032", "walls_interior_house_02_048",
                       "floors_interior_carpet_01_032"),
    }
    special_styles = {}
    for kind, (ext, inte, floor) in SPECIAL_SPEC.items():
        special_styles[kind] = {
            "name": kind,
            "exterior": pick("exterior_walls", ext),
            "interior": pick("interior_walls", inte),
            "floor": pick("floors", floor) if floor else None,
        }

    KINDS = ["livingroom", "kitchen", "bedroom", "bathroom", "dining",
             "hall", "storage", "office",
             # Rooms only special buildings use; all present in RoomNames.txt.
             "classroom", "church", "warehouse", "garage", "clinic",
             "bar", "restaurant", "lobby", "gym", "library", "medical"]
    missing = [k for k in KINDS if k not in room_colors]
    if missing:
        raise SystemExit(f"ERROR: room names absent from RoomNames.txt: {missing}")
    colors = {k: room_colors[k] for k in KINDS}

    names = collections.Counter()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write('"""Tile, furniture and room data for knoxbuild.\n\n'
                "GENERATED by tools/make_catalog.py from a PZ_Mapping_Tools\n"
                "config folder - every name here is one BuildingEd itself loads.\n"
                "Regenerate rather than editing by hand.\n\"\"\"\n"
                "from __future__ import annotations\n\n")
        f.write("# 1-based: the .tbx references these positionally.\n")
        f.write("TILE_ENTRIES = " + pprint.pformat(tile_entries, width=100, sort_dicts=False) + "\n\n")
        for i, (cat, anchor) in enumerate(WANTED, 1):
            names[cat] += 1
        f.write("EXTERIOR_WALL = 1\nDOOR = 2\nDOOR_FRAME = 3\nWINDOW = 4\n"
                "CURTAINS = 5\nSTAIRS = 6\nINTERIOR_WALL = 7\n\n")
        f.write("FLOOR_CARPET_RED = 8\nFLOOR_CARPET_BLUE = 9\nFLOOR_WOOD = 10\n"
                "FLOOR_TILE_PALE = 11\nFLOOR_TILE_CHECK = 12\nFLOOR_LINO = 13\n\n")
        f.write("ROOF_CAP = 14\nROOF_SLOPE = 15\nROOF_TOP = 16\n"
                "CEILING = 17\nINTERIOR_WALL_TRIM = 18\n\n")
        f.write("FURNITURE = " + pprint.pformat(furniture, width=100, sort_dicts=False) + "\n\n")
        f.write("# Furniture layer per role; anything but Furniture sits on a wall.\n")
        f.write("FURNITURE_LAYERS = " + pprint.pformat(furniture_layers, width=100) + "\n\n")
        f.write("# Official room colours, straight from the tools' RoomNames.txt.\n")
        f.write("ROOM_COLORS = " + pprint.pformat(colors, width=100, sort_dicts=False) + "\n\n")
        f.write("# Houses draw from these, picked per neighbourhood block so a\n"
                "# street stays coherent while the next one differs.\n")
        f.write("HOUSE_STYLES = " + pprint.pformat(house_styles, width=100, sort_dicts=False) + "\n\n")
        f.write("# Materials for buildings OSM tags as something particular.\n")
        f.write("SPECIAL_STYLES = " + pprint.pformat(special_styles, width=100, sort_dicts=False) + "\n")

    print(f"wrote {out_path}: {len(tile_entries)} tile entries, "
          f"{len(furniture)} furniture roles, {len(colors)} room colours")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
