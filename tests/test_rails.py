"""The rail bed is gravel: without rails on it, it reads as a sandy path."""
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import roads


class _Proj:
    meters_per_tile = 1.0


def _painted(ring, mpt=1.0):
    img = Image.new("RGB", (60, 40), C.LIGHT_ASPHALT)
    feat = OSMFeature(1, "way", {"railway": "rail"}, [[0.0, 0.0], [0.0, 1.0]])
    with mock.patch.object(roads, "_feature_coords_px", return_value=[ring]):
        roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]},
                          type("P", (), {"meters_per_tile": mpt})())
    return img


class Rails(unittest.TestCase):
    def test_two_rails_with_ballast_between_them(self):
        img = _painted([(5, 20), (55, 20)])
        self.assertEqual(img.getpixel((30, 19)), C.DARKEST_ASPHALT)
        self.assertEqual(img.getpixel((30, 21)), C.DARKEST_ASPHALT)
        self.assertEqual(img.getpixel((30, 20)), C.LIGHT_ASPHALT)

    def test_sleepers_cross_the_bed(self):
        img = _painted([(5, 20), (55, 20)])
        self.assertEqual(img.getpixel((8, 20)), C.DIRT)     # 3 m along, mid-bed
        self.assertEqual(img.getpixel((11, 20)), C.DIRT)    # 6 m along
        self.assertEqual(img.getpixel((9, 20)), C.LIGHT_ASPHALT)  # between

    def test_rails_follow_a_diagonal(self):
        img = _painted([(5, 5), (55, 35)])
        dark = sum(1 for x in range(60) for y in range(40)
                   if img.getpixel((x, y)) == C.DARKEST_ASPHALT)
        self.assertGreater(dark, 60)


if __name__ == "__main__":
    unittest.main()
