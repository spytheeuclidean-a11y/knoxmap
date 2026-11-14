"""Pavement on the edge of a street (generator/rendering/roads.py).

A pavement tile with no pavement beside it orthogonally is one step of a
diagonal edge. On its own the tile draws with a lip and reads as a spike in the
grass, so the tidy-up pass takes it back to the ground it stands in.
"""
import unittest

from PIL import Image

from generator.pz_colors import (MEDIUM_GRASS, MEDIUM_ASPHALT, DARK_ASPHALT,
                                 DARKEST_ASPHALT, PALE_CONCRETE)
from generator.rendering.roads import _smooth_road_edges

ASPHALT = (MEDIUM_ASPHALT, DARK_ASPHALT, DARKEST_ASPHALT)


def is_colour(ground, colours):
    import numpy as np
    mask = np.zeros(ground.shape[:2], dtype=bool)
    for colour in colours:
        mask |= np.all(ground == colour, axis=2)
    return mask


def tidy(im):
    _smooth_road_edges(im, ASPHALT, is_colour)
    return im


class RoadEdges(unittest.TestCase):
    def test_a_straight_street_keeps_its_pavements(self):
        im = Image.new('RGB', (60, 60), MEDIUM_GRASS)
        for y in range(10, 50):
            for x in range(20, 31):
                im.putpixel((x, y), MEDIUM_ASPHALT)
            im.putpixel((19, y), PALE_CONCRETE)
            im.putpixel((31, y), PALE_CONCRETE)
        tidy(im)
        self.assertEqual(im.getpixel((19, 30)), PALE_CONCRETE)
        self.assertEqual(im.getpixel((31, 30)), PALE_CONCRETE)

    def test_a_stepped_pavement_runs_on(self):
        # One tile a step down a diagonal edge is what a sidewalk beside a
        # diagonal street is made of. It stays, so the line runs on instead of
        # stopping and starting.
        im = Image.new('RGB', (60, 60), MEDIUM_GRASS)
        for i in range(10, 40):
            for x in range(i, i + 8):
                im.putpixel((x, i), MEDIUM_ASPHALT)
            im.putpixel((i - 1, i), PALE_CONCRETE)
        tidy(im)
        left = [im.getpixel((i - 1, i)) for i in range(10, 40)]
        self.assertGreaterEqual(left.count(PALE_CONCRETE), 28,
                                "the sidewalk keeps its steps")

    def test_a_lone_slab_is_taken_back_to_grass(self):
        # A slab with no pavement beside it in any direction is a stub standing
        # in the lawn, and goes.
        im = Image.new('RGB', (60, 60), MEDIUM_GRASS)
        for x in range(20, 30):
            im.putpixel((x, 10), MEDIUM_ASPHALT)
        im.putpixel((25, 20), PALE_CONCRETE)
        tidy(im)
        self.assertEqual(im.getpixel((25, 20)), MEDIUM_GRASS)


if __name__ == "__main__":
    unittest.main()

class PavementAgainstGrass(unittest.TestCase):
    """The edge the pavement makes on grass had the same teeth as the road's
    edge on pavement, one boundary out."""

    def band(self):
        im = Image.new("RGB", (24, 24), MEDIUM_GRASS)
        for y in range(8, 16):
            for x in range(4, 20):
                im.putpixel((x, y), PALE_CONCRETE)
        for y in range(4, 8):
            for x in range(4, 20):
                im.putpixel((x, y), MEDIUM_ASPHALT)
        return im

    def test_a_tooth_of_grass_in_the_kerb_goes(self):
        im = self.band()
        im.putpixel((10, 7), MEDIUM_GRASS)      # grass between road and pavement
        tidy(im)
        self.assertNotEqual(im.getpixel((10, 7)), MEDIUM_GRASS)

    def test_a_slab_standing_in_the_grass_goes(self):
        im = self.band()
        im.putpixel((10, 18), PALE_CONCRETE)    # one square of pavement in lawn
        tidy(im)
        self.assertNotEqual(im.getpixel((10, 18)), PALE_CONCRETE)
    def test_a_one_tile_pavement_spike_into_grass_is_shaved(self):
        im = self.band()
        im.putpixel((10, 16), PALE_CONCRETE)    # 1-tile spike jutting into grass
        tidy(im)
        self.assertEqual(im.getpixel((10, 16)), MEDIUM_GRASS)

    def test_a_one_tile_grass_notch_in_pavement_is_filled(self):
        im = self.band()
        im.putpixel((10, 15), MEDIUM_GRASS)     # 1-tile notch in pavement edge
        tidy(im)
        self.assertEqual(im.getpixel((10, 15)), PALE_CONCRETE)


class DiagonalKerbs(unittest.TestCase):
    def test_shallow_horizontal_step_gets_no_diagonal_kerb(self):
        from types import SimpleNamespace
        from unittest import mock

        from generator import pz_colors as C
        from generator.rendering.roads import _paint_road_details

        w, h = 32, 20
        landscape = Image.new("RGB", (w, h), C.MEDIUM_GRASS)
        veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
        # Road steps down by 1 tile at x=16, with concrete pavement below it.
        for x in range(w):
            road_y = 6 if x < 16 else 7
            for y in range(road_y - 3, road_y + 1):
                landscape.putpixel((x, y), C.MEDIUM_ASPHALT)
            for y in range(road_y + 1, road_y + 4):
                landscape.putpixel((x, y), C.PALE_CONCRETE)
        diag_colours = {
            C.KERB_DNW_0, C.KERB_DNW_1, C.KERB_DNE_0, C.KERB_DNE_1,
            C.KERB_DSW_0, C.KERB_DSW_1, C.KERB_DSE_0, C.KERB_DSE_1,
        }
        with mock.patch("generator.rendering.furniture._rule_ready", return_value=True):
            _paint_road_details(veg, landscape, {}, SimpleNamespace(meters_per_tile=1.0))
        found = {veg.getpixel((x, y)) for y in range(h) for x in range(w)} & diag_colours
        self.assertFalse(found, f"unexpected diagonal kerbs on shallow step: {found}")

    def test_forty_five_degree_edge_gets_no_diagonal_kerbs(self):
        from types import SimpleNamespace
        from unittest import mock

        from generator import pz_colors as C
        from generator.rendering.roads import _paint_road_details

        w, h = 24, 24
        landscape = Image.new("RGB", (w, h), C.MEDIUM_GRASS)
        veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
        # 45-degree diagonal road along y == x with pavement below-right.
        for x in range(4, 20):
            for d in range(3):
                landscape.putpixel((x, x - d), C.MEDIUM_ASPHALT)
            for d in range(1, 4):
                landscape.putpixel((x, x + d), C.PALE_CONCRETE)
        diag_colours = {
            C.KERB_DNW_0, C.KERB_DNW_1, C.KERB_DNE_0, C.KERB_DNE_1,
            C.KERB_DSW_0, C.KERB_DSW_1, C.KERB_DSE_0, C.KERB_DSE_1,
        }
        with mock.patch("generator.rendering.furniture._rule_ready", return_value=True):
            _paint_road_details(veg, landscape, {}, SimpleNamespace(meters_per_tile=1.0))
        found = {veg.getpixel((x, y)) for y in range(h) for x in range(w)} & diag_colours
        self.assertFalse(found, f"unexpected diagonal kerbs on 45-degree road edge: {found}")
