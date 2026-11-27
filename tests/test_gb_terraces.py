"""British terraces and semis: houses, not flats, and cut at a terraced
house's width (docs/REGIONAL_PROFILES.md, GB step 5)."""
import unittest

import numpy as np

from knoxbuild.build import row_units
from knoxbuild.footprint import place
from knoxbuild.regional import british_house

GRID = np.zeros((200, 200), dtype=bool)


def footprint(w: int, h: int):
    ring = [(10.0, 10.0), (10.0 + w, 10.0), (10.0 + w, 10.0 + h),
            (10.0, 10.0 + h), (10.0, 10.0)]
    fp, reason = place(ring, GRID.copy(), max_side=1e9)
    assert fp is not None, reason
    return fp


class BritishHouse(unittest.TestCase):
    def test_residential_and_terrace_are_houses_in_britain(self):
        self.assertTrue(british_house("apartment", "residential", 60, None))
        self.assertTrue(british_house("apartment", "terrace", 180, None))

    def test_big_or_tall_ones_stay_flats(self):
        self.assertFalse(british_house("apartment", "residential", 400, None))
        self.assertFalse(british_house("apartment", "residential", 60, 3))

    def test_tagged_flats_and_other_kinds_are_left_alone(self):
        self.assertFalse(british_house("apartment", "apartments", 60, None))
        self.assertFalse(british_house("shop", "residential", 60, None))


class TerraceWidths(unittest.TestCase):
    def test_a_british_terrace_is_cut_at_a_terraced_houses_width(self):
        fp = footprint(33, 9)
        self.assertEqual(len(row_units(fp, None, "terrace", 0, 1.0)), 4)
        self.assertEqual(len(row_units(fp, None, "terrace", 0, 1.0, region="gb")), 6)

    def test_a_british_semi_mapped_as_one_outline_is_two_houses(self):
        fp = footprint(12, 8)
        self.assertEqual(len(row_units(fp, None, "semidetached_house", 0, 1.0)), 1)
        self.assertEqual(len(row_units(fp, None, "semidetached_house", 0, 1.0,
                                       region="gb")), 2)

    def test_a_detached_house_stays_whole(self):
        fp = footprint(12, 8)
        self.assertEqual(len(row_units(fp, None, "yes", 0, 1.0, region="gb")), 1)

    def test_shops_keep_their_frontage(self):
        fp = footprint(39, 12)
        self.assertEqual(len(row_units(fp, "shop", "retail", 0, 1.0, region="gb")),
                         len(row_units(fp, "shop", "retail", 0, 1.0)))


if __name__ == "__main__":
    unittest.main()
