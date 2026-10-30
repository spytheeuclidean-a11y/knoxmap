"""Woods in open fields."""
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering.vegetation import _paint_groves



class Proj:
    meters_per_tile = 2.0


def _field(size=900):
    return (Image.new("RGB", (size, size), C.MEDIUM_GRASS),
            Image.new("RGB", (size, size), C.VEG_NOTHING))


def _share(veg):
    return float((np.array(veg).sum(axis=2) > 0).mean())


class Groves(unittest.TestCase):
    def test_a_share_of_open_ground_is_wood(self):
        land, veg = _field()
        _paint_groves(veg, land, Proj(), 1.0)
        self.assertTrue(0.08 < _share(veg) < 0.22, _share(veg))

    def test_density_scales_it_and_zero_is_none(self):
        shares = []
        for d in (0.0, 0.5, 1.0, 2.0):
            land, veg = _field()
            _paint_groves(veg, land, Proj(), d)
            shares.append(_share(veg))
        self.assertEqual(shares[0], 0)
        self.assertEqual(shares, sorted(shares))

    def test_nothing_on_roads_or_water(self):
        land, veg = _field(400)
        land.paste(C.MEDIUM_ASPHALT, (0, 0, 400, 400))
        self.assertEqual(_paint_groves(veg, land, Proj(), 2.0), 0)
        self.assertEqual(_share(veg), 0)

    def test_grass_under_a_wood_is_dark(self):
        land, veg = _field()
        _paint_groves(veg, land, Proj(), 1.0)
        trees = np.array(veg).sum(axis=2) > 0
        ground = np.array(land)
        self.assertTrue((ground[trees] == np.array(C.DARK_GRASS)).all())


if __name__ == "__main__":
    unittest.main()
