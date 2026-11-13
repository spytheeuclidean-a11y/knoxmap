"""Hand-made buildings compiled by WorldEd, to learn what each part of a .tbx becomes.

    bx.py <name> [...]        names are keys of CASES below
Output: scratchpad/bx/<name>/ (a copy of the flat-grass project with one building in it).
"""
import contextlib
import copy
import io
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
from tools import compile_map as cm

H = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = f"{H}/exp/house/buildings/house_0000.tbx"
BASE = f"{H}/exp/base"
LOT_X, LOT_Y = 40, 40          # where the building goes, in tiles of the first 300x300 cell


def make_tbx(width, height, floors):
    """floors: list of {"rooms": [[ids per row]...], "objects": [attribute dicts]}"""
    root = ET.parse(TEMPLATE).getroot()
    for f in [c for c in root if c.tag == "floor"]:
        root.remove(f)
    root.set("width", str(width))
    root.set("height", str(height))
    # keep only the first few room definitions; ids in the grids are 1-based
    rooms = [c for c in root if c.tag == "room"]
    for r in rooms[20:]:
        root.remove(r)
    for fl in floors:
        f = ET.SubElement(root, "floor")
        for o in fl.get("objects", []):
            ET.SubElement(f, "object", {k: str(v) for k, v in o.items()})
        grid = fl.get("rooms") or [[0] * width for _ in range(height)]
        rm = ET.SubElement(f, "rooms")
        rm.text = "\n" + ",\n".join(",".join(str(v) for v in row) for row in grid) + "\n"
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def block(w, h, room=1, x0=0, y0=0, rw=None, rh=None):
    g = [[0] * w for _ in range(h)]
    for y in range(y0, y0 + (rh or h)):
        for x in range(x0, x0 + (rw or w)):
            g[y][x] = room
    return g


def two_rooms(w, h, a=1, b=2):
    g = [[a] * w for _ in range(h)]
    for y in range(h):
        for x in range(w // 2, w):
            g[y][x] = b
    return g


CASES = {
    "room6x5": (6, 5, [{"rooms": block(6, 5)}]),
    "door": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="door", FrameTile=3, x=2, y=0, dir="N", Tile=2)]}]),
    "doorW": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="door", FrameTile=3, x=0, y=2, dir="W", Tile=2)]}]),
    "doorS": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="door", FrameTile=3, x=2, y=5, dir="N", Tile=2)]}]),
    "doorE": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="door", FrameTile=3, x=6, y=2, dir="W", Tile=2)]}]),
    "doorIn": (6, 5, [{"rooms": two_rooms(6, 5), "objects": [dict(type="door", FrameTile=3, x=3, y=2, dir="W", Tile=2)]}]),
    "windowS": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=0, ShuttersTile=0, x=2, y=5, dir="N", Tile=21)]}]),
    "windowW": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=0, ShuttersTile=0, x=0, y=2, dir="W", Tile=21)]}]),
    "wSc": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=5, ShuttersTile=0, x=2, y=5, dir="N", Tile=21)]}]),
    "wSs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=0, ShuttersTile=23, x=2, y=5, dir="N", Tile=21)]}]),
    "wScs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=5, ShuttersTile=23, x=2, y=5, dir="N", Tile=21)]}]),
    "wNcs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=5, ShuttersTile=23, x=2, y=0, dir="N", Tile=21)]}]),
    "wWcs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=5, ShuttersTile=23, x=0, y=2, dir="W", Tile=21)]}]),
    "wEcs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=5, ShuttersTile=23, x=6, y=2, dir="W", Tile=21)]}]),
    "ceil1": (6, 5, [{"rooms": block(6, 5)}, {"rooms": [[0] * 6 for _ in range(5)]}]),
    "ceil2": (6, 5, [{"rooms": block(6, 5)}, {"rooms": block(6, 5)}, {"rooms": [[0] * 6 for _ in range(5)]}]),
    "stairsW": (9, 6, [{"rooms": block(9, 6), "objects": [dict(type="stairs", x=1, y=1, dir="W", Tile=6)]}, {"rooms": block(9, 6)}, {"rooms": [[0] * 9 for _ in range(6)]}]),
    "stairsN": (6, 9, [{"rooms": block(6, 9), "objects": [dict(type="stairs", x=1, y=1, dir="N", Tile=6)]}, {"rooms": block(6, 9)}, {"rooms": [[0] * 6 for _ in range(9)]}]),
    "window": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="window", CurtainsTile=0, ShuttersTile=0, x=2, y=0, dir="N", Tile=21)]}]),
    "two": (6, 5, [{"rooms": two_rooms(6, 5)}]),
    "floors2": (6, 5, [{"rooms": block(6, 5)}, {"rooms": block(6, 5)}]),
    "roof": (6, 5, [{"rooms": block(6, 5)}, {"rooms": [[0] * 6 for _ in range(5)], "objects": [
        dict(type="roof", width=6, height=5, RoofType="PeakWE", Depth="Three", cappedW="true", cappedN="false",
             cappedE="true", cappedS="false", CapTiles=27, SlopeTiles=25, TopTiles=26, x=0, y=0)]}]),
    "stairs": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="stairs", x=1, y=1, dir="W", Tile=6)]}, {"rooms": block(6, 5)}]),
    "furn": (6, 5, [{"rooms": block(6, 5), "objects": [dict(type="furniture", FurnitureTiles=0, orient="E", x=2, y=2)]}]),
    "outside": (6, 5, [{"rooms": block(4, 3, rw=4, rh=3) and [[0, 0, 0, 0, 0, 0], [0, 1, 1, 1, 1, 0], [0, 1, 1, 1, 1, 0], [0, 1, 1, 1, 1, 0], [0, 0, 0, 0, 0, 0]]}]),
}


def roof_obj(rtype, depth, w, h, x, y, caps=""):
    return dict(type="roof", width=w, height=h, RoofType=rtype, Depth=depth,
                cappedW=str("W" in caps).lower(), cappedN=str("N" in caps).lower(),
                cappedE=str("E" in caps).lower(), cappedS=str("S" in caps).lower(),
                CapTiles=27, SlopeTiles=25, TopTiles=26, x=x, y=y)


ROOF_SETS = {
    # (RoofType, Depth, w, h, caps)
    "roofsA": [("PeakWE", "Three", 8, 6, ""), ("PeakWE", "Three", 8, 6, "WE"), ("PeakWE", "Three", 8, 6, "W"),
               ("PeakWE", "TwoPoint5", 8, 5, ""), ("PeakWE", "Two", 8, 4, ""), ("PeakWE", "OnePoint5", 8, 3, ""),
               ("PeakWE", "One", 8, 2, ""), ("PeakWE", "Point5", 8, 1, "")],
    "roofsB": [("PeakNS", "Three", 6, 8, ""), ("PeakNS", "Three", 6, 8, "NS"), ("PeakNS", "TwoPoint5", 5, 8, ""),
               ("PeakNS", "Two", 4, 8, ""), ("PeakNS", "OnePoint5", 3, 8, ""), ("PeakNS", "One", 2, 8, ""),
               ("PeakNS", "Point5", 1, 8, ""), ("PeakNS", "Three", 7, 8, "N")],
    "roofsD": [("PeakWE", "Three", 8, 7, ""), ("PeakWE", "Three", 8, 8, ""), ("PeakWE", "Three", 8, 9, ""),
               ("PeakWE", "Three", 8, 12, ""), ("PeakWE", "Two", 8, 4, "WE"), ("PeakWE", "TwoPoint5", 8, 5, "WE"),
               ("PeakWE", "OnePoint5", 8, 3, "WE"), ("PeakWE", "One", 8, 2, "WE"), ("PeakWE", "Point5", 8, 1, "WE")],
    "roofsE": [("PeakWE", "Three", 8, 7, "WE"), ("PeakWE", "Three", 8, 8, "WE"), ("PeakWE", "Three", 8, 9, "WE"),
               ("PeakWE", "Three", 8, 12, "WE"), ("PeakNS", "Three", 7, 8, "NS"), ("PeakNS", "Two", 4, 8, "NS"),
               ("PeakNS", "TwoPoint5", 5, 8, "NS"), ("PeakNS", "One", 2, 8, "NS"), ("PeakNS", "Three", 12, 8, "NS")],
    "roofsC": [("Peak30WE", "Zero", 10, 5, ""), ("Peak30WE", "Zero", 10, 7, ""), ("Peak30WE", "Zero", 10, 5, "WE"),
               ("Peak30NS", "Zero", 5, 10, ""), ("Peak30NS", "Zero", 7, 10, "NS"),
               ("Peak30Quad", "Zero", 5, 5, ""), ("Peak30Quad", "Zero", 7, 7, ""), ("Peak30WE", "Zero", 10, 9, "")],
}
for _n, _roofs in ROOF_SETS.items():
    _objs = []
    for _i, (_t, _d, _w, _h, _c) in enumerate(_roofs):
        _objs.append(roof_obj(_t, _d, _w, _h, 2 + _i * 13, 2, _c))
    _W = 2 + len(_roofs) * 13
    CASES[_n] = (_W, 16, [{"rooms": block(_W, 16)}, {"rooms": [[0] * _W for _ in range(16)], "objects": _objs}])

ROOF_SETS["roofsF"] = ROOF_SETS["roofsE"]
ROOF_SETS["roofsG"] = ROOF_SETS["roofsD"]
CASES["roofsF"] = (CASES["roofsE"][0], 16, CASES["roofsE"][2] + [{"rooms": [[0] * CASES["roofsE"][0] for _ in range(16)]}])
CASES["roofsG"] = (CASES["roofsD"][0], 16, CASES["roofsD"][2] + [{"rooms": [[0] * CASES["roofsD"][0] for _ in range(16)]}])
CASES["flat"] = (40, 14, [{"rooms": block(40, 14), "objects": [
    roof_obj("FlatTop", "Three", 6, 5, 2, 2), roof_obj("FlatTop", "Three", 3, 3, 12, 2),
    roof_obj("FlatTop", "Three", 9, 9, 18, 2)]}, {"rooms": [[0] * 40 for _ in range(14)]}])


def make(name):
    w, h, floors = CASES[name]
    out = f"{H}/bx/{name}"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(f"{out}/buildings")
    # the flat-grass project, without its lots
    for f in os.listdir(BASE):
        src = f"{BASE}/{f}"
        if f in ("lots", "buildings", "build_cache.json") or f.endswith((".geojson", ".npz")):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, f"{out}/{f}")
        else:
            shutil.copy2(src, f"{out}/{f}")
    # the .pzw is named after the project folder, and points at its own files
    pzw = open(f"{BASE}/base.pzw", encoding="utf-8").read()
    pzw = re.sub(r'[A-Za-z]:/[^"]*?/scratchpad/exp/base', out.replace("\\", "/"), pzw, flags=re.I)
    pzw = pzw.replace("base.bmp", f"{name}.bmp")
    pzw = re.sub(r"(?<![\w])base(_|\.|\")", lambda m: name + m.group(1), pzw)
    lot = f'  <lot x="{LOT_X}" y="{LOT_Y}" level="0" width="{w}" height="{h}" map="buildings/{name}.tbx"/>\n'
    pzw = re.sub(r'(<cell x="0" y="0"[^>]*>\n)', lambda m: m.group(1) + lot, pzw, count=1)
    # the flat project's file names
    for f in os.listdir(out):
        if f.startswith("base"):
            os.rename(f"{out}/{f}", f"{out}/{name}{f[4:]}")
    for f in os.listdir(f"{out}/tmx"):
        if f.startswith("base"):
            os.rename(f"{out}/tmx/{f}", f"{out}/tmx/{name}{f[4:]}")
    open(f"{out}/{name}.pzw", "w", encoding="utf-8").write(pzw)
    open(f"{out}/buildings/{name}.tbx", "w", encoding="utf-8").write(make_tbx(w, h, floors))
    os.makedirs(f"{out}/lots", exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        cm.compile_map(out, batch=1, only_cells=[[0, 0, 0, 0]], incremental=False)
    return out


if __name__ == "__main__":
    for n in sys.argv[1:]:
        out = make(n)
        print("made", n, sorted(os.listdir(f"{out}/lots"))[:4])
