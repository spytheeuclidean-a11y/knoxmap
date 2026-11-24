import math
import unittest

import numpy as np

from knoxbuild.footprint import place


def turned(cx, cy, w, h, deg):
    a = math.radians(deg)
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append((cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)))
    return pts


def run(poly, **kw):
    occ = np.zeros((80, 80), dtype=bool)
    fp, why = place(poly, occ, **kw)
    return fp, why


class SmartHouseBox(unittest.TestCase):
    def test_a_diagonal_house_becomes_a_box(self):
        fp, _ = run(turned(40, 40, 16, 10, 33), alignment="smart", house_box_tiles=400)
        self.assertTrue(fp.mask.all())
        self.assertEqual(sorted((fp.width, fp.height)), [10, 16])

    def test_without_the_limit_it_keeps_its_staircase(self):
        fp, _ = run(turned(40, 40, 16, 10, 33), alignment="smart")
        self.assertFalse(fp.mask.all())

    def test_a_big_building_keeps_what_it_was_drawn_as(self):
        fp, _ = run(turned(40, 40, 30, 20, 33), alignment="smart", house_box_tiles=400)
        self.assertFalse(fp.mask.all())

    def test_a_courtyard_house_is_not_filled_in(self):
        u = [(20, 20), (40, 20), (40, 36), (36, 36), (36, 23), (24, 23), (24, 36), (20, 36)]
        fp, _ = run(u, alignment="smart", house_box_tiles=400)
        self.assertTrue(fp is None or not fp.mask.all())     # refused as cut, never filled in

    def test_real_keeps_everything(self):
        fp, _ = run(turned(40, 40, 16, 10, 33), alignment="real", house_box_tiles=400)
        self.assertFalse(fp.mask.all())


if __name__ == "__main__":
    unittest.main()
