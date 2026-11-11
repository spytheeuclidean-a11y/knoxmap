"""Compare buildtiles with WorldEd on a real KnoxMap building.

    housecheck.py <variant folder> <lot world x> <lot world y> <tbx name>
e.g. housecheck.py exp/house 269 592 house_0000
"""
import collections
import os
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bxshow import load
from knoxbuild.buildtiles import level_tiles, parse_tbx

H = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 21000


def prefix(t):
    parts = t.rsplit("_", 1)
    return parts[0]


variant, lx, ly, name = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
b = parse_tbx(open(f"{H}/{variant}/buildings/{name}.tbx", encoding="utf-8").read())
cx, cy = (ORIGIN + lx) // 256, ly // 256
sq, levels = load(f"{H}/{variant}/lots", cx, cy)
print(f"{name}: {b.width}x{b.height}, {len(b.floors)} floors in the file, {levels} levels in the lots, cell {cx}_{cy}")
for z in range(min(len(b.floors), levels)):
    pred = level_tiles(b, z)
    total = same = 0
    only_actual = collections.Counter()
    only_pred = collections.Counter()
    for dy in range(-1, b.height + 2):
        for dx in range(-1, b.width + 2):
            actual = list(sq.get((ORIGIN + lx + dx - cx * 256, ly + dy - cy * 256, z), []))
            if z == 0 and actual and actual[0].startswith("blends_natural"):
                actual = actual[1:]
            want = pred.get((dx, dy), [])
            if not actual and not want:
                continue
            total += 1
            if actual == want:
                same += 1
            else:
                for t in set(actual) - set(want):
                    only_actual[prefix(t)] += 1
                for t in set(want) - set(actual):
                    only_pred[prefix(t)] += 1
    print(f" level {z}: {same} of {total} squares identical")
    print("    WorldEd has, we lack:", dict(only_actual.most_common(6)))
    print("    we have, WorldEd lacks:", dict(only_pred.most_common(4)))


# ---- examples of squares where we add a wall WorldEd does not ---------------------------
if "--extra" in sys.argv:
    z = 0
    pred = level_tiles(b, z)
    shown = 0
    for dy in range(-1, b.height + 2):
        for dx in range(-1, b.width + 2):
            actual = list(sq.get((ORIGIN + lx + dx - cx * 256, ly + dy - cy * 256, z), []))
            want = pred.get((dx, dy), [])
            extra = [t for t in want if t not in actual and t.startswith("walls_interior_house")]
            if extra and shown < 6:
                shown += 1
                r = lambda x, y: b.floors[z].rooms[y][x] if 0 <= x < b.width and 0 <= y < b.height else 0
                print(f"square ({dx},{dy}) room {r(dx,dy)} west-neighbour {r(dx-1,dy)} north-neighbour {r(dx,dy-1)}")
                print("    ours   ", want)
                print("    WorldEd", actual)


if "--trim" in sys.argv:
    z = 0
    pred = level_tiles(b, z)
    shown = 0
    for dy in range(-1, b.height + 2):
        for dx in range(-1, b.width + 2):
            actual = list(sq.get((ORIGIN + lx + dx - cx * 256, ly + dy - cy * 256, z), []))
            if any(t.startswith("walls_interior_detailing") for t in actual) and shown < 8:
                shown += 1
                rr = lambda x, y: b.floors[z].rooms[y][x] if 0 <= x < b.width and 0 <= y < b.height else 0
                r = rr(dx, dy)
                print(f"square ({dx},{dy}) room {r} W-nb {rr(dx-1,dy)} N-nb {rr(dx,dy-1)}  trim attr {b.rooms[r-1].get('InteriorWallTrim') if r else None}")
                print("    ours   ", pred.get((dx, dy), []))
                print("    WorldEd", actual)


if "--diff" in sys.argv:
    TERRAIN = ("blends_", "vegetation_foliage", "e_", "d_", "lighting_outdoor", "overlay_grime_floor")
    zsel = int(sys.argv[sys.argv.index("--diff") + 1])
    pred = level_tiles(b, zsel)
    shown = 0
    for dy in range(-1, b.height + 2):
        for dx in range(-1, b.width + 2):
            actual = list(sq.get((ORIGIN + lx + dx - cx * 256, ly + dy - cy * 256, zsel), []))
            want = pred.get((dx, dy), [])
            a2 = [t for t in actual if not t.startswith(TERRAIN)]
            if a2 != want and shown < 8:
                shown += 1
                rr = lambda x, y: b.floors[zsel].rooms[y][x] if 0 <= x < b.width and 0 <= y < b.height else 0
                print(f"square ({dx},{dy}) room {rr(dx,dy)} W-nb {rr(dx-1,dy)} N-nb {rr(dx,dy-1)}")
                print("    ours   ", want)
                print("    WorldEd", a2)
