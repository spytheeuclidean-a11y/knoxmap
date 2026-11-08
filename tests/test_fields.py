"""Fields on farmland, pools in wetland and rock fields on bare ground."""
import math
import unittest

import numpy as np
from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.rendering import fields as F


class P:
    meters_per_tile = 1.0


def colour_mask(img, colour):
    return np.all(np.asarray(img) == colour, axis=2)


def rect_ring(x0, y0, x1, y1, angle_deg=0.0):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a = math.radians(angle_deg)
    out = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        dx, dy = x - cx, y - cy
        out.append((cx + dx * math.cos(a) - dy * math.sin(a),
                    cy + dx * math.sin(a) + dy * math.cos(a)))
    return out


def blank(w, h, ground=C.LIGHT_GRASS):
    return Image.new("RGB", (w, h), ground), Image.new("RGB", (w, h), C.VEG_NOTHING)


class OsmFieldTest(unittest.TestCase):
    def test_long_field_is_split_along_its_axis(self):
        land, veg = blank(500, 200)
        n = F.paint_fields(land, veg, P(), [rect_ring(40, 50, 440, 150)], None)
        self.assertGreaterEqual(n, 3)
        self.assertTrue(colour_mask(land, C.DIRT_ROWS_H).any())
        self.assertFalse(colour_mask(land, C.DIRT_ROWS_V).any())
        inside = np.asarray(land)[55:145, 45:435]
        allowed = np.zeros(inside.shape[:2], dtype=bool)
        for colour in (C.DIRT_ROWS_H, C.LIGHT_GRASS):
            allowed |= np.all(inside == colour, axis=2)
        self.assertTrue(allowed.all())

    def test_upright_field_gets_vertical_rows(self):
        land, veg = blank(200, 500)
        F.paint_fields(land, veg, P(), [rect_ring(50, 40, 150, 440)], None)
        self.assertTrue(colour_mask(land, C.DIRT_ROWS_V).any())
        self.assertFalse(colour_mask(land, C.DIRT_ROWS_H).any())

    def test_small_field_is_one_plot(self):
        land, veg = blank(200, 200)
        self.assertEqual(F.paint_fields(land, veg, P(), [rect_ring(50, 50, 130, 110)], None), 1)

    def test_road_over_a_field_survives(self):
        land, veg = blank(500, 200)
        ImageDraw.Draw(land).rectangle((200, 0, 205, 199), fill=C.MEDIUM_ASPHALT)
        F.paint_fields(land, veg, P(), [rect_ring(40, 50, 440, 150)], None)
        self.assertTrue(colour_mask(land, C.MEDIUM_ASPHALT)[:, 200:206].all())
        self.assertFalse((np.asarray(veg)[:, 200:206] != 0).any())

    def test_only_light_grass_outside_is_untouched(self):
        land, veg = blank(500, 200, C.DARK_GRASS)
        ImageDraw.Draw(land).polygon(rect_ring(40, 50, 440, 150), fill=C.LIGHT_GRASS)
        F.paint_fields(land, veg, P(), [rect_ring(40, 50, 440, 150)], None)
        self.assertTrue(colour_mask(land, C.DARK_GRASS)[0:45].all())


class CroplandTest(unittest.TestCase):
    def test_shares_and_determinism(self):
        def run():
            land, veg = blank(2000, 2000)
            n = F.paint_fields(land, veg, P(), [], np.ones((2000, 2000), dtype=bool))
            return n, land, veg
        n, land, veg = run()
        self.assertGreater(n, 100)
        corn = colour_mask(veg, C.CORN_1) | colour_mask(veg, C.CORN_2)
        furrow = colour_mask(land, C.DIRT_ROWS_H) | colour_mask(land, C.DIRT_ROWS_V)
        share_corn = corn.sum() / furrow.sum()
        self.assertGreater(share_corn, 0.45)
        self.assertLess(share_corn, 0.80)
        self.assertGreater(furrow.mean(), 0.6)
        self.assertTrue(colour_mask(veg, C.BUSHES).any())
        n2, land2, veg2 = run()
        self.assertEqual(n, n2)
        self.assertEqual(land.tobytes(), land2.tobytes())
        self.assertEqual(veg.tobytes(), veg2.tobytes())

    def test_only_inside_the_mask(self):
        land, veg = blank(600, 600)
        mask = np.zeros((600, 600), dtype=bool)
        mask[:, :300] = True
        F.paint_fields(land, veg, P(), [], mask)
        self.assertTrue(colour_mask(land, C.LIGHT_GRASS)[:, 300:].all())
        self.assertFalse((np.asarray(veg)[:, 300:] != 0).any())


if __name__ == "__main__":
    unittest.main()
