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

from knoxbuild.layout import STAIR_RUN, build_building, roof_rects  # noqa: E402

KINDS = [None, None, "apartment", "apartment", "shop", "school", "civic",
         "church", "medical", "restaurant"]


def door_pair(storey, door):
    x, y, d = door
    if d == "W" and 0 < x < storey.width:
        return storey.grid[y][x - 1], storey.grid[y][x]
    if d == "N" and 0 < y < storey.height:
        return storey.grid[y - 1][x], storey.grid[y][x]
    return None


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


def audit(building, kind):
    problems = Counter()
    for lvl, s in enumerate(building.storeys):
        n = len(s.rooms)
        adj = {i: set() for i in range(1, n + 1)}
        fronts = Counter()
        for door in s.doors:
            pair = door_pair(s, door)
            if not pair or not all(pair) or pair[0] == pair[1]:
                continue
            a, b = pair
            adj[a].add(b)
            adj[b].add(a)
            ua, ub = s.rooms[a - 1].unit, s.rooms[b - 1].unit
            if ua and ub and ua != ub:
                problems["door between two flats"] += 1
            elif ua != ub:
                fronts[ua or ub] += 1
        lit = {s.grid[fy][fx] for role, fx, fy, _o in s.furniture if role == "switch"}
        if any(i not in lit for i in range(1, n + 1)):
            problems["room with no light switch"] += 1
        if n:
            seen, stack = {1}, [1]
            while stack:
                cur = stack.pop()
                for nx in adj[cur] - seen:
                    seen.add(nx)
                    stack.append(nx)
            if len(seen) != n:
                problems["room with no way in"] += 1
        if kind == "apartment" and any(r.unit == 0 for r in s.rooms):
            for unit in {r.unit for r in s.rooms if r.unit}:
                if fronts[unit] == 0:
                    problems["flat with no front door"] += 1
                elif fronts[unit] > 1:
                    problems["flat with several front doors"] += 1
        if lvl == 0:
            outside = [d for d in s.doors if door_pair(s, d) is None or
                       0 in (door_pair(s, d) or (0,))]
            if not outside:
                problems["no way in from outside"] += 1
        if lvl > 0 and any(0 in (door_pair(s, d) or (0,)) for d in s.doors):
            problems["outside door on an upper floor"] += 1
        # Roof: covers exactly the top storey's footprint, no more.
        if lvl == len(building.storeys) - 1:
            covered = set()
            for x0, y0, rw, rh, _caps in roof_rects(s.grid):
                for y in range(y0, y0 + rh):
                    for x in range(x0, x0 + rw):
                        if (x, y) in covered:
                            problems["roofs overlapping"] += 1
                        covered.add((x, y))
            inside = {(x, y) for y in range(s.height) for x in range(s.width)
                      if s.grid[y][x]}
            if covered - inside:
                problems["roof over open ground"] += 1
            if inside - covered:
                problems["building with a hole in its roof"] += 1
    for lvl, (x, y, d) in enumerate(building.stairs):
        dx, dy = (0, 1) if d == "N" else (1, 0)
        run = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
        for s in (building.storeys[lvl], building.storeys[lvl + 1]):
            rooms = {s.grid[ry][rx] if 0 <= rx < s.width and 0 <= ry < s.height
                     else 0 for rx, ry in run}
            if len(rooms) != 1 or 0 in rooms:
                problems["stairs crossing a wall"] += 1
                break
        blocked = {(x + dx * i, y + dy * i) for i in range(STAIR_RUN)}
        for s in (building.storeys[lvl], building.storeys[lvl + 1]):
            for role, fx, fy, _o in s.furniture:
                if (fx, fy) in blocked:
                    problems["furniture on the stairs"] += 1
    return problems


def main(argv):
    count = int(argv[1]) if len(argv) > 1 else 400
    rng = random.Random(4242)
    totals = Counter()
    failed = Counter()
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
        levels = rng.randint(1, 5)
        b = build_building(w, h, levels=levels, seed=i, kind=kind, mask=mask,
                           commercial=kind not in (None, "apartment"))
        found = audit(b, kind)
        label = kind or "house"
        totals[label] += 1
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
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
