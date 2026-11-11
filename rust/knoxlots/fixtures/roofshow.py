"""Show roof tiles by their BuildingEd names.

    roofshow.py <case> <level> <x0> <y0> <w> <h>      region in tiles from the lot's corner
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bx
from bxshow import load
from knoxbuild.buildtiles import tile_name

H = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 21000

case, z, x0, y0, w, h = sys.argv[1], int(sys.argv[2]), *(int(a) for a in sys.argv[3:7])
root = ET.parse(f"{H}/bx/{case}/buildings/{case}.tbx").getroot()
ents = [c for c in root if c.tag == "tile_entry"]
names = {}      # tile -> [short enum names]
for n, e in enumerate(ents, start=1):
    cat = e.get("category")
    if cat not in ("roof_slopes", "roof_caps", "roof_tops", "ceiling"):
        continue
    for t in e:
        short = (t.get("enum").replace("Slope", "s").replace("Cap", "c").replace("Peak", "pk")
                 .replace("Rise", "R").replace("Fall", "F").replace("Point", "pt").replace("OnePt5", "1p5")
                 .replace("TwoPt5", "2p5").replace("Pt5", "p5").replace("Shallow", "sh"))
        names.setdefault(tile_name(t.get("tile")), []).append(short)
cx = (ORIGIN + bx.LOT_X) // 256
sq, levels = load(f"{H}/bx/{case}/lots", cx, 0)
print(f"{case}: level {z} of {levels}, region x {x0}..{x0 + w - 1}, y {y0}..{y0 + h - 1}  (c = ceiling)")
for y in range(y0, y0 + h):
    row = []
    for x in range(x0, x0 + w):
        st = sq.get((ORIGIN + bx.LOT_X + x - cx * 256, bx.LOT_Y + y, z), [])
        toks = []
        for t in st:
            if t.startswith("ceilings"):
                toks.append("c")
            elif t in names:
                toks.append("|".join(names[t][:2]) + ("+" if len(names[t]) > 2 else ""))
            elif t.startswith(("roofs", "walls_exterior_roofs", "roofs_30")):
                toks.append("?" + t.rsplit("_", 1)[1])
        row.append(" ".join(toks) or ".")
    print(f"{y:3} " + " ".join(r.ljust(11) for r in row))
