"""Big houses keep a kitchen, rooms are not stuffed, restaurants keep a counter,
and the Workshop-facing audit checks hold."""
import os
import random
import statistics
import sys
import unittest
from collections import Counter

from knoxbuild import interiors as I
from knoxbuild import layout as L

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
from audit_layouts import audit  # noqa: E402


class BigHouses(unittest.TestCase):
    def test_a_big_house_has_somewhere_to_cook(self):
        have = 0
        for seed in range(30):
            b = L.build_building(20 + seed % 5, 18 + seed % 4, levels=2, seed=seed)
            kinds = {r.kind for r in b.storeys[0].rooms}
            have += bool(kinds & {"kitchen", "openplan"})
        self.assertGreaterEqual(have, 27, have)


class Clutter(unittest.TestCase):
    def test_a_room_is_not_mostly_furniture(self):
        fills = {"bedroom": [], "hall": []}
        for seed in range(40):
            b = L.build_building(10 + seed % 9, 9 + seed % 7, levels=2, seed=seed)
            for s in b.storeys:
                floor = Counter(v for row in s.grid for v in row if v)
                used = Counter()
                for role, fx, fy, o in s.furniture:
                    if L._blocks(role):
                        for x, y in L._tiles_under(role, fx, fy, o):
                            if 0 <= x < s.width and 0 <= y < s.height and s.grid[y][x]:
                                used[s.grid[y][x]] += 1
                for i, r in enumerate(s.rooms, 1):
                    if r.kind in fills and not r.is_core:
                        fills[r.kind].append(used[i] / floor[i])
        self.assertLessEqual(statistics.median(fills["bedroom"]), 0.45)
        self.assertLessEqual(statistics.median(fills["hall"]), 0.32)


class Restaurants(unittest.TestCase):
    def test_a_big_eatery_has_its_counter(self):
        roles = {r for v in I.BACK_COUNTERS.values() for r in v}
        big = have = 0
        rng = random.Random(5)
        for seed in range(40):
            b = L.build_building(rng.randint(16, 36), rng.randint(12, 26), levels=1,
                                 seed=seed, kind="restaurant", commercial=True)
            s = b.storeys[0]
            for idx, r in enumerate(s.rooms, 1):
                if r.kind in I.DINING_ROOMS and r.area >= 60:
                    big += 1
                    have += any(f[0] in roles and s.grid[f[2]][f[1]] == idx
                                for f in s.furniture)
        self.assertGreater(big, 0)
        self.assertGreaterEqual(have, 0.95 * big, (have, big))


class Audit(unittest.TestCase):
    def test_no_window_is_blocked_and_no_door_is_boxed_in(self):
        windows = boxed = 0
        for seed in range(30):
            kind = (None, "apartment", "civic", "medical")[seed % 4]
            b = L.build_building(14 + seed % 12, 12 + seed % 9, levels=1 + seed % 3,
                                 seed=seed, kind=kind, commercial=kind not in (None, "apartment"))
            found = audit(b, kind)
            windows += found.get("window blocked by furniture", 0)
            boxed += found.get("stat:door boxed in", 0)
        self.assertEqual(windows, 0)
        self.assertLessEqual(boxed, 1)


if __name__ == "__main__":
    unittest.main()
