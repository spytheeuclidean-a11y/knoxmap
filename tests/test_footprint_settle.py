import unittest

import numpy as np

from knoxbuild import footprint
from knoxbuild.why import FIX, SHORT, WHY


def rect(w, h):
    return np.ones((h, w), dtype=bool)


class Settle(unittest.TestCase):
    def test_a_whole_rectangle_is_left_alone(self):
        m, x, y, why = footprint._settle(rect(8, 6), 3, 4, 48)
        self.assertEqual((why, x, y), ("ok", 3, 4))
        self.assertTrue(m.all())

    def test_a_building_cut_in_half_is_refused(self):
        m = rect(12, 8)
        m[:, 5:] = False                       # a road took more than half
        self.assertEqual(footprint._settle(m, 0, 0, 96)[3], "cut")

    def test_only_the_biggest_piece_is_kept(self):
        m = rect(12, 8)
        m[:, 8:10] = False                     # a 2-wide road through a long house
        m, x, y, why = footprint._settle(m, 0, 0, 96)
        self.assertEqual(why, "ok")
        self.assertEqual(m.shape, (8, 8))      # the wing past the road is gone
        self.assertTrue(m.all())

    def test_spurs_are_trimmed(self):
        m = rect(10, 8)
        m[0, :] = False
        m[0, 4] = True                         # a one-tile needle on the roof line
        m, x, y, why = footprint._settle(m, 0, 0, 80)
        self.assertEqual((why, y), ("ok", 1))
        self.assertTrue(m.all())

    def test_a_shape_no_building_has_is_refused(self):
        m = rect(16, 16)
        m[3:, 3:13] = False                    # a comb: a thin frame round a hole
        self.assertEqual(footprint._settle(m, 0, 0, 200)[3], "cut")

    def test_every_reason_is_explained(self):
        for table in (WHY, FIX, SHORT):
            self.assertIn("cut", table)


class PlaceCut(unittest.TestCase):
    def _place(self, road_cols):
        occupied = np.zeros((40, 60), dtype=bool)
        avoid = np.zeros((40, 60), dtype=np.uint8)
        avoid[:, road_cols] = 3
        px = [(10, 10), (40, 10), (40, 26), (10, 26)]
        return footprint.place(px, occupied, avoid=avoid)

    def test_a_road_through_the_middle_moves_or_refuses_the_building(self):
        fp, why = self._place(slice(22, 26))
        if fp is not None:                     # moved clear of it, or trimmed to one side
            self.assertGreaterEqual(int(fp.mask.sum()), 0.55 * 30 * 16)
        else:
            self.assertIn(why, ("cut", "road"))

    def test_no_road_no_change(self):
        fp, why = self._place(slice(55, 56))
        self.assertEqual(why, "ok")
        self.assertTrue(fp.mask.all())


if __name__ == "__main__":
    unittest.main()
