"""The rail bed is gravel: without rails on it, it reads as a sandy path."""
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import roads


class _Proj:
    meters_per_tile = 1.0


def _painted(ring):
    img = Image.new("RGB", (60, 40), C.DIRT)
    feat = OSMFeature(1, "way", {"railway": "rail"}, [[0.0, 0.0], [0.0, 1.0]])
    with mock.patch.object(roads, "_feature_coords_px", return_value=[ring]):
        roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]}, _Proj())
    return img


class RailTile(unittest.TestCase):
    def test_a_line_climbing_north_east_gets_the_ne_sw_tile(self):
        img = _painted([(5, 30), (40, 5)])
        self.assertIn(C.RAIL_NE_SW,
                      {img.getpixel((x, y)) for x in range(60) for y in range(40)})

    def test_a_line_climbing_south_east_gets_the_nw_se_tile(self):
        img = _painted([(5, 5), (40, 30)])
        self.assertIn(C.RAIL_NW_SE,
                      {img.getpixel((x, y)) for x in range(60) for y in range(40)})

    def test_the_dirt_bed_shows_beside_the_track(self):
        img = _painted([(5, 30), (40, 5)])
        self.assertEqual(img.getpixel((20, 34)), C.DIRT)


if __name__ == "__main__":
    unittest.main()
