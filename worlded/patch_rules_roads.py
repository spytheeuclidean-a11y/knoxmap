"""Teach WorldEd's Rules.txt to lay kerbs and road markings.

Build 42 ships kerb tiles (street_curbs_01) and painted lines
(street_trafficlines_01), but no rule places them: the vanilla map's mappers
laid every kerb and centre line by hand, which is a good part of why its
streets look finished and generated ones did not. These rules put them on the
vegetation bitmap, one colour per tile, so the renderer can mark where each
goes (see generator/rendering/roads.py, _paint_road_details).

Which edge each tile sits on was measured from the sheets themselves - where
its pixels fall inside the floor diamond - not guessed from names. The tile
edges follow the game's axes: north is up-right on screen, west up-left.

    python patch_rules_roads.py <PZMappingTools dir>

Safe to run again: rules already present are not added twice.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knoxpaths  # noqa: E402
from generator.rail_tiles import RAIL_RULES

# Rules.txt has no comment syntax - a "#" line makes WorldEd reject the whole
# file - so the rules carry the marker in their labels instead.
MARKER = "KnoxMap road"

# (label, vegetation colour, tile, layer). The colours are unused by the
# shipped rules and must match generator/pz_colors.py.
RULES = [
    ("Kerb W", (12, 34, 200), "street_curbs_01_40", "0_Curbs"),
    ("Kerb N", (12, 34, 201), "street_curbs_01_41", "0_Curbs"),
    ("Kerb S", (12, 34, 202), "street_curbs_01_42", "0_Curbs"),
    ("Kerb E", (12, 34, 203), "street_curbs_01_43", "0_Curbs"),
    ("Kerb NW", (12, 34, 204), "street_curbs_01_44", "0_Curbs"),
    ("Kerb SW", (12, 34, 205), "street_curbs_01_45", "0_Curbs"),
    ("Kerb NE", (12, 34, 206), "street_curbs_01_46", "0_Curbs"),
    ("Kerb SE", (12, 34, 207), "street_curbs_01_2", "0_Curbs"),
    # The faded paint (0-7 white, 16-23 yellow), which is what Knox County's
    # own streets use almost everywhere; the fresh set (8-15, 24-31) looked
    # newly painted beside them.
    ("Centre line yellow N", (12, 35, 200), "street_trafficlines_01_18", "0_FloorOverlay5"),
    ("Centre line yellow W", (12, 35, 201), "street_trafficlines_01_16", "0_FloorOverlay5"),
    ("Centre line white N", (12, 35, 202), "street_trafficlines_01_2", "0_FloorOverlay5"),
    ("Centre line white W", (12, 35, 203), "street_trafficlines_01_0", "0_FloorOverlay5"),
    # Edge lines, a faded white line along each side of the carriageway.
    ("Edge line W", (12, 35, 204), "street_trafficlines_01_0", "0_FloorOverlay5"),
    ("Edge line N", (12, 35, 205), "street_trafficlines_01_2", "0_FloorOverlay5"),
    ("Edge line E", (12, 35, 206), "street_trafficlines_01_4", "0_FloorOverlay5"),
    ("Edge line S", (12, 35, 207), "street_trafficlines_01_6", "0_FloorOverlay5"),
    # Overlay layers 1-4 are rewritten by the ground blends when a map is
    # generated, wiping anything a rule put there; 5 and 6 are left alone.
    # What the vanilla streets carry besides kerbs and lines, counted on their
    # squares: grime on about one in eleven, cracks, storm drains, fire
    # hydrants, a street lamp every few houses, litter. A list is picked from
    # at random for each square.
    ("Asphalt grime", (12, 36, 200),
     # The general wear vanilla lays on its tarmac (28 and 29 above all);
     # 0-11 are hard-edged dark squares that read as holes in the road.
     [f"overlay_grime_floor_01_{i}" for i in (28, 29, 30, 31, 36, 37, 38, 39)],
     "0_FloorOverlay6"),
    ("Asphalt cracks", (12, 36, 201), [f"d_streetcracks_1_{i}" for i in range(16)],
     "0_FloorOverlay6"),
    # Lamp arms measured from the sprites: 8 reaches north, 9 east, 10 south,
    # 11 west - over the road, from a post on the pavement.
    ("Street lamp N", (12, 36, 202), "lighting_outdoor_01_8", "0_Furniture"),
    ("Street lamp E", (12, 36, 203), "lighting_outdoor_01_9", "0_Furniture"),
    ("Street lamp S", (12, 36, 204), "lighting_outdoor_01_10", "0_Furniture"),
    ("Street lamp W", (12, 36, 205), "lighting_outdoor_01_11", "0_Furniture"),
    ("Fire hydrant", (12, 36, 206), "street_decoration_01_12", "0_Furniture"),
    ("Storm drain", (12, 36, 207), ["street_decoration_01_13", "street_decoration_01_14"],
     "0_FloorOverlay6"),
    # Litter. Only 0-12: trash_01_13, 14 and 15 are blank squares in the
    # sheet Build 42 ships, and a rule that names one puts a question mark on
    # the pavement where the game cannot find its picture - the "?????" every
    # street had litter on (54 and 55 are blank too, for whoever adds more).
    ("Litter", (12, 36, 208), [f"trash_01_{i}" for i in range(13)], "0_FloorOverlay6"),
    # By each house (knoxbuild/yards.py): a mailbox where the front path meets
    # the pavement, a dustbin at the top of the drive.
    # 17 is a blank square in the sheet, and was a third of the mailboxes.
    ("Mailbox", (12, 36, 209), ["street_decoration_01_18",
                                "street_decoration_01_19"], "0_Furniture"),
    ("Dustbin", (12, 36, 210), "trashcontainers_01_16", "0_Furniture"),
    # Back yards: patio grill, table and chairs, a clothesline, a raised bed.
    ("Yard grill", (12, 37, 200), "appliances_cooking_01_035", "0_Furniture"),
    ("Yard chair_w", (12, 37, 201), "furniture_seating_outdoor_01_016", "0_Furniture"),
    ("Yard chair_n", (12, 37, 202), "furniture_seating_outdoor_01_017", "0_Furniture"),
    ("Yard chair_e", (12, 37, 203), "furniture_seating_outdoor_01_019", "0_Furniture"),
    ("Yard chair_s", (12, 37, 204), "furniture_seating_outdoor_01_018", "0_Furniture"),
    ("Yard table_x0", (12, 37, 205), "furniture_seating_outdoor_01_026", "0_Furniture"),
    ("Yard table_x1", (12, 37, 206), "furniture_seating_outdoor_01_027", "0_Furniture"),
    ("Yard table_y0", (12, 37, 207), "furniture_seating_outdoor_01_025", "0_Furniture"),
    ("Yard table_y1", (12, 37, 208), "furniture_seating_outdoor_01_024", "0_Furniture"),
    ("Yard line_x0", (12, 37, 209), "appliances_laundry_01_026", "0_Furniture"),
    ("Yard line_xm", (12, 37, 210), "appliances_laundry_01_030", "0_Furniture"),
    ("Yard line_x1", (12, 37, 211), "appliances_laundry_01_027", "0_Furniture"),
    ("Yard line_y0", (12, 37, 212), "appliances_laundry_01_029", "0_Furniture"),
    ("Yard line_ym", (12, 37, 213), "appliances_laundry_01_031", "0_Furniture"),
    ("Yard line_y1", (12, 37, 214), "appliances_laundry_01_028", "0_Furniture"),
    ("Yard bed_nw", (12, 37, 215), "carpentry_03_053", "0_Furniture"),
    ("Yard bed_w", (12, 37, 216), "carpentry_03_042", "0_Furniture"),
    ("Yard bed_sw", (12, 37, 217), "carpentry_03_054", "0_Furniture"),
    ("Yard bed_n", (12, 37, 218), "carpentry_03_041", "0_Furniture"),
    ("Yard bed_s", (12, 37, 219), "carpentry_03_040", "0_Furniture"),
    ("Yard bed_ne", (12, 37, 220), "carpentry_03_055", "0_Furniture"),
    ("Yard bed_e", (12, 37, 221), "carpentry_03_043", "0_Furniture"),
    ("Yard bed_se", (12, 37, 222), "carpentry_03_052", "0_Furniture"),
    ("Yard bed_soil", (12, 37, 223), "floors_exterior_natural_01_018", "0_FloorOverlay6"),
    # Works yards (knoxbuild/works.py): pallets, drums, barrels, crates and
    # tyres along the walls, a list picked from for each square.
    ("Works pallet", (12, 39, 200), "construction_01_5", "0_Furniture"),
    ("Works bricks", (12, 39, 201), "construction_01_4", "0_Furniture"),
    ("Works drum", (12, 39, 202), [f"crafted_01_{i}" for i in range(24, 33)], "0_Furniture"),
    ("Works barrel", (12, 39, 203), ["industry_01_22", "industry_01_23"], "0_Furniture"),
    ("Works crate", (12, 39, 204), ["carpentry_01_16", "carpentry_01_19"], "0_Furniture"),
    ("Works tires", (12, 39, 205), [f"location_business_machinery_01_{i}"
                                    for i in (40, 41, 42, 43, 44, 45, 48, 49, 50, 51, 52)],
     "0_Furniture"),
    # The dumpster's halves, read off the game's tile definitions: facing S
    # it is 0,0 then 1,0 along x; facing E, 0,0 then 0,1 along y.
    ("Dumpster blue s0", (12, 39, 206), "trashcontainers_01_10", "0_Furniture"),
    ("Dumpster blue s1", (12, 39, 207), "trashcontainers_01_11", "0_Furniture"),
    ("Dumpster blue e0", (12, 39, 208), "trashcontainers_01_9", "0_Furniture"),
    ("Dumpster blue e1", (12, 39, 209), "trashcontainers_01_8", "0_Furniture"),
    ("Dumpster orange s0", (12, 39, 210), "trashcontainers_01_14", "0_Furniture"),
    ("Dumpster orange s1", (12, 39, 211), "trashcontainers_01_15", "0_Furniture"),
    ("Dumpster orange e0", (12, 39, 212), "trashcontainers_01_13", "0_Furniture"),
    ("Dumpster orange e1", (12, 39, 213), "trashcontainers_01_12", "0_Furniture"),
]

# Rules for Erika's Tiles (workshop 3346506593), written only once Setup has
# registered its sheets: a rule naming a tileset WorldEd does not know breaks
# the conversion. Speed limit signs, by limit and the way the sign faces.
ERIKA_RULES = [
    ("Speed limit 25 S", (12, 38, 200), "street_roadsigns_erika_01_18", "0_Furniture"),
    ("Speed limit 25 E", (12, 38, 201), "street_roadsigns_erika_01_19", "0_Furniture"),
    ("Speed limit 35 S", (12, 38, 202), "street_roadsigns_erika_01_20", "0_Furniture"),
    ("Speed limit 35 E", (12, 38, 203), "street_roadsigns_erika_01_21", "0_Furniture"),
    ("Speed limit 45 S", (12, 38, 204), "street_roadsigns_erika_01_24", "0_Furniture"),
    ("Speed limit 45 E", (12, 38, 205), "street_roadsigns_erika_01_25", "0_Furniture"),
]


def _blank(two_x: Path, tile: str) -> bool:
    """Whether a tile is an empty square in its sheet.

    A sheet's declared grid is often bigger than the pictures in it, and the
    leftover cells are transparent. A rule naming one of those puts "missing
    tile trash_01_14" in the console and a question mark on the pavement, so
    they are dropped here rather than shipped. False when the artwork is not
    on this PC, so patching still works without the game.
    """
    m = re.fullmatch(r"(.+)_(\d+)", tile)
    if not m:
        return False
    sheet, idx = m.group(1), int(m.group(2))
    if sheet in _ALPHA:
        alpha = _ALPHA[sheet]
    else:
        alpha = _ALPHA[sheet] = None
        path = two_x / f"{sheet}.png"
        try:
            import numpy as np
            from PIL import Image

            if path.exists():
                with Image.open(path) as img:
                    alpha = _ALPHA[sheet] = np.asarray(img.convert("RGBA"))[:, :, 3]
        except Exception:                # noqa: BLE001 - no PIL, no check
            pass
    if alpha is None:
        return False
    cols = max(1, alpha.shape[1] // 128)
    r, c = divmod(idx, cols)
    cell = alpha[r * 256:(r + 1) * 256, c * 128:(c + 1) * 128]
    return cell.size == 0 or not cell.any()


_ALPHA: dict = {}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rules_path = Path(argv[1]) / "config" / "Rules.txt"
    if not rules_path.is_file():
        # Said as a sentence, not as a traceback: Setup prints what a script
        # says into logs/setup.log, and that is where somebody reads it.
        print(f"Rules.txt not found under {rules_path.parent}", file=sys.stderr)
        return 2
    text = rules_path.read_text(encoding="utf-8", errors="replace")
    # Replace every rule of ours with the current set, so a changed tile or
    # layer reaches an install patched by an older version.
    old = len(re.findall(rf"label = {MARKER} ", text))
    # The old transparent single rail replaced 0_Floor, leaving black holes.
    # Our own blocks are rewritten in place further down, by
    # knoxpaths.lay_rule_blocks, rather than stripped and appended - appending
    # is what made this file change on every Setup (see that function).
    text = re.sub(r"\n?rule\s*\{\s*label = Railroad (?:NE-SW|NW-SE)\s.*?\}\s*",
                  "\n", text, flags=re.S)
    blocks = []
    rail_blocks = []
    for label, (r, g, b), rail in RAIL_RULES:
        for tile, layer in (("lightgravel", "0_Floor"), (rail, "0_FloorOverlay6")):
            rail_blocks.append(
                "rule\n{\n"
                f"    label = {MARKER} {label} {layer}\n"
                "    bitmap = 0\n"
                f"    color = {r} {g} {b}\n"
                f"    tiles = {tile}\n"
                f"    layer = {layer}\n"
                "}\n")
    tilesets = Path(argv[1]) / "config" / "Tilesets.txt"
    rules = list(RULES)
    if tilesets.exists() and "Erikas_Tiles.pack/street_roadsigns_erika_01\n" in \
            tilesets.read_text(encoding="utf-8", errors="replace"):
        rules += ERIKA_RULES
    two_x = Path(argv[1]) / "Tiles" / "2x"
    dropped = []
    for label, (r, g, b), tile, layer in rules:
        if isinstance(tile, list):
            keep = [t for t in tile if not _blank(two_x, t)]
            dropped += [t for t in tile if t not in keep]
            if not keep:
                continue
            tile = "[\n" + "".join(f"        {t}\n" for t in keep) + "    ]"
        elif _blank(two_x, tile):
            dropped.append(tile)
            continue
        blocks.append(
            "rule\n{\n"
            f"    label = {MARKER} {label}\n"
            "    bitmap = 1\n"
            f"    color = {r} {g} {b}\n"
            f"    tiles = {tile}\n"
            f"    layer = {layer}\n"
            "}\n")
    # Track must survive asphalt cracks and other details sharing its overlay.
    blocks.extend(rail_blocks)
    new_text = knoxpaths.lay_rule_blocks(text, MARKER, blocks)
    if new_text == rules_path.read_text(encoding="utf-8", errors="replace"):
        print("road details already up to date")
        return _finish(Path(argv[1]))
    rules_path.write_text(new_text, encoding="utf-8")
    print(f"wrote {len(blocks)} road detail rules to {rules_path} (replacing {old})")
    if dropped:
        print(f"    left out {len(dropped)} blank tiles: {', '.join(sorted(set(dropped)))}")
    return _finish(Path(argv[1]))


def _finish(root: Path) -> int:
    """0 when the file is what the window's setup card asks for, else 3.

    The same question, from the same place (knoxpaths.road_rules_ok), so Setup
    can trust this exit code: a file without the kerb and street-furniture
    rules is not "set up", however cleanly the run went.
    """
    if knoxpaths.road_rules_ok(root):
        return 0
    print("the road rules are still not the ones the map tools need: the kerb and "
          "street-furniture rules are missing, or the litter rule still names a "
          "blank tile", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
