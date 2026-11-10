"""Stress-test the floor-plan generator for plans that cannot work in game.

    python tools/audit_layouts.py [count]

Builds many buildings of every kind, rectangular and irregular, and checks the
things a player notices first: a room with no way in, a door between two
people's flats, a flat with no front door or several, a flight of stairs with
a wall across it, a building with no way in from outside, and roofs hanging
over open ground. Exits non-zero if anything fails, so it can gate a change.
"""
from __future__ import annotations

import math
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from knoxbuild import basements  # noqa: E402
from knoxbuild.settings import Settings  # noqa: E402
from knoxbuild.layout import build_building  # noqa: E402

# Doors with no free tile to step onto, and rooms entered only through a
# bathroom, each as a share of what could have them. Measured over 200
# buildings: 1 door in 23,000, and 75 rooms in 7,800 (apartment bedrooms, mostly,
# whose only other wall is the outside). Since such a room swaps places with
# its bathroom (layout._swap_through_bathrooms), 42 in 22,270 over 400. A rise
# means furnishing or the door tree has started boxing people in.
DOORS_BOXED_IN_BUDGET = 0.0005
ROOMS_VIA_BATHROOM_BUDGET = 0.005

# Doors left on a corner, as a share of all doors. It was 1.69% before they
# were moved off; anything near that means the moving has stopped working.
DOORS_ON_CORNERS_BUDGET = 0.2

KINDS = [None, None, "apartment", "apartment", "shop", "school", "civic",
         "church", "medical", "restaurant", "shed",
         "police", "library", "fire", "military", "industrial",
         "castle", "stadium", "mall"]


# The checks themselves live in knoxbuild/audit.py, where Build runs them over
# every building it lays out; these names are how the tests and the selftest
# reach them.
from knoxbuild.audit import audit, basement_unreached, door_pair  # noqa: E402,F401


def rotated_mask(rng):
    """A rectangle turned off the grid and rasterised by tile centres."""
    import numpy as np
    from knoxbuild.footprint import place
    angle = math.radians(rng.uniform(12, 45))
    a, b = rng.uniform(10, 34), rng.uniform(8, 22)
    pts = [(a * math.cos(angle) * sx - b * math.sin(angle) * sy + 60,
            a * math.sin(angle) * sx + b * math.cos(angle) * sy + 60)
           for sx, sy in ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5))]
    fp, _ = place(pts, np.zeros((140, 140), dtype=bool))
    return fp


def irregular_mask(w, h, rng):
    """An L, a notch, or a courtyard-free T - the shapes real footprints take."""
    mask = [[True] * w for _ in range(h)]
    shape = rng.choice(["L", "notch", "T"])
    if shape == "L":
        cw, ch = rng.randint(w // 3, w // 2), rng.randint(h // 3, h // 2)
        for y in range(ch):
            for x in range(w - cw, w):
                mask[y][x] = False
    elif shape == "notch":
        cw = rng.randint(3, max(3, w // 3))
        x0 = rng.randint(1, max(1, w - cw - 1))
        for y in range(rng.randint(2, max(2, h // 3))):
            for x in range(x0, min(w, x0 + cw)):
                mask[y][x] = False
    else:
        cw = rng.randint(w // 4, w // 3)
        for y in range(rng.randint(h // 3, h // 2)):
            for x in list(range(cw)) + list(range(w - cw, w)):
                mask[y][x] = False
    return mask


def main(argv):
    count = int(argv[1]) if len(argv) > 1 else 400
    rng = random.Random(4242)
    totals = Counter()
    failed = Counter()
    stats = Counter()
    windows = []
    for i in range(count):
        kind = KINDS[i % len(KINDS)]
        w, h = rng.randint(9, 40), rng.randint(9, 40)
        roll = rng.random()
        mask = None
        if roll < 0.3:
            mask = irregular_mask(w, h, rng)
        elif roll < 0.65:
            fp = rotated_mask(rng)
            if fp is not None:
                w, h, mask = fp.width, fp.height, fp.mask_list()
        levels = rng.choice((1, 2, 3, 4, 5, 6, 8, 12))
        b = build_building(w, h, levels=levels, seed=i, kind=kind, mask=mask,
                           commercial=kind not in (None, "apartment"))
        found = audit(b, kind)
        # A basement under it, where its kind has one (the cellar of every
        # house here, not a share of them).
        area = sum(1 for row in b.storeys[0].grid for v in row if v)
        t = basements.tier(kind or "house", area, 0)
        if t is not None and t != "installation":
            ground = np.array([[bool(v) for v in row] for row in b.storeys[0].grid])
            spec = basements.BasementSpec(t, kind or "house", basements.levels_for(t, area, 0, 8),
                                          0, 0, basements._inside(ground))
            below = basements.plan_basement(b, spec, i, Settings())
            if below is not None:
                lost, rooms = basement_unreached(below)
                stats["stat:basement rooms unreached"] += lost
                stats["stat:basement rooms"] += rooms
                stats["stat:basements"] += 1
        label = kind or "house"
        totals[label] += 1
        for k in [k for k in found if k.startswith("stat:")]:
            stats[k] += found.pop(k)
        if found:
            failed[label] += 1
            for k, v in found.items():
                failed["  " + k] += v
        perim = sum(1 for row in b.storeys[0].grid for v in row if v)
        windows.append(len(b.storeys[0].windows) / max(1, perim ** 0.5))

    print(f"buildings audited: {count}")
    for label in sorted(totals):
        print(f"  {label:10} {totals[label]:4}  failing: {failed[label]}")
    problems = {k: v for k, v in failed.items() if k.startswith("  ")}
    if problems:
        print("problems:")
        for k, v in sorted(problems.items(), key=lambda kv: -kv[1]):
            print(f"{k:40} {v}")
    print(f"windows per sqrt(floor area), ground floor, mean: "
          f"{sum(windows) / len(windows):.2f}")
    # A door on a corner is drawn as neither door nor wall. It only stays on
    # one when every clean wall it could move to would shut a room off, so a
    # few is right and a lot means the moving has stopped working.
    stuck = 100.0 * stats["stat:on a corner"] / max(1, stats["stat:doors"])
    print(f"doors drawn as wall, on a corner: {stats['stat:on a corner']} of "
          f"{stats['stat:doors']} ({stuck:.3f}%)")
    boxed = 100.0 * stats["stat:door boxed in"] / max(1, stats["stat:door fronts"])
    via = 100.0 * stats["stat:room through a bathroom"] / max(1, stats["stat:rooms"])
    print(f"door fronts boxed in: {stats['stat:door boxed in']} of "
          f"{stats['stat:door fronts']} ({boxed:.3f}%)")
    print(f"rooms entered only through a bathroom: "
          f"{stats['stat:room through a bathroom']} of {stats['stat:rooms']} ({via:.2f}%)")
    print(f"basement rooms with no way in: {stats['stat:basement rooms unreached']} of "
          f"{stats['stat:basement rooms']} ({stats['stat:basements']} basements)")
    over = (stats["stat:basement rooms unreached"] > 0 or stuck > DOORS_ON_CORNERS_BUDGET or boxed > 100 * DOORS_BOXED_IN_BUDGET
            or via > 100 * ROOMS_VIA_BATHROOM_BUDGET)
    return 1 if problems or over else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
