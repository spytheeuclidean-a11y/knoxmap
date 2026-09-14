"""Teach WorldEd's Rules.txt to lay kerbs and road markings.

Build 42 ships kerb tiles (street_curbs_01) and painted lines
(street_trafficlines_01), but no rule places them: the vanilla map's mappers
laid every kerb and centre line by hand, which is a good part of why its
streets look finished and generated ones did not. These rules put them on the
vegetation bitmap, one colour per tile, so the renderer can mark where each
goes (see generator/renderer.py, _paint_road_details).

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
    ("Litter", (12, 36, 208), [f"trash_01_{i}" for i in range(15)], "0_FloorOverlay6"),
]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rules_path = Path(argv[1]) / "config" / "Rules.txt"
    text = rules_path.read_text(encoding="utf-8", errors="replace")
    # Replace every rule of ours with the current set, so a changed tile or
    # layer reaches an install patched by an older version.
    old = len(re.findall(rf"label = {MARKER} ", text))
    text = re.sub(rf"\n?rule\n\{{\n    label = {MARKER} .*?\n\}}\n?", "\n", text, flags=re.S)
    blocks = []
    for label, (r, g, b), tile, layer in RULES:
        if isinstance(tile, list):
            tile = "[\n" + "".join(f"        {t}\n" for t in tile) + "    ]"
        blocks.append(
            "rule\n{\n"
            f"    label = {MARKER} {label}\n"
            "    bitmap = 1\n"
            f"    color = {r} {g} {b}\n"
            f"    tiles = {tile}\n"
            f"    layer = {layer}\n"
            "}\n")
    new_text = text.rstrip("\n") + "\n\n" + "\n".join(blocks)
    if new_text == rules_path.read_text(encoding="utf-8", errors="replace"):
        print("road details already up to date")
        return 0
    rules_path.write_text(new_text, encoding="utf-8")
    print(f"wrote {len(blocks)} road detail rules to {rules_path} (replacing {old})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
