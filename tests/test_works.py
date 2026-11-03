"""Works yards (knoxbuild/works.py): tarmac round a works, a drive to the
road, a dumpster and clutter by the walls, grass beyond."""
import unittest
from collections import deque

import numpy as np

from generator import pz_colors as C
from knoxbuild.works import YARD_EDGE, yard_width
from tests.test_yards import SIZE, _paint

X, Y = 16, 20                 # the works, SIZE x SIZE, door in its north wall
DUMPSTER = {C.DUMPSTER_BLUE_S0, C.DUMPSTER_BLUE_S1, C.DUMPSTER_BLUE_E0, C.DUMPSTER_BLUE_E1,
            C.DUMPSTER_ORANGE_S0, C.DUMPSTER_ORANGE_S1, C.DUMPSTER_ORANGE_E0,
            C.DUMPSTER_ORANGE_E1}
OBJECTS = DUMPSTER | {C.WORKS_PALLET, C.WORKS_BRICKS, C.WORKS_DRUM, C.WORKS_BARREL,
                      C.WORKS_CRATE, C.WORKS_TIRES, C.LAMP_N, C.LAMP_S}


def _colours(img):
    return {tuple(int(v) for v in px) for px in img.reshape(-1, 3)}


class WorksYards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        works = [("industrial", X, Y)]
        cls.ground = _paint(50, 50, works)
        cls.veg = _paint(50, 50, works, veg=True)
        cls.r = yard_width(SIZE, SIZE)

    def ring(self, x, y):
        return max(X - x, x - (X + SIZE - 1), Y - y, y - (Y + SIZE - 1), 0)

    def test_the_yard_is_tarmac_and_the_land_beyond_is_grass(self):
        for y in range(2, 50):
            for x in range(50):
                k = self.ring(x, y)
                if 1 <= k <= self.r:
                    self.assertNotEqual(tuple(self.ground[y, x]), C.MEDIUM_GRASS, (x, y))
                elif k > self.r + YARD_EDGE + 1 and abs(x - (X + 3)) > 3:
                    # (the drive runs north to the pavement past the door)
                    self.assertEqual(tuple(self.ground[y, x]), C.MEDIUM_GRASS, (x, y))

    def test_a_drive_reaches_the_pavement(self):
        hard = ~np.all(self.ground == C.MEDIUM_GRASS, axis=2)
        start = (X + 3, Y - 1)
        seen, todo = {start}, deque([start])
        while todo:
            x, y = todo.popleft()
            if y < 2:
                return
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= n[0] < 50 and 0 <= n[1] < 50 and n not in seen and hard[n[1], n[0]]:
                    seen.add(n)
                    todo.append(n)
        self.fail("no hard ground from the works' door to the pavement")

    def test_a_dumpster_and_clutter_stand_in_the_yard(self):
        got = _colours(self.veg)
        self.assertTrue(got & DUMPSTER)
        self.assertGreaterEqual(len(got & {C.WORKS_PALLET, C.WORKS_BRICKS, C.WORKS_DRUM,
                                           C.WORKS_BARREL, C.WORKS_CRATE, C.WORKS_TIRES}), 1)

    def test_nothing_stands_at_the_door(self):
        door = (X + 3, Y - 1)
        for x, y in [(door[0], door[1] - k) for k in range(3)] + [(door[0] - 1, door[1]),
                                                                  (door[0] + 1, door[1])]:
            self.assertNotIn(tuple(self.veg[y, x]), OBJECTS, (x, y))

    def test_a_house_gets_no_works_yard(self):
        ground = _paint(50, 50, [("house", X, Y)])
        self.assertEqual(tuple(ground[Y + SIZE + 4, X + 3]), C.MEDIUM_GRASS)


if __name__ == "__main__":
    unittest.main()
