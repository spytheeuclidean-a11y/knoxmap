"""What grows on each WorldCover class, on ground OSM left blank."""
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import landcover_veg as LV


class P:
    meters_per_tile = 1.0


STRIPES = (10, 20, 30, 90, 60)


def setup(owned_all=True):
    grid = np.zeros((200, 250), dtype="uint8")
    for i, code in enumerate(STRIPES):
        grid[:, i * 50:(i + 1) * 50] = code
    owned = np.ones(grid.shape, dtype=bool)
    if not owned_all:
        owned[:100] = False
    land = Image.new("RGB", (250, 200), C.MEDIUM_GRASS)
    veg = Image.new("RGB", (250, 200), C.VEG_NOTHING)
    return grid, owned, land, veg


def colours_in(img, cols):
    arr = np.asarray(img)[:, cols]
    return {tuple(int(v) for v in c) for c in np.unique(arr.reshape(-1, 3), axis=0)}


class PlantTest(unittest.TestCase):
    def test_each_class_gets_its_own(self):
        grid, owned, land, veg = setup()
        forest, counts = LV.plant_landcover(veg, land, grid, owned, P())
        young = {C.TREE_SMALL, C.SPARSE_TREES}
        allowed = {
            10: {C.VEG_NOTHING},
            20: {C.VEG_NOTHING, C.BUSHES} | young,
            30: {C.VEG_NOTHING, C.SHORT_GRASS, C.BUSHES},
            90: {C.VEG_NOTHING, C.DENSE_BUSHES_GRASS, C.SPARSE_TREES},
            60: {C.VEG_NOTHING},
        }
        for i, code in enumerate(STRIPES):
            got = colours_in(veg, slice(i * 50, (i + 1) * 50))
            self.assertLessEqual(got, allowed[code], code)
            if code in (20, 30, 90):
                self.assertGreater(len(got), 1, code)
        self.assertTrue(forest[:, :50].all())
        self.assertFalse(forest[:, 50:].any())
        self.assertGreater(counts[20], 0)

    def test_marsh_sits_on_dark_grass(self):
        grid, owned, land, veg = setup()
        LV.plant_landcover(veg, land, grid, owned, P())
        marsh = np.all(np.asarray(veg) == C.DENSE_BUSHES_GRASS, axis=2)
        self.assertTrue(np.all(np.asarray(land)[marsh] == C.DARK_GRASS))

    def test_unowned_untouched(self):
        grid, owned, land, veg = setup(owned_all=False)
        forest, _ = LV.plant_landcover(veg, land, grid, owned, P())
        self.assertFalse((np.asarray(veg)[:100] != 0).any())
        self.assertFalse(forest[:100].any())
        self.assertTrue(np.all(np.asarray(land)[:100] == C.MEDIUM_GRASS))

    def test_density_zero(self):
        grid, owned, land, veg = setup()
        LV.plant_landcover(veg, land, grid, owned, P(), density=0.0)
        self.assertFalse((np.asarray(veg) != 0).any())

    def test_keeps_what_is_there(self):
        grid, owned, land, veg = setup()
        veg.putpixel((60, 60), C.TREES)
        LV.plant_landcover(veg, land, grid, owned, P())
        self.assertEqual(veg.getpixel((60, 60)), C.TREES)

    def test_deterministic(self):
        a = setup()
        b = setup()
        LV.plant_landcover(a[3], a[2], a[0], a[1], P())
        LV.plant_landcover(b[3], b[2], b[0], b[1], P())
        self.assertEqual(a[3].tobytes(), b[3].tobytes())


if __name__ == "__main__":
    unittest.main()
