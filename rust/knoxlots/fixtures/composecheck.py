"""Compare composed lots, including overlaps, with WorldEd.

    composecheck.py <map folder> [--show]

Terrain prefixes are omitted; remaining background differences stay visible.
"""
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
from knoxbuild.buildtiles import compose_lots, level_tiles, parse_tbx
from bxshow import load

TERRAIN = ("blends_", "vegetation_foliage", "e_", "d_", "lighting_outdoor",
           "overlay_grime_floor", "fencing_", "street_trafficlines")
UTILITY = ("fences", "lights", "structures", "bridge", "monument")


def compare_project(project):
    project = Path(project)
    root = ET.parse(project / (project.name + ".pzw")).getroot()
    placements, coverage, contributors = [], set(), {}
    buildings = 0
    for cell in root.iter("cell"):
        cx, cy = int(cell.get("x")), int(cell.get("y"))
        for lot in cell.findall("lot"):
            path = project / lot.get("map")
            b = parse_tbx(path.read_text(encoding="utf-8"))
            tx, ty = cx * 300 + int(lot.get("x")), cy * 300 + int(lot.get("y"))
            base = int(lot.get("level"))
            placements.append((b, tx, ty, base))
            utility = any(word in path.stem for word in UTILITY)
            if not utility:
                buildings += 1
            for z in range(len(b.floors)):
                for (x, y), tiles in level_tiles(b, z).items():
                    if any(not t.startswith(TERRAIN) for t in tiles):
                        contributors.setdefault((tx + x, ty + y, base + z), set()).add(len(placements))
                        coverage.add((tx + x, ty + y, base + z))
                if not utility:
                    coverage.update((tx + x, ty + y, base + z) for x in range(-1, b.width + 2)
                                    for y in range(-1, b.height + 2))
    predicted = compose_lots(placements)
    cells, total, same, overlaps, overlap_misses, misses = {}, 0, 0, 0, 0, []
    for pos in sorted(coverage):
        tx, ty, z = pos
        cx, cy = (21000 + tx) // 256, ty // 256
        if (cx, cy) not in cells:
            cells[cx, cy] = load(str(project / "lots"), cx, cy)[0]
        actual = [t for t in cells[cx, cy].get(((21000 + tx) % 256, ty % 256, z), []) if not t.startswith(TERRAIN)]
        want = [t for t in predicted.get(pos, []) if not t.startswith(TERRAIN)]
        if not actual and not want:
            continue
        total += 1
        overlap = len(contributors.get(pos, ())) > 1
        overlaps += overlap
        same += actual == want
        if actual != want:
            overlap_misses += overlap
            misses.append((pos, want, actual))
    return dict(buildings=buildings, same=same, total=total,
                overlaps=overlaps, overlap_misses=overlap_misses, misses=misses)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    result = compare_project(argv[0])
    print(f"{result['buildings']} buildings composed: {result['same']} of {result['total']} unique squares identical; "
          f"{len(result['misses'])} mismatches")
    print(f"{result['overlaps']} overlapping tile squares checked; {result['overlap_misses']} mismatches")
    if "--show" in argv:
        for pos, want, actual in result['misses'][:10]:
            print(pos, "ours", want, "WorldEd", actual)
    return int(bool(result['misses']))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
