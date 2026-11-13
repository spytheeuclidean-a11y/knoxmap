"""Which furniture tile comes first in WorldEd's stack?  Pairwise precedence by (layer, orient)."""
import collections
import os
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bxshow import load
from knoxbuild.buildtiles import parse_tbx

H = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 21000
variant, lx, ly, name = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
b = parse_tbx(open(f"{H}/{variant}/buildings/{name}.tbx", encoding="utf-8").read())
cx, cy = (ORIGIN + lx) // 256, ly // 256
sq, levels = load(f"{H}/{variant}/lots", cx, cy)
before = collections.Counter()
examples = {}
for z, fl in enumerate(b.floors[:levels]):
    placed = collections.defaultdict(list)           # square -> [(category, tile, file order)]
    for n, o in enumerate(fl.objects):
        if o.get("type") != "furniture":
            continue
        d = b.furniture[int(o["FurnitureTiles"])]
        for dx, dy, tile in d["orients"].get(o["orient"], []):
            placed[(int(o["x"]) + dx, int(o["y"]) + dy)].append(((d["layer"] or "-", o["orient"]), tile, n))
    for (x, y), items in placed.items():
        if len(items) < 2:
            continue
        actual = sq.get((ORIGIN + lx + x - cx * 256, ly + y - cy * 256, z), [])
        pos = {}
        for cat, tile, n in items:
            if tile in actual:
                pos[(cat, tile, n)] = actual.index(tile)
        keys = sorted(pos, key=pos.get)
        for i, a in enumerate(keys):
            for c in keys[i + 1:]:
                if a[0] != c[0]:
                    before[(a[0], c[0])] += 1
                    examples.setdefault((a[0], c[0]), (z, x, y, a[1], c[1]))
cats = sorted({c for pair in before for c in pair})
print("A before B (counts); a rule needs the reverse to be 0")
for (a, c), n in sorted(before.items()):
    rev = before.get((c, a), 0)
    flag = "" if rev == 0 else f"   <-- conflict, reverse {rev}"
    print(f"  {a} before {c}: {n}{flag}")
