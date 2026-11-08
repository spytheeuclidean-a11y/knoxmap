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


class PoolTest(unittest.TestCase):
    def test_share_clearance_and_bank(self):
        land, veg = blank(300, 300, C.DARK_GRASS)
        ImageDraw.Draw(land).rectangle((148, 0, 152, 299), fill=C.MEDIUM_ASPHALT)
        wet = np.ones((300, 300), dtype=bool)
        wet[:, 148:153] = False
        blocked = np.zeros_like(wet)
        n = F.paint_pools(land, veg, P(), wet, blocked)
        water = colour_mask(land, C.WATER)
        self.assertEqual(n, int(water.sum()))
        share = water.sum() / wet.sum()
        self.assertGreater(share, 0.05)
        self.assertLess(share, 0.15)
        self.assertFalse(water[:, 146:155].any())
        self.assertFalse(water[:2].any())
        self.assertTrue(colour_mask(veg, C.DENSE_BUSHES_GRASS).any())
        self.assertFalse((np.asarray(veg)[water] != 0).any())

    def test_never_under_a_building(self):
        land, veg = blank(200, 200, C.DARK_GRASS)
        wet = np.ones((200, 200), dtype=bool)
        blocked = np.zeros_like(wet)
        blocked[50:150, 50:150] = True
        F.paint_pools(land, veg, P(), wet, blocked)
        self.assertFalse(colour_mask(land, C.WATER)[48:152, 48:152].any())


class RockTest(unittest.TestCase):
    def setUp(self):
        self.grid = np.zeros((300, 600), dtype="uint8")
        self.grid[:, :300] = 100
        self.grid[:, 300:] = 60
        self.owned = np.ones((300, 600), dtype=bool)
        self.owned[:, 140:150] = False          # a road through the tundra
        self.land, self.veg = blank(600, 300, C.DIRT)

    def test_shares_and_clearance(self):
        F.paint_rocks(self.land, self.veg, P(), self.grid, self.owned)
        rock = colour_mask(self.veg, C.ROCKS) | colour_mask(self.veg, C.BOULDERS)
        tundra = self.owned[:, :300]
        self.assertAlmostEqual(rock[:, :300][tundra].mean(), 0.30, delta=0.08)
        self.assertAlmostEqual(rock[:, 300:].mean(), 0.10, delta=0.05)
        boulder = colour_mask(self.veg, C.BOULDERS)
        self.assertTrue(boulder.any())
        self.assertFalse(boulder[:, 138:152].any())
        self.assertFalse(rock[:, 140:150].any())
        for tree in (C.TREES, C.SPARSE_TREES, C.TREE_SMALL, C.TREES_DARK_GRASS):
            self.assertFalse(colour_mask(self.veg, tree).any())

    def test_moss_on_tundra_only(self):
        F.paint_rocks(self.land, self.veg, P(), self.grid, self.owned)
        moss = colour_mask(self.land, C.DARK_GRASS)
        self.assertAlmostEqual(moss[:, :300][self.owned[:, :300]].mean(), 0.30, delta=0.1)
        self.assertFalse(moss[:, 300:].any())


if __name__ == "__main__":
    unittest.main()
