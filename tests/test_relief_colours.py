"""Relief and climate repaint the ground in colours Rules.txt has rules for.

Both passes named DIRT_GRASS and GRAVEL_DIRT, which pz_colors did not define;
the AttributeError was swallowed by the renderer's try/except, so relief and
an arid climate quietly did nothing on every map.
"""
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator import renderer


def colours(img):
    return {tuple(int(v) for v in c)
            for c in np.unique(np.asarray(img).reshape(-1, 3), axis=0)}


class ReliefColours(unittest.TestCase):
    def test_relief_bands_the_ground(self):
        land = Image.new("RGB", (100, 100), C.DARK_GRASS)
        slope = np.tile(np.linspace(0, 200, 100, dtype="float32"), (100, 1))
        renderer._paint_relief_ground(land, slope, (0.0, 200.0))
        got = colours(land)
        self.assertIn(C.GRAVEL_DIRT, got)
        self.assertLessEqual(got, C.LANDSCAPE_COLORS)

    def test_an_arid_climate_dries_the_grass(self):
        land = Image.new("RGB", (10, 10), C.LIGHT_GRASS)
        renderer._paint_climate_ground(land, {"class": "arid"})
        self.assertEqual(colours(land), {C.DIRT_GRASS})


if __name__ == "__main__":
    unittest.main()
