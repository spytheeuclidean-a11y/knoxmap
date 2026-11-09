"""Knoxify smoke test: render a tiny area end-to-end."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# `python tools/pipeline_check.py` from the top of the repository: generator/
# sits one folder above this one.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import osm, renderer

# ~600m x 600m area in Lexington, KY (thematically appropriate for PZ!).
SOUTH, WEST = 38.0400, -84.5050
NORTH, EAST = 38.0454, -84.4984  # rough ~600m both sides

OUT = Path("output/_smoketest")


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    print(f"Querying Overpass for bbox ({SOUTH}, {WEST}) -> ({NORTH}, {EAST})…")
    feats = osm.fetch_features(SOUTH, WEST, NORTH, EAST)
    print(f"  -> {len(feats)} features")
    by_cat: dict[str, int] = {}
    for f in feats:
        c = osm.classify(f.tags) or "_none"
        by_cat[c] = by_cat.get(c, 0) + 1
    print(f"  categories: {sorted(by_cat.items())}")

    print("Rendering…")
    r = renderer.render(feats, SOUTH, WEST, NORTH, EAST,
                        meters_per_tile=1.0,
                        output_dir=str(OUT),
                        map_name="smoketest")
    print(f"  landscape: {r.landscape_path} ({r.width}x{r.height})")
    print(f"  cells:     {r.cells_x} x {r.cells_y}")

    # Sanity checks.
    from PIL import Image
    land = Image.open(r.landscape_path)
    assert land.size == (r.width, r.height)
    assert r.width % 300 == 0 and r.height % 300 == 0
    colors = {p for row in range(0, r.height, 20)
                for p in land.crop((0, row, r.width, row+1)).getdata()}
    print(f"  unique landscape colors sampled: {len(colors)}")
    assert (90, 100, 35) in colors, "dark grass (default) missing"
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
