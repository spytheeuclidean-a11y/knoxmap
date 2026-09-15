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

    # BuildingTemplates.txt names only three windows; the editor's full list
    # is in BuildingTiles.txt, as West/North pairs.
    tiles_txt = open(os.path.join(cfg_dir, "BuildingTiles.txt"), encoding="utf-8",
                     errors="replace").read()
    window_pairs = dict(re.findall(r"West = (fixtures_windows_\w+)\s+North = (\w+)", tiles_txt))

    def bt_entry(category: str, anchor: str | None) -> dict | None:
        """An entry of BuildingTiles.txt's `category` whose first tile is
        `anchor` - the editor's full lists, where the templates hold a few."""
        if not anchor:
            return None
        start = tiles_txt.index(f"name = {category}\n")
        nxt = tiles_txt.find("\n    name = ", start + 10)
        block = tiles_txt[start:nxt if nxt > 0 else None]
        for body in re.findall(r"entry\s*\{(.*?)\}", block, re.S):
            pairs = re.findall(r"^\s*(\w+) = ([^\n]*)$", body, re.M)
            tiles = {k: v.strip() for k, v in pairs if k != "offset" and v.strip()}
            if tiles and next(iter(tiles.values())) == anchor:
                return {"category": category, "tiles": tiles}
        raise SystemExit(f"ERROR: no {category} {anchor!r} in BuildingTiles.txt.")

    def wall_entry(anchor: str) -> dict:
        """An exterior wall from the templates, or the editor's full list."""
        for e in entries:
            if e.get("category") == "exterior_walls":
                vals = list(tile_keys(e).values())
                if vals and vals[0] == anchor:
                    return {"category": "exterior_walls", "tiles": tile_keys(e)}
        return bt_entry("exterior_walls", anchor)

    def caps_for(wall: str, fallback: str | None) -> dict | None:
        """The gable-end set the editor pairs with this exterior wall: each of
        its roof_caps entries names the wall it belongs to in CapGapE3."""
        start = tiles_txt.index("name = roof_caps\n")
        nxt = tiles_txt.find("\n    name = ", start + 10)
        for body in re.findall(r"entry\s*\{(.*?)\}", tiles_txt[start:nxt], re.S):
            pairs = dict((k, v.strip()) for k, v in re.findall(r"^\s*(\w+) = ([^\n]*)$", body, re.M))
            if pairs.get("CapGapE3") == wall and pairs.get("CapPeak30S1"):
                tiles = {k: v for k, v in pairs.items() if k != "offset" and v}
                return {"category": "roof_caps", "tiles": tiles}
        return bt_entry("roof_caps", fallback) if fallback else None

    def curtains(anchor: str | None) -> dict | None:
        """A curtains entry from its West tile: East, North, South follow it."""
        if not anchor:
            return None
        sheet, idx = anchor.rsplit("_", 1)
        n = int(idx)
        names = [f"{sheet}_{n + i:03d}" for i in range(4)]
        if names[0] not in tiles_txt:
            raise SystemExit(f"ERROR: no curtains {anchor!r} in BuildingTiles.txt.")
        return {"category": "curtains",
                "tiles": dict(zip(("West", "East", "North", "South"), names))}

    def roof(slopes: str | None, top: str, peaked: bool) -> dict:
        """Roof materials: a slope family from the templates, and a flat-top
        tile used for all three depths (the templates' roofs_01_054 entry has
        the same tile in every slot too)."""
        # From BuildingTiles.txt: its slope entries carry the 30-degree
        # tiles as well, which the templates' copies leave out.
        return {"slopes": bt_entry("roof_slopes", slopes) if slopes else None,
                "tops": {"category": "roof_tops",
                         "tiles": {k: top for k in ("West1", "West2", "West3",
                                                    "North1", "North2", "North3")}},
                "peaked": peaked}

    def window(anchor: str) -> dict:
        if anchor not in window_pairs:
            raise SystemExit(f"ERROR: no window {anchor!r} in BuildingTiles.txt.")
        return {"category": "windows",
                "tiles": {"West": anchor, "North": window_pairs[anchor]}}

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
        # What Knox County's own houses are furnished with most, counted in
        # their rooms (tools/building_stats.py): double beds, the kitchen sink
        # and stove, showers and bath mats, table lamps, shag rugs, dressers.
        "double_bed": "furniture_bedding_01_030",       # 2x2
        "double_bed_alt": "furniture_bedding_01_042",   # 2x2
        "kitchen_sink": "fixtures_sinks_01_008",
        "stove_alt": "appliances_cooking_01_012",
        "shower": "fixtures_bathroom_01_035",           # 2x1
        "bath_mat": "floors_rugs_01_051",               # 1x2
        "lamp": "lighting_indoor_01_008",
        "shag_rug": "floors_rugs_02_000",               # 2x2
        "dresser_alt": "furniture_storage_01_012",
        "washer": "appliances_laundry_01_001",
        "wall_cabinet": "fixtures_counters_01_027",     # above a counter
        "microwave": "appliances_cooking_01_068",
        # On flat roofs (tbx.ROOFTOP): an air-conditioning unit, a vent, a hatch.
        "roof_ac": "rooftop_furniture_001",
        "roof_vent": "rooftop_furniture_015",
        "roof_hatch": "rooftop_furniture_022",
        # Pieces for the middle of a room (layout.CENTRE_GROUPS): a room
        # furnished only along its walls was an empty floor with a ring of
        # furniture round it.
        "dining_table": "furniture_tables_high_01_000",   # 2x1
        "round_table": "furniture_tables_high_01_023",    # 1x1, E N S W
        "coffee_table": "furniture_tables_low_01_001",    # 1x2
        "rug": "floors_rugs_01_024",                      # 2x3, E N S W
        "rug_wide": "floors_rugs_01_119",                 # 3x2, E N S W
        "rug_small": "floors_rugs_01_006",                # 2x2, E N S W
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
        ("clapboard", "walls_exterior_house_01_032", "walls_interior_house_01_016", "fixtures_windows_01_008", "fixtures_windows_curtains_01_032"),
        ("brick", "walls_exterior_house_01_016", "walls_interior_house_02_000", "fixtures_windows_wood_008", "fixtures_windows_curtains_01_040"),
        ("painted", "walls_exterior_house_01_052", "walls_interior_house_03_000", "fixtures_windows_white_024", "fixtures_windows_curtains_02_008"),
        ("stucco", "walls_exterior_house_02_004", "walls_interior_house_02_032", "fixtures_windows_01_024", "fixtures_windows_curtains_02_000"),
        ("panel", "walls_exterior_house_02_016", "walls_interior_house_03_020", "fixtures_windows_01_032", "fixtures_windows_curtains_02_000"),
        ("timber", "walls_exterior_wooden_01_024", "walls_interior_house_01_052", "fixtures_windows_wood_024", "fixtures_windows_curtains_01_040"),
        ("logs", "walls_logs_000", "walls_interior_house_03_032", "fixtures_windows_wood_016", "fixtures_windows_curtains_01_040"),
        ("trailer", "location_trailer_01_000", "location_trailer_01_024", "fixtures_windows_01_000", "fixtures_windows_curtains_02_008"),
        # BuildingTemplates.txt offers 24 exterior wall families and the first
        # eight entries here used a third of them, so a long street ran out of
        # variety and started repeating itself.
        ("render", "walls_exterior_house_02_064", "walls_interior_house_03_036", "fixtures_windows_white_016", "fixtures_windows_curtains_01_032"),
        # Painted clapboard in the colours Knox County's own houses wear. The
        # old "plaster" style was an interior wall used outside; the editor has
        # no gable ends for it, so its roofs ended in white triangles.
        ("siding_blue", "walls_exterior_house_02_020", "walls_interior_house_02_000", "fixtures_windows_white_024", "fixtures_windows_curtains_02_000"),
        ("siding_yellow", "walls_exterior_house_02_032", "walls_interior_house_03_000", "fixtures_windows_white_016", "fixtures_windows_curtains_01_032"),
        ("siding_green", "walls_exterior_house_02_080", "walls_interior_house_01_016", "fixtures_windows_white_024", "fixtures_windows_curtains_01_040"),
        ("siding_pink", "walls_exterior_house_02_068", "walls_interior_house_03_036", "fixtures_windows_white_016", "fixtures_windows_curtains_02_000"),
        ("siding_grey", "walls_exterior_house_01_000", "walls_interior_house_02_032", "fixtures_windows_01_008", "fixtures_windows_curtains_02_008"),
    ]
    # Houses have pitched roofs: every building used to wear the same flat
    # brown planks, which is no roof a suburb has. (slopes, flat top, peaked):
    # the top covers the flat middle of a wide house between its two slopes.
    SLATE = ("roofs_01_000", "roofs_01_022", True)
    BROWN = ("roofs_02_000", "roofs_02_022", True)
    WOOD = ("roofs_03_000", "roofs_03_022", True)
    RED = ("roofs_04_000", "roofs_04_022", True)  # 04_054 is white
    HOUSE_ROOFS = {"clapboard": SLATE, "brick": BROWN, "painted": RED, "stucco": WOOD,
                   "panel": SLATE, "timber": WOOD, "logs": WOOD, "render": RED,
                   "siding_blue": SLATE, "siding_yellow": BROWN, "siding_green": BROWN,
                   "siding_pink": SLATE, "siding_grey": RED,
                   # A trailer's roof is flat.
                   "trailer": (None, "roofs_01_054", False)}
    # The triangle of wall at a gable end, in the house's own material rather
    # than the one tan stone every gable had. Matched by eye against each
    # style's exterior wall.
    ROOF_CAPS = {"clapboard": "walls_exterior_roofs_03_024",
                 "brick": "walls_exterior_roofs_04_000",
                 "painted": "walls_exterior_roofs_04_024",
                 "stucco": "walls_exterior_roofs_01_096",
                 "panel": "walls_exterior_roofs_06_000",
                 "timber": "walls_exterior_roofs_02_024",
                 "logs": "walls_logs_016",
                 "trailer": "walls_exterior_roofs_03_024",
                 "render": "walls_exterior_roofs_09_080",
                 "barn": "location_barn_01_024",
                 "church": "walls_exterior_roofs_10_224"}
    # What makes a Knox County house read as a house from outside, besides its
    # roof: a trim board or foundation along the bottom of each storey and
    # shutters either side of the windows. (trim, shutters) per style.
    WHITE_BASE, FOUNDATION, BASE = ("walls_detailing_01_013", "walls_detailing_01_005",
                                    "walls_detailing_01_021")
    WHITE_S, BLUE_S, BROWN_S, DARK_S = ("fixtures_windows_detailing_01_016",
                                        "fixtures_windows_detailing_01_020",
                                        "fixtures_windows_detailing_01_024",
                                        "fixtures_windows_detailing_01_028")
    HOUSE_TRIM = {"clapboard": (WHITE_BASE, DARK_S), "brick": (FOUNDATION, WHITE_S),
                  "painted": (FOUNDATION, WHITE_S), "stucco": (BASE, BROWN_S),
                  "panel": (FOUNDATION, BLUE_S), "timber": (None, None),
                  "logs": (None, None), "trailer": ("location_trailer_01_004", None),
                  "render": (WHITE_BASE, DARK_S),
                  "siding_blue": (WHITE_BASE, WHITE_S), "siding_yellow": (WHITE_BASE, DARK_S),
                  "siding_green": (WHITE_BASE, WHITE_S), "siding_pink": (WHITE_BASE, WHITE_S),
                  "siding_grey": (WHITE_BASE, BLUE_S)}
    # Weathering streaks on every outside wall; spotless walls read as
    # plastic next to the game's own buildings, which all carry it.
    GRIME = pick("grime_wall", "overlay_grime_wall_01_000")
    house_styles = []
    for style_name, ext, inte, window_name, curtain_name in HOUSE_STYLE_SPEC:
        house_styles.append({
            "name": style_name,
            "exterior": wall_entry(ext),
            "interior": pick("interior_walls", inte),
            "window": window(window_name),
            "curtains": curtains(curtain_name),
            "roof": roof(*HOUSE_ROOFS[style_name]),
            "trim": bt_entry("exterior_wall_trim", HOUSE_TRIM[style_name][0]),
            "shutters": bt_entry("shutters", HOUSE_TRIM[style_name][1]),
            "grime": GRIME,
        })
        house_styles[-1]["roof"]["caps"] = caps_for(ext, ROOF_CAPS.get(style_name))

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
    # Every building once had the same brown four-pane window, and later a
    # small one everywhere. A wall tile is one storey (226 px) and the small
    # domestic windows are 95 px of it - right for a house, lost on a block of
    # flats or an office, where real facades are tall panes or whole panels of
    # glass. So a style lists its windows by height of building: (from this
    # many storeys, window, curtains or None). Every window used to hang the
    # same pink drapes; flats, offices and clinics get roller blinds, and
    # glass panels hang nothing - a curtain sized for a small window looks
    # stuck on. "shop_front" glazes the ground
    # floor of a shop or restaurant. Measured heights: small 95-105 px, tall
    # 150-160, floor-to-ceiling 216-225.
    SPECIAL_WINDOWS = {
        # Tall three-pane classroom windows.
        "school": [(1, "fixtures_windows_metal_020", None)],
        # Stained glass.
        "church": [(1, "fixtures_windows_church_014", None)],
        "restaurant": [(1, "fixtures_windows_01_048", "fixtures_windows_curtains_01_040")],
        "shop": [(1, "fixtures_windows_01_048", "fixtures_windows_curtains_02_000")],
        # Wide, low windows high on a works wall.
        "industrial": [(1, "fixtures_windows_metal_026", None)],
        "barn": [(1, "fixtures_windows_wood_024", None)],
        "medical": [(1, "fixtures_windows_white_010", "fixtures_windows_curtains_02_000"),
                    (5, "fixtures_windows_metal_010", "fixtures_windows_curtains_02_000")],
        # Offices, hotels, town halls: tall panes, then glass from the height
        # layout.GLASS_TOWER_FROM_LEVELS glazes every tile.
        "civic": [(1, "fixtures_windows_white_010", "fixtures_windows_curtains_02_000"),
                  (5, "fixtures_windows_metal_010", "fixtures_windows_curtains_02_000"),
                  (8, "fixtures_windows_metal_014", None)],
        # Low flats: tall sash. Mid-rise: tall double panes. Towers: panels
        # floor to ceiling.
        "apartment": [(1, "fixtures_windows_white_016", "fixtures_windows_curtains_02_000"),
                      (5, "fixtures_windows_metal_010", "fixtures_windows_curtains_02_000"),
                      (12, "fixtures_windows_metal_014", None)],
    }
    # Anything big is flat-roofed in grey membrane, not wooden planks; barns
    # and churches are pitched.
    FLAT_GREY = (None, "floors_exterior_street_01_016", False)  # roofs_02_054 is half transparent
    SPECIAL_ROOFS = {"barn": RED, "church": SLATE}
    SHOP_FRONTS = {
        "shop": ("fixtures_windows_metal_014", None),
        "restaurant": ("fixtures_windows_metal_008", None),
    }
    # Every block of flats was cream render and every office the same school
    # wall, so a city centre came out one colour from end to end. Knox County's
    # big buildings are brick in several colours, stone and pale commercial
    # block; each building now takes one of these by where it stands.
    SPECIAL_WALLS = {
        "apartment": ["walls_exterior_house_02_064", "walls_exterior_house_01_016",
                      "walls_exterior_house_01_052", "walls_exterior_house_02_036",
                      "walls_exterior_house_02_048", "walls_exterior_house_02_016"],
        "civic": ["walls_commercial_03_000", "walls_commercial_03_016",
                  "walls_commercial_03_032", "walls_exterior_house_02_004",
                  "walls_exterior_house_02_048", "walls_exterior_house_02_064"],
        "medical": ["walls_commercial_03_032", "walls_exterior_house_02_048"],
        "school": ["walls_exterior_house_01_016", "walls_exterior_house_02_064"],
        "shop": ["walls_commercial_03_000", "walls_exterior_house_02_064",
                 "walls_exterior_house_01_016", "walls_commercial_03_048"],
        "restaurant": ["walls_exterior_house_02_064", "walls_commercial_03_016"],
    }
    special_styles = {}
    special_variants = {}
    for kind, (ext, inte, floor) in SPECIAL_SPEC.items():
        by_height = SPECIAL_WINDOWS[kind]
        style = {
            "name": kind,
            "exterior": pick("exterior_walls", ext),
            "interior": pick("interior_walls", inte),
            "floor": pick("floors", floor) if floor else None,
            "window": window(by_height[0][1]),
            "curtains": curtains(by_height[0][2]),
            "windows_by_levels": [[levels, window(name), curtains(cur)]
                                  for levels, name, cur in by_height],
            "roof": roof(*SPECIAL_ROOFS.get(kind, FLAT_GREY)),
            "trim": bt_entry("exterior_wall_trim",
                             None if kind in ("church", "barn", "industrial") else FOUNDATION),
            "shutters": None,
            "grime": GRIME,
        }
        style["roof"]["caps"] = caps_for(ext, ROOF_CAPS.get(kind))
        if kind in SHOP_FRONTS:
            name, cur = SHOP_FRONTS[kind]
            style["shop_front"] = [window(name), curtains(cur)]
        special_styles[kind] = style
        # The same building in other materials, so a city is not one colour.
        variants = []
        for wall in [ext] + [w for w in SPECIAL_WALLS.get(kind, ()) if w != ext]:
            v = dict(style)
            v["exterior"] = wall_entry(wall)
            v["roof"] = dict(style["roof"])
            v["roof"]["caps"] = caps_for(wall, ROOF_CAPS.get(kind))
            variants.append(v)
        special_variants[kind] = variants

    KINDS = ["livingroom", "kitchen", "bedroom", "bathroom", "dining",
             "hall", "storage", "office",
             # Rooms only special buildings use; all present in RoomNames.txt.
             "classroom", "church", "warehouse", "garage", "clinic",
             "bar", "restaurant", "lobby", "gym", "library", "medical", "shed",
             "elevator", "kidsbedroom", "closet", "laundry"]
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
        # Elevator doors are not in BuildingFurniture.txt, so they are written
        # here directly. They are the vanilla tiles the Elevators mod looks
        # for (fixtures_escalators_01_48-51), set into the Walls layer, which
        # BuildingEd uses to replace a stretch of wall with the given tiles.
        # Each door is two squares wide; the halves were matched to their end
        # of the doorway from the artwork - the frame post is on the outer end.
        furniture["elevator_door"] = {
            "W": {"0,0": "fixtures_escalators_01_49", "0,1": "fixtures_escalators_01_48"},
            "N": {"0,0": "fixtures_escalators_01_50", "1,0": "fixtures_escalators_01_51"},
        }
        furniture_layers["elevator_door"] = "Walls"
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
        f.write("\nSPECIAL_STYLE_VARIANTS = "
                + pprint.pformat(special_variants, width=100, sort_dicts=False) + "\n")

    print(f"wrote {out_path}: {len(tile_entries)} tile entries, "
          f"{len(furniture)} furniture roles, {len(colors)} room colours")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
