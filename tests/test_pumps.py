"""Petrol station forecourts: pumps on islands, set well back from the shop."""
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild import pumps
from knoxbuild.bitmaps import read_rgb


def forecourt(mpt, side="S", w=18, h=8, size=(120, 90), at=(50, 20)):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "buildings"))
    ground = np.zeros((size[1], size[0], 3), np.uint8)
    ground[:] = C.MEDIUM_GRASS
    ground[size[1] - 6:] = C.MEDIUM_ASPHALT          # a street along the bottom
    Image.fromarray(ground).save(os.path.join(d, "m.bmp"), format="BMP")
    occupied = np.zeros((size[1], size[0]), bool)
    x0, y0 = at
    occupied[y0:y0 + h, x0:x0 + w] = True
    placements, count = pumps.place_pumps(
        d, "m", os.path.join(d, "buildings"), occupied, [(x0, y0, w, h, side)], [],
        metres_per_tile=mpt)
    return read_rgb(os.path.join(d, "m.bmp")), count, placements, (x0, y0, w, h)


class Forecourt(unittest.TestCase):
    def test_islands_stand_off_the_shop(self):
        for mpt in (1.0, 2.0):
            ground, count, placements, (x0, y0, w, h) = forecourt(mpt)
            self.assertGreaterEqual(count, 2)
            rows = np.where((ground == np.array(C.PALE_CONCRETE)).all(axis=2).any(axis=1))[0]
            front = y0 + h + 1                        # the shop's pavement row
            island_rows = [r for r in rows if r > front + 1 and r < 80]
            self.assertTrue(island_rows, "no island was drawn")
            nearest = (min(island_rows) - (y0 + h)) * mpt
            self.assertGreaterEqual(nearest, pumps.PUMP_SETBACK_M - mpt, f"mpt {mpt}")

    def test_the_shop_front_is_paved(self):
        ground, _count, _p, (x0, y0, w, h) = forecourt(2.0)
        row = ground[y0 + h + 1, x0:x0 + w]
        self.assertTrue((row == np.array(C.PALE_CONCRETE)).all(axis=1).sum() >= w // 2)

    def test_each_island_has_a_roof_on_posts(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "buildings"))
        ground = np.zeros((90, 120, 3), np.uint8)
        ground[:] = C.MEDIUM_GRASS
        Image.fromarray(ground).save(os.path.join(d, "m.bmp"), format="BMP")
        occupied = np.zeros((90, 120), bool)
        occupied[20:28, 50:68] = True
        pumps.place_pumps(d, "m", os.path.join(d, "buildings"), occupied,
                          [(50, 20, 18, 8, "S")], [], metres_per_tile=2.0)
        text = "".join(open(os.path.join(d, "buildings", f), encoding="utf-8").read()
                       for f in os.listdir(os.path.join(d, "buildings")))
        self.assertIn(pumps.CANOPY_ROOF, text)
        self.assertIn(pumps.CANOPY_POST, text)
        self.assertEqual(text.count("<floor>"), 2)        # the roof is a floor up

    def test_deep_forecourt_gets_two_islands(self):
        for mpt in (1.0, 2.0):
            rows = pumps.island_rows(pumps.full_depth(mpt), mpt)
            self.assertEqual(len(rows), 2)
            self.assertGreaterEqual(rows[1] - rows[0], pumps.MIN_LANE_TILES)
        self.assertEqual(len(pumps.island_rows(5, 2.0)), 1)


if __name__ == "__main__":
    unittest.main()
