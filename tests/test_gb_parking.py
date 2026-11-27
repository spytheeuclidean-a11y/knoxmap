"""British garages and parking: lock-up rows, cars on the street
(docs/REGIONAL_PROFILES.md, GB step 8)."""
import unittest

import numpy as np

from knoxbuild.build import row_units
from knoxbuild.footprint import place
from knoxbuild.zones_detect import kerbside_rate

GRID = np.zeros((200, 200), dtype=bool)


def footprint(w: int, h: int):
    ring = [(10.0, 10.0), (10.0 + w, 10.0), (10.0 + w, 10.0 + h),
            (10.0, 10.0 + h), (10.0, 10.0)]
    fp, reason = place(ring, GRID.copy(), max_side=1e9)
    assert fp is not None, reason
    return fp


class LockUps(unittest.TestCase):
    def test_a_british_row_of_garages_is_lock_ups(self):
        fp = footprint(20, 6)
        self.assertEqual(len(row_units(fp, "garage", "garages", 0, 1.0, region="gb")), 4)
        self.assertEqual(len(row_units(fp, "garage", "garages", 0, 1.0)), 1)

    def test_a_single_garage_stays_whole(self):
        self.assertEqual(len(row_units(footprint(10, 6), "garage", "garage", 0, 1.0,
                                       region="gb")), 1)
        self.assertEqual(len(row_units(footprint(10, 6), "garage", "garages", 0, 1.0,
                                       region="gb")), 2)
        self.assertEqual(len(row_units(footprint(7, 6), "garage", "garages", 0, 1.0,
                                       region="gb")), 1)


class Kerbside(unittest.TestCase):
    def test_british_residential_streets_are_lined_with_cars(self):
        for tier in (3, 4):
            self.assertGreater(kerbside_rate(tier, "gb"), kerbside_rate(tier, None))
        self.assertGreaterEqual(kerbside_rate(3, "gb"), 0.8)

    def test_main_roads_and_other_maps_are_unchanged(self):
        for tier in (1, 2, 5, 6, 7, 8):
            self.assertEqual(kerbside_rate(tier, "gb"), kerbside_rate(tier, None))
        self.assertEqual(kerbside_rate(3, None), 0.55)
        self.assertEqual(kerbside_rate(None, None), 0.45)


if __name__ == "__main__":
    unittest.main()
