"""Compare buildtiles' prediction with WorldEd's output for a hand-made building.

    bxcheck.py <case> [...]
"""
import os
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bxshow import load
from knoxbuild.buildtiles import level_tiles, parse_tbx

H = os.environ.get("KNOXLOTS_FIXTURES", os.path.dirname(os.path.abspath(__file__)))
LOT_X, LOT_Y = 40, 40
ORIGIN = 21000

for case in sys.argv[1:]:
    b = parse_tbx(open(f"{H}/bx/{case}/buildings/{case}.tbx", encoding="utf-8").read())
    cx = (ORIGIN + LOT_X) // 256
    sq, levels = load(f"{H}/bx/{case}/lots", cx, 0)
    total = same = 0
    shown = 0
    for z in range(len(b.floors)):
        pred = level_tiles(b, z)
        # compare over the building and its ring of outside squares (and a margin to catch extras)
        for dy in range(-2, b.height + 3):
            for dx in range(-2, b.width + 3):
                actual = sq.get((ORIGIN + LOT_X + dx - cx * 256, LOT_Y + dy, z), [])
                if z == 0 and actual and actual[0].startswith("blends_natural"):
                    actual = actual[1:]
                want = pred.get((dx, dy), [])
                if actual or want:
                    total += 1
                    if actual == want:
                        same += 1
                    elif shown < 6:
                        shown += 1
                        print(f"   level {z} square ({dx},{dy}): ours {want}\n                        WorldEd {actual}")
    print(f"{case}: {same} of {total} squares identical")
