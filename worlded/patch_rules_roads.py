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
    ("Centre line yellow N", (12, 35, 200), "street_trafficlines_01_26", "0_FloorOverlay5"),
    ("Centre line yellow W", (12, 35, 201), "street_trafficlines_01_24", "0_FloorOverlay5"),
    ("Centre line white N", (12, 35, 202), "street_trafficlines_01_10", "0_FloorOverlay5"),
    ("Centre line white W", (12, 35, 203), "street_trafficlines_01_8", "0_FloorOverlay5"),
]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rules_path = Path(argv[1]) / "config" / "Rules.txt"
    text = rules_path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        print("road details already present")
        return 0
    blocks = []
    for label, (r, g, b), tile, layer in RULES:
        blocks.append(
            "rule\n{\n"
            f"    label = {MARKER} {label}\n"
            "    bitmap = 1\n"
            f"    color = {r} {g} {b}\n"
            f"    tiles = {tile}\n"
            f"    layer = {layer}\n"
            "}\n")
    rules_path.write_text(text.rstrip("\n") + "\n" + "\n".join(blocks), encoding="utf-8")
    print(f"added {len(RULES)} road detail rules to {rules_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
