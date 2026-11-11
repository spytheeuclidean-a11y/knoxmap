"""Which window variant does WorldEd pick, and what does it depend on?"""
import collections
import os
import re
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bxshow import load
from knoxbuild.buildtiles import parse_tbx, _entry

H = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 21000
proj = f"{H}/real/{sys.argv[1]}"
name = os.path.basename(proj)
cells = {}


def world(tx, ty, z):
    cx, cy = (ORIGIN + tx) // 256, ty // 256
    if (cx, cy) not in cells:
        try:
            cells[(cx, cy)] = load(f"{proj}/lots", cx, cy)
        except FileNotFoundError:
            cells[(cx, cy)] = ({}, 0)
    return cells[(cx, cy)][0].get(((ORIGIN + tx) - cx * 256, ty - cy * 256, z), [])


lots, cell = [], None
for line in open(f"{proj}/{name}.pzw", encoding="utf-8"):
    m = re.match(r'\s*<cell x="(\d+)" y="(\d+)"', line)
    if m:
        cell = (int(m[1]), int(m[2]))
    m = re.search(r'<lot x="(\d+)" y="(\d+)" level="(\d+)" width="(\d+)" height="(\d+)" map="buildings/([^"]+)\.tbx"', line)
    if m and cell:
        x, y, lv, w, h, t = m.groups()
        lots.append((cell[0] * 300 + int(x), cell[1] * 300 + int(y), int(lv), t))

rows = collections.Counter()
by = collections.defaultdict(collections.Counter)
for tx0, ty0, lv, tbx in lots:
    if any(k in tbx for k in ("fences", "lights", "structures", "bridge", "monument")):
        continue
    b = parse_tbx(open(f"{proj}/buildings/{tbx}.tbx", encoding="utf-8").read())
    for z, fl in enumerate(b.floors):
        for o in fl.objects:
            if o.get("type") != "window":
                continue
            x, y = int(o["x"]), int(o["y"])
            d = "North" if o.get("dir") == "N" else "West"
            stack = world(tx0 + x, ty0 + y, z + lv)
            r = fl.rooms[y][x] if 0 <= x < b.width and 0 <= y < b.height else 0
            ent = _entry(b, b.attrs["ExteriorWall"]) if r == 0 else _entry(b, b.rooms[r - 1]["InteriorWall"])
            nums = sorted({int(re.sub(r"\D", "", e) or 0) for e, t in ent.items() if e.startswith(d + "Window") and t in stack})
            win = _entry(b, o.get("Tile")).get(d, "?")
            cur = _entry(b, o.get("CurtainsTile")).get("North" if d == "North" else "West", "-")
            sh = _entry(b, o.get("ShuttersTile")).get("NorthLeft" if d == "North" else "WestAbove", "-")
            key = ("ext" if r == 0 else "int", win[-18:], cur[-12:], sh[-12:])
            rows[key] += 1
            by[key][tuple(nums)] += 1
print("(side, window tile, curtain tile, shutter tile) -> candidate variant numbers (0 = plain)")
for key, c in sorted(rows.items(), key=lambda kv: -kv[1])[:24]:
    print(f"  {key}: {c}  {dict(by[key].most_common(3))}")
