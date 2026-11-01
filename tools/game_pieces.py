"""Furniture roles read straight off the game's own tile definitions.

    python tools/game_pieces.py        prints the block knoxbuild/catalog.py ends with

BuildingEd's furniture file has no pews, pool tables, salon chairs, treadmills
or coin laundry machines, so these come from media/newtiledefinitions.tiles.txt
instead: each tile's Facing says which wall the piece stands against (the
catalog key, FACING_TO_ORIENT) and its SpriteGridPos where it sits in a piece
of several tiles. tools/make_catalog.py writes the same block.
"""
from __future__ import annotations

import os
import pprint
import re

# The catalog keys a piece by the wall it stands against; the game by the way
# it faces, which is away from that wall.
FACING_TO_ORIENT = {"S": "N", "E": "W", "N": "S", "W": "E"}

# role: (sheet, tile numbers, layer). A role whose tiles do not cover all four
# facings has only the walls they do, which layout.NORTH_WEST_ONLY picks up.
GAME_PIECES = {
    # Churches: a pew of three seats, and the altar facing them.
    "pew": ("location_community_church_small_01", [48, 49, 50, 51, 52, 53, 56, 57, 58, 59, 60, 61], "Furniture"),
    "altar": ("location_community_church_small_01", [40, 41, 42, 43], "Furniture"),
    # Bars: the counter, its stools, the bottle shelves behind it, a pool
    # table, a jukebox and an arcade cabinet.
    "bar_counter": ("location_restaurant_bar_01", [1, 3, 5, 7], "Furniture"),
    "bar_shelf": ("location_restaurant_bar_01", [30, 38], "Furniture"),
    "pool_table": ("recreational_01", [2, 3, 6, 7], "Furniture"),
    "jukebox": ("recreational_01", [0, 1], "Furniture"),
    "arcade": ("recreational_01", [20, 21, 22, 23], "Furniture"),
    # Laundromats.
    "coin_washer": ("appliances_laundry_01", [4, 5, 6, 7], "Furniture"),
    "coin_dryer": ("appliances_laundry_01", [12, 13, 14, 15], "Furniture"),
    # Hair salons: the chair and the hood dryer.
    "salon_chair": ("location_services_beauty_01", [0, 1, 2, 3], "Furniture"),
    "hair_dryer": ("location_services_beauty_01", [8, 9, 10, 11], "Furniture"),
    # Gyms: treadmills and weight machines, two tiles each.
    "treadmill": ("recreational_sports_01", [28, 29, 30, 31], "Furniture"),
    "weight_machine": ("recreational_sports_01", [40, 41, 42, 43], "Furniture"),
    "weight_machine_alt": ("recreational_sports_01", [44, 45, 46, 47], "Furniture"),
    # Children's rooms.
    "bunk_bed": ("furniture_bedding_01", [84, 85, 86, 87], "Furniture"),
    # A home's tables in its other woods (interiors.TONES): low tables the
    # height of the coffee table (Surface 15), and white and light oak dining
    # tables.
    "low_table_tan": ("furniture_tables_low_01", [16, 17], "Furniture"),
    "low_table_black": ("furniture_tables_low_01", [18, 19], "Furniture"),
    "low_table_white": ("furniture_tables_low_01", [20, 21], "Furniture"),
    "dining_table_white": ("furniture_tables_high_01", [44, 45, 46, 47], "Furniture"),
    "dining_table_oak": ("furniture_tables_high_01", [60, 61, 62, 63], "Furniture"),
    # The small things a home has (interiors.dress_room): a toaster and a
    # coffee maker on the worktop, a radio on a chest, a mirrored vanity in a
    # bedroom, a cot in a baby's room, and a small mirror over a basin and a
    # clock over a worktop on the north and west walls.
    "coffee_maker": ("appliances_cooking_01", [56, 57, 58, 59], "Furniture"),
    "toaster": ("appliances_cooking_01", [32, 33], "Furniture"),
    "radio": ("appliances_radio_01", [0, 1, 2, 3], "Furniture"),
    "vanity": ("furniture_storage_01", [40, 41, 42, 43], "Furniture"),
    "crib": ("furniture_bedding_01", [88, 89, 90, 91], "Furniture"),
    "mirror_small": ("walls_decoration_01", [10, 11], "WallFurniture"),
    "clock": ("walls_decoration_01", [104, 105], "WallFurniture"),
    # The rest of a home's and a shop's (interiors.dress_room): a telephone,
    # a coat rack by the door, cardboard boxes in a closet or a stockroom, a
    # laundry hamper, an air vent on the wall, a sale sign in a shop.
    "phone": ("location_business_office_generic_02", [0, 1, 2, 3], "Furniture"),
    "coat_rack": ("location_community_school_01", [36, 37, 38, 39], "Furniture"),
    "box": ("trashcontainers_01", [24, 25], "Furniture"),
    "box_battered": ("trashcontainers_01", [26, 27], "Furniture"),
    "hamper": ("appliances_laundry_01", [24, 25], "Furniture"),
    "wall_vent": ("rooftop_furniture", [34, 35], "WallFurniture"),
    "sale_sign": ("location_shop_generic_01", [70, 71], "Furniture"),
}
# A bar stool is round: the one sprite, whichever way.
ROUND = {"bar_stool": ("location_restaurant_bar_01_26", "Furniture"),
         # A kitchen's or a bathroom's waste bin.
         "bin": ("trashcontainers_01_20", "Furniture")}
# The door mat has no Facing in the game's definitions: its two halves are
# laid out as the bath mat's are (floors_rugs_01 48-51), so it is set the same.
FIXED = {"door_mat": ({"W": {"0,0": "floors_rugs_01_059", "0,1": "floors_rugs_01_058"},
                       "N": {"0,0": "floors_rugs_01_056", "1,0": "floors_rugs_01_057"}},
                      "FloorFurniture")}
# Posters for a teenager's room: walls_decoration_05 0-7 face south (a north
# wall) and 8-15 are the same posters facing east (a west wall).
POSTERS = [(f"walls_decoration_05_{n:03d}", f"walls_decoration_05_{n + 8:03d}") for n in range(8)]


def tiledefs_path() -> str:
    try:
        import knoxpaths
        game = knoxpaths.pz_install_dir()
    except Exception:            # noqa: BLE001 - no game found: the default Steam folder
        game = None
    game = game or r"C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid"
    return os.path.join(str(game), "media", "newtiledefinitions.tiles.txt")


def _props(txt: str) -> dict[str, dict]:
    out = {}
    for name, body in re.findall(r"// (\S+)\s*\n\s*tile\s*\{(.*?)\n\s*\}", txt, re.S):
        out[name] = dict(re.findall(r"^[ \t]*(\w+)[ \t]*=[ \t]*(.*?)[ \t]*$", body, re.M))
    return out


def build(path: str | None = None) -> tuple[dict, dict]:
    """(furniture, layers) for every role above."""
    txt = open(path or tiledefs_path(), encoding="utf-8", errors="replace").read()
    props = _props(txt)
    furniture: dict = {}
    layers: dict = {}
    for role, (sheet, numbers, layer) in GAME_PIECES.items():
        piece: dict = {}
        for n in numbers:
            p = props.get(f"{sheet}_{n}")
            if not p or p.get("Facing") not in FACING_TO_ORIENT:
                raise SystemExit(f"ERROR: {sheet}_{n} has no Facing")
            orient = FACING_TO_ORIENT[p["Facing"]]
            at = (p.get("SpriteGridPos") or "0,0").replace(" ", "")
            piece.setdefault(orient, {}).setdefault(at, f"{sheet}_{n:03d}")
        furniture[role] = piece
        layers[role] = layer
    for role, (tile, layer) in ROUND.items():
        furniture[role] = {o: {"0,0": tile} for o in ("W", "N", "E", "S")}
        layers[role] = layer
    for role, (piece, layer) in FIXED.items():
        furniture[role] = piece
        layers[role] = layer
    for i, (north, west) in enumerate(POSTERS):
        furniture[f"poster_{i}"] = {"N": {"0,0": north}, "W": {"0,0": west}}
        layers[f"poster_{i}"] = "WallFurniture"
    return furniture, layers


def block(path: str | None = None) -> str:
    furniture, layers = build(path)
    return ("\n# Pieces read off the game's own tile definitions (tools/game_pieces.py).\n"
            "FURNITURE.update(" + pprint.pformat(furniture, width=100, sort_dicts=False) + ")\n"
            "FURNITURE_LAYERS.update(" + pprint.pformat(layers, width=100) + ")\n"
            f"POSTERS = {[f'poster_{i}' for i in range(len(POSTERS))]!r}\n")


if __name__ == "__main__":
    print(block())
