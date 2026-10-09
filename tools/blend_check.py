"""Do our edge blends land on the same squares, with the same overlay kinds, as WorldEd's?

    python tools/blend_check.py <WorldEd lots folder> <width> <height>

The floor tiles WorldEd put on the map are the input, so only the blend rules are
tested; the choice among an overlay's alternative tiles is random, so overlays are
compared by kind (which blend rule's tile set a tile belongs to), not by tile.
WorldEd blends each 300 x 300 map on its own, so the check does the same (seam=300).
"""
from __future__ import annotations

import collections
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild.blends import blend_layers, load_blends  # noqa: E402
from knoxbuild.rules import load_rules  # noqa: E402
from knoxbuild.terrain import Palette  # noqa: E402
from tools.terrain_check import read_level0  # noqa: E402
from tools.terrain_source import ORIGIN_X, rules_path  # noqa: E402


def main(argv: list[str]) -> int:
    global argv_all
    argv_all = argv
    argv = [a for a in argv if not a.startswith("--")]
    if len(argv) != 3:
        print(__doc__)
        return 2
    lots, w, h = argv[0], int(argv[1]), int(argv[2])
    cfg = os.path.dirname(rules_path())
    rules = load_rules(rules_path())
    blends = load_blends(os.path.join(cfg, "Blends.txt"))
    kind_of: dict[str, str] = {}
    for b in blends:
        for t in rules.aliases.get(b.tile, [b.tile]):
            kind_of[t] = f"{b.layer}:{b.tile}"
    pal = Palette()
    floor = np.zeros((h, w), np.int64)
    theirs: dict[tuple[int, int], frozenset] = {}
    cells = sorted({tuple(int(t) for t in f[:-10].split("_")) for f in os.listdir(lots) if f.endswith(".lotheader")})
    for cx, cy in cells:
        for (x, y), stack in read_level0(lots, cx, cy).items():
            wx, wy = cx * 256 + x - ORIGIN_X, cy * 256 + y
            if 0 <= wx < w and 0 <= wy < h and stack:
                floor[wy, wx] = pal.of(stack[0])
                kinds = frozenset(kind_of[t] for t in stack[1:] if t in kind_of)
                if kinds:
                    theirs[(wx, wy)] = kinds
    layers = blend_layers(floor, rules, blends, pal, seed=1, seam=300)
    ours: dict[tuple[int, int], frozenset] = {}
    for layer in layers.values():
        for y, x in zip(*np.nonzero(layer)):
            t = pal.names[layer[y, x]]
            ours[(int(x), int(y))] = ours.get((int(x), int(y)), frozenset()) | {kind_of[t]}
    keys = set(ours) | set(theirs)
    same = sum(1 for k in keys if ours.get(k) == theirs.get(k))
    print(f"squares with an overlay: WorldEd {len(theirs)}, ours {len(ours)}; "
          f"identical overlay kinds on {same} of {len(keys)} of those squares")
    bad = collections.Counter()
    for k in keys:
        if ours.get(k) != theirs.get(k):
            bad[(tuple(sorted(ours.get(k, ()))), tuple(sorted(theirs.get(k, ()))))] += 1
    for (a, b), n in bad.most_common(5):
        print(f"  {n} squares: ours {list(a)} / WorldEd {list(b)}")
    grass = set(rules.aliases["darkgrass"])

    def letter(x, y):
        if not (0 <= x < w and 0 <= y < h) or floor[y, x] == 0:
            return "."
        t = pal.names[floor[y, x]]
        return "G" if t in grass else ("S" if t.startswith("blends_street") else "?")

    shown = 0
    for k in sorted(keys):
        if ours.get(k) != theirs.get(k) and shown < 6 and "--show" in argv_all:
            shown += 1
            x, y = k
            print(f"  square {k}: ours {sorted(ours.get(k, []))} WorldEd {sorted(theirs.get(k, []))}")
            for dy in (-1, 0, 1):
                print("      " + "".join(letter(x + dx, y + dy) for dx in (-1, 0, 1)))
    return 0 if same == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
