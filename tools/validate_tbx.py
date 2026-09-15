"""Check generated .tbx files against BuildingEd's reader rules.

Replicates every rejection path in BuildingReader that we can check without
running the editor, so a clean run here means the file should load.

    python tools/validate_tbx.py output/<map>/buildings
"""
from __future__ import annotations

import glob
import os
import sys
import xml.etree.ElementTree as ET

VALID_DIRS = {"N", "W"}
VALID_ORIENTS = {"W", "N", "E", "S"}

# category -> accepted enum names, taken from the catalogue.
#
# These were originally hard-coded from the 2015-era BuildingTemplates.txt and
# wrongly rejected Build 42 keys like 'WestWindow3'. The catalogue is generated
# straight from the config BuildingEd itself loads, so it is the better
# authority; this check now catches only the thing we can actually get wrong -
# emitting an enum we never sourced.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from knoxbuild import catalog as _C  # noqa: E402

CATEGORY_ENUMS: dict[str, set[str]] = {}


def _collect(node) -> None:
    """Every tile entry the catalog can write, shared or in a style - all of
    them copied from the editor's own config, so their enums are its enums."""
    if isinstance(node, dict):
        if isinstance(node.get("category"), str) and isinstance(node.get("tiles"), dict):
            CATEGORY_ENUMS.setdefault(node["category"], set()).update(node["tiles"])
        for v in node.values():
            _collect(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _collect(v)


_collect([_C.TILE_ENTRIES, _C.HOUSE_STYLES, _C.SPECIAL_STYLES,
          getattr(_C, "SPECIAL_STYLE_VARIANTS", {})])

# BuildingReader rejects anything outside this, and accepts versions 1..7.
MAX_BUILDING_DIMENSION = 300
VALID_VERSIONS = {str(v) for v in range(1, 8)}

VALID_ROOF_TYPES = {"FlatTop", "SlopeW", "SlopeN", "SlopeE", "SlopeS",
                    "PeakWE", "PeakNS", "Peak30WE", "Peak30NS", "Peak30Quad"}
VALID_ROOF_DEPTHS = {"Zero", "Point5", "One", "OnePoint5", "Two",
                     "TwoPoint5", "Three"}


def check(path: str) -> list[str]:
    errs: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"XML parse error: {exc}"]

    if root.tag != "building":
        return [f"root is <{root.tag}>, expected <building>"]
    if root.get("version") not in VALID_VERSIONS:
        errs.append(f"version={root.get('version')!r} outside 1..7")

    w = int(root.get("width", 0))
    h = int(root.get("height", 0))
    if w < 1 or h < 1 or w > MAX_BUILDING_DIMENSION or h > MAX_BUILDING_DIMENSION:
        errs.append(f"size {w}x{h} outside 1..{MAX_BUILDING_DIMENSION}")

    entries = root.findall("tile_entry")
    furniture = root.findall("furniture")
    rooms = root.findall("room")

    for i, e in enumerate(entries, 1):
        cat = e.get("category")
        if cat not in CATEGORY_ENUMS:
            errs.append(f"tile_entry {i}: unknown category {cat!r}")
            continue
        for t in e.findall("tile"):
            if t.get("enum") not in CATEGORY_ENUMS[cat]:
                errs.append(f"tile_entry {i} ({cat}): bad enum {t.get('enum')!r}")
            if not t.get("tile"):
                errs.append(f"tile_entry {i} ({cat}): empty tile name")

    for i, f in enumerate(furniture):
        for e in f.findall("entry"):
            if e.get("orient") not in VALID_ORIENTS:
                errs.append(f"furniture {i}: bad orient {e.get('orient')!r}")
            for t in e.findall("tile"):
                if int(t.get("x", -1)) < 0 or int(t.get("y", -1)) < 0:
                    errs.append(f"furniture {i}: negative tile offset")

    # Building-level and room-level tile references are 1-based, 0 = none.
    def check_ref(where: str, val: str | None) -> None:
        if val is None:
            return
        n = int(val)
        if n < 0 or n > len(entries):
            errs.append(f"{where}: tile entry index {n} out of range "
                        f"(have {len(entries)})")

    for attr in ("ExteriorWall", "ExteriorWallTrim", "Door", "DoorFrame",
                 "Window", "Curtains", "Shutters", "Stairs", "RoofCap",
                 "RoofSlope", "RoofTop", "GrimeWall"):
        check_ref(f"building/{attr}", root.get(attr))

    for i, r in enumerate(rooms):
        for attr in ("InteriorWall", "InteriorWallTrim", "Floor",
                     "GrimeFloor", "GrimeWall", "Ceiling"):
            check_ref(f"room {i}/{attr}", r.get(attr))
        if not r.get("InternalName"):
            errs.append(f"room {i}: missing InternalName")
        col = (r.get("Color") or "").split()
        if len(col) != 3 or not all(c.isdigit() for c in col):
            errs.append(f"room {i}: bad Color {r.get('Color')!r}")

    floors = root.findall("floor")
    if not floors:
        return errs + ["missing <floor>"]

    # Every storey, not just the first. A <floor> per level is how a building
    # gets more than one, and a fault on an upper floor rejects the whole file
    # just as surely as one on the ground.
    for level, floor in enumerate(floors):
        where = f"floor {level}"
        for o in floor.findall("object"):
            typ = o.get("type")
            x, y = int(o.get("x", -1)), int(o.get("y", -1))
            # Reader: x < 0 || x >= width+1 || y < 0 || y >= height+1
            if not (0 <= x <= w and 0 <= y <= h):
                errs.append(f"{where}: {typ} at ({x},{y}) outside 0..{w},0..{h}")
            if typ in ("door", "window", "stairs"):
                if o.get("dir") not in VALID_DIRS:
                    errs.append(f"{where}: {typ} bad dir {o.get('dir')!r}")
                check_ref(f"{where} {typ}/Tile", o.get("Tile"))
                check_ref(f"{where} {typ}/FrameTile", o.get("FrameTile"))
                check_ref(f"{where} {typ}/CurtainsTile", o.get("CurtainsTile"))
                check_ref(f"{where} {typ}/ShuttersTile", o.get("ShuttersTile"))
            if typ == "stairs":
                # Stairs::bounds is 1x5 facing N and 5x1 facing W, and returns
                # an empty rect for any other direction. The run has to fit
                # inside the building or the flight ends in mid-air.
                if o.get("dir") == "N" and y + 5 > h + 1:
                    errs.append(f"{where}: stairs at ({x},{y}) run off the south edge")
                if o.get("dir") == "W" and x + 5 > w + 1:
                    errs.append(f"{where}: stairs at ({x},{y}) run off the east edge")
                if level >= len(floors) - 2:
                    errs.append(f"{where}: stairs on the top storey lead nowhere")
            elif typ == "furniture":
                idx = int(o.get("FurnitureTiles", -1))
                # furnitureIndex is 0-based, unlike tile entries.
                if not (0 <= idx < len(furniture)):
                    errs.append(f"{where}: furniture index {idx} out of range "
                                f"(have {len(furniture)})")
                if o.get("orient") not in VALID_ORIENTS:
                    errs.append(f"{where}: furniture bad orient {o.get('orient')!r}")
            elif typ == "roof":
                # Flat roofs sit on the top storey with Depth Three, and
                # BuildingEd lays their tiles on the empty floor above it.
                # Pitched ones go on the roof floor above it.
                pitched = any(r.get("RoofType") != "FlatTop" for r in floors[-2].iter("object")
                              if r.get("type") == "roof") if len(floors) >= 2 else False
                top = len(floors) - (3 if pitched else 2)
                # A flat roof may also cover the ledge where a tower steps back.
                parapet = o.get("RoofType") == "FlatTop" and o.get("Depth") == "Point5"
                if parapet:
                    if level != top + 1:
                        errs.append(f"{where}: parapet on floor {level}, expected the roof floor {top + 1}")
                elif o.get("RoofType") == "FlatTop":
                    if level > top:
                        errs.append(f"{where}: flat roof on floor {level}, above the top storey {top}")
                elif level != top + 1:
                    errs.append(f"{where}: {o.get('RoofType')} roof on floor {level}, expected {top + 1}")
                if o.get("RoofType") == "FlatTop" and o.get("Depth") not in ("Three", "Point5"):
                    errs.append(f"{where}: flat roof Depth {o.get('Depth')!r} compiles to no roof - use Three")
                if o.get("RoofType") not in VALID_ROOF_TYPES:
                    errs.append(f"{where}: roof bad RoofType {o.get('RoofType')!r}")
                if o.get("Depth") not in VALID_ROOF_DEPTHS:
                    errs.append(f"{where}: roof bad Depth {o.get('Depth')!r}")
                for attr in ("CapTiles", "SlopeTiles", "TopTiles"):
                    check_ref(f"{where} roof/{attr}", o.get(attr))
                for attr in ("cappedW", "cappedN", "cappedE", "cappedS"):
                    if o.get(attr) not in ("true", "false"):
                        errs.append(f"{where}: roof bad {attr}={o.get(attr)!r}")
                rw, rh = int(o.get("width", 0)), int(o.get("height", 0))
                if rw <= 0 or rh <= 0 or x + rw > w or y + rh > h:
                    errs.append(f"{where}: roof {rw}x{rh} at ({x},{y}) "
                                f"does not fit {w}x{h}")
            elif typ not in ("door", "window", "stairs"):
                errs.append(f"{where}: unknown object type {typ!r}")

        grid = floor.find("rooms")
        if grid is None or not (grid.text or "").strip():
            errs.append(f"{where}: missing or empty <rooms>")
            continue
        vals = [v for v in (grid.text or "").replace("\n", ",").split(",")
                if v.strip() != ""]
        if len(vals) != w * h:
            errs.append(f"{where}: <rooms> has {len(vals)} values, "
                        f"expected {w*h}")
        for v in vals:
            n = int(v)
            if n < 0 or n > len(rooms):
                errs.append(f"{where}: <rooms> index {n} out of range "
                            f"(have {len(rooms)} rooms)")
                break
    return errs


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    files = sorted(glob.glob(os.path.join(argv[1], "*.tbx")))
    if not files:
        print(f"no .tbx files in {argv[1]}")
        return 2
    bad = 0
    for path in files:
        errs = check(path)
        if errs:
            bad += 1
            print(f"FAIL {os.path.basename(path)}")
            for e in errs[:6]:
                print(f"   - {e}")
    print(f"\n{len(files) - bad}/{len(files)} files valid")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
