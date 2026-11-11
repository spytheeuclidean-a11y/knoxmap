"""WorldCover ground is painted in marker colours, so what OSM painted over it
can be told apart even where OSM used the very same colour."""
import unittest

import numpy as np
from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.rendering import landcover as L


def grid_half(h=20, w=20):
    grid = np.zeros((h, w), dtype="uint8")
    grid[:, : w // 2] = 10
    grid[:, w // 2:] = 30
    return grid


class MarkerTest(unittest.TestCase):
    def test_markers_are_not_ground(self):
        for code, colour in L.MARKER.items():
            self.assertNotIn(colour, C.LANDSCAPE_COLORS, code)
        self.assertEqual(len(set(L.MARKER.values())), len(L.MARKER))

    def test_osm_in_the_same_colour_still_claims(self):
        grid = grid_half()
        land = Image.new("RGB", (20, 20), C.DARK_GRASS)
        L.paint_markers(land, grid)
        # A residential polygon (medium grass, class 30's own colour).
        ImageDraw.Draw(land).rectangle((14, 0, 19, 4), fill=C.MEDIUM_GRASS)
        owned = L.settle_markers(land, grid)
        self.assertFalse(owned[0:5, 14:20].any())
        self.assertTrue(owned[5:, 10:].all())
        self.assertTrue(owned[:, :10].all())
        arr = np.asarray(land)
        for colour in L.MARKER.values():
            self.assertFalse(np.all(arr == colour, axis=2).any())
        self.assertTrue(np.all(arr[10, 2] == C.DARK_GRASS))
        self.assertTrue(np.all(arr[10, 15] == C.MEDIUM_GRASS))

    def test_class_zero_is_left_alone(self):
        grid = np.zeros((10, 10), dtype="uint8")
        grid[:5] = 40
        land = Image.new("RGB", (10, 10), C.DARK_GRASS)
        L.paint_markers(land, grid)
        owned = L.settle_markers(land, grid)
        self.assertTrue(owned[:5].all())
        self.assertFalse(owned[5:].any())
        self.assertTrue(np.all(np.asarray(land)[7, 7] == C.DARK_GRASS))

    def test_grid_resized_to_image(self):
        grid = grid_half(10, 10)
        land = Image.new("RGB", (40, 40), C.DARK_GRASS)
        L.paint_markers(land, grid)
        owned = L.settle_markers(land, grid)
        self.assertEqual(owned.shape, (40, 40))
        self.assertTrue(owned.all())

    def test_refine_drops_repainted(self):
        grid = grid_half()
        land = Image.new("RGB", (20, 20), C.DARK_GRASS)
        L.paint_markers(land, grid)
        owned = L.settle_markers(land, grid)
        land.putpixel((3, 3), C.PALE_CONCRETE)
        L.refine_owned(land, grid, owned)
        self.assertFalse(owned[3, 3])
        self.assertTrue(owned[4, 4])
        self.assertEqual(L.resized_grid(grid, land.size).shape, (20, 20))


if __name__ == "__main__":
    unittest.main()
