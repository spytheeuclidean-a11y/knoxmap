"""Compare buildtiles with WorldEd on every building of a compiled map.

    allcheck.py <map folder under real/> [--worst N] [--show] [--exclude-overlaps]

Overlap exclusion is conservative: another lot's rectangle, including its south/east
wall ring, on a level represented by its TBX. Excluded squares remain unverified.
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bxshow import load
from knoxbuild.buildtiles import level_tiles, parse_tbx

H = os.environ.get("KNOXLOTS_FIXTURES", os.path.dirname(os.path.abspath(__file__)))
ORIGIN = 21000
TERRAIN = ("blends_", "vegetation_foliage", "e_", "d_", "lighting_outdoor", "overlay_grime_floor",
           "fencing_", "street_trafficlines")

folder = sys.argv[1]
proj = f"{H}/real/{folder}" if not os.path.isabs(folder) else folder
name = os.path.basename(proj)
worst_n = int(sys.argv[sys.argv.index("--worst") + 1]) if "--worst" in sys.argv else 5

# the lots of the project, with the cell each one is listed in
lots = []
cell = None
for line in open(f"{proj}/{name}.pzw", encoding="utf-8"):
    m = re.match(r'\s*<cell x="(\d+)" y="(\d+)"', line)
    if m:
        cell = (int(m[1]), int(m[2]))
    m = re.search(r'<lot x="(\d+)" y="(\d+)" level="(\d+)" width="(\d+)" height="(\d+)" map="buildings/([^"]+)\.tbx"', line)
    if m and cell:
        x, y, lv, w, h, tbx = m.groups()
        lots.append((cell[0] * 300 + int(x), cell[1] * 300 + int(y), int(lv), int(w), int(h), tbx))

cells = {}


def world(tx, ty, z):
    cx, cy = (ORIGIN + tx) // 256, ty // 256
    if (cx, cy) not in cells:
        try:
            cells[(cx, cy)] = load(f"{proj}/lots", cx, cy)
        except FileNotFoundError:
            cells[(cx, cy)] = ({}, 0)
    sq, _ = cells[(cx, cy)]
    return sq.get(((ORIGIN + tx) - cx * 256, ty - cy * 256, z), [])


rects = [(x, y, w, h, t) for x, y, lv, w, h, t in lots]
exclude_overlaps = "--exclude-overlaps" in sys.argv
overlap_rects = []
if exclude_overlaps:
    for x, y, lv, w, h, t in lots:
        b = parse_tbx(open(f"{proj}/buildings/{t}.tbx", encoding="utf-8").read())
        overlap_rects.append((x, y, w, h, t, lv, lv + len(b.floors)))


def owned_by_another(x, y, me):
    return any(t != me and rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh, t in rects)


results = []
ambiguous = ambiguous_mismatches = 0
prefix_missing = collections.Counter()
prefix_extra = collections.Counter()
for tx0, ty0, lv, w, h, tbx in lots:
    if any(k in tbx for k in ("fences", "lights", "structures", "bridge", "monument")):
        continue
    try:
        b = parse_tbx(open(f"{proj}/buildings/{tbx}.tbx", encoding="utf-8").read())
    except Exception as e:                      # noqa: BLE001
        results.append((tbx, 0, 0, [f"parse failed: {e}"]))
        continue
    total = same = 0
    examples = []
    for z in range(len(b.floors)):
        pred = level_tiles(b, z)
        for dy in range(-1, b.height + 2):
            for dx in range(-1, b.width + 2):
                inside = 0 <= dx < b.width and 0 <= dy < b.height
                if not inside and owned_by_another(tx0 + dx, ty0 + dy, tbx):
                    continue
                actual = [t for t in world(tx0 + dx, ty0 + dy, z + lv) if not t.startswith(TERRAIN)]
                want = pred.get((dx, dy), [])
                if not actual and not want:
                    continue
                if exclude_overlaps and any(t != tbx and rx <= tx0 + dx <= rx + rw
                                            and ry <= ty0 + dy <= ry + rh and lo <= z + lv < hi
                                            for rx, ry, rw, rh, t, lo, hi in overlap_rects):
                    ambiguous += 1
                    ambiguous_mismatches += actual != want
                    continue
                total += 1
                if actual == want:
                    same += 1
                else:
                    for t in set(actual) - set(want):
                        prefix_missing[t.rsplit("_", 1)[0]] += 1
                    for t in set(want) - set(actual):
                        prefix_extra[t.rsplit("_", 1)[0]] += 1
                    if len(examples) < 3:
                        examples.append((z, dx, dy, want, actual))
    results.append((tbx, same, total, examples))

n = len(results)
perfect = sum(1 for _, s, t, e in results if t and s == t)
sq_same = sum(s for _, s, t, e in results)
sq_total = sum(t for _, s, t, e in results)
print(f"{name}: {n} buildings checked; {perfect} match on every compared square; {sq_same} of {sq_total} squares identical"
      f" ({100 * sq_same / max(sq_total, 1):.2f}%)")
if exclude_overlaps:
    print(f"  excluded {ambiguous} ambiguous lot-overlap comparisons ({ambiguous_mismatches} mismatched)")
print("  WorldEd has, we lack:", dict(prefix_missing.most_common(8)))
print("  we have, WorldEd lacks:", dict(prefix_extra.most_common(8)))
bad = sorted((r for r in results if r[2] and r[1] != r[2]), key=lambda r: r[2] - r[1], reverse=True)
for tbx, s, t, ex in bad[:worst_n]:
    print(f"  {tbx}: {s} of {t}")
    if "--show" in sys.argv:
        for z, dx, dy, want, actual in ex:
            print(f"     level {z} ({dx},{dy})\n        ours    {want}\n        WorldEd {actual}")
