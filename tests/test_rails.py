"""The rail bed is gravel: without rails on it, it reads as a sandy path."""
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import roads
from generator.rendering import rails


class _Proj:
    meters_per_tile = 1.0
    width = 60
    height = 40


def _painted(ring):
    img = Image.new("RGB", (60, 40), C.DIRT)
    feat = OSMFeature(1, "way", {"railway": "rail"}, [[0.0, 0.0], [0.0, 1.0]])
    with mock.patch.object(rails, "_feature_coords_px", return_value=[ring]):
        roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]}, _Proj())
    return img


class RailTile(unittest.TestCase):
    def test_a_flat_run_gets_the_east_west_tile(self):
        img = _painted([(5, 20), (50, 20)])
        self.assertIn(C.RAIL_NW_SE,
                      {img.getpixel((x, y)) for x in range(60) for y in range(40)})

    def test_a_vertical_run_gets_the_north_south_tile(self):
        img = _painted([(20, 5), (20, 35)])
        self.assertIn(C.RAIL_NE_SW,
                      {img.getpixel((x, y)) for x in range(60) for y in range(40)})

    def test_a_long_run_mostly_across_gets_the_east_west_tile(self):
        img = _painted([(5, 30), (45, 12)])
        self.assertIn(C.RAIL_NW_SE,
                      {img.getpixel((x, y)) for x in range(60) for y in range(40)})

    def test_the_dirt_bed_shows_beside_the_track(self):
        img = _painted([(5, 30), (40, 5)])
        self.assertEqual(img.getpixel((20, 34)), C.DIRT)

    def test_railroad_cuts_straight_through_water_and_wetland_pools(self):
        from generator import renderer
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0018, -84.9978
        proj = Projector.build(south, west, north, east, 1.0, 0.0)
        pond = OSMFeature(1, "way", {"natural": "water"}, [
            proj.to_latlon(55, 55), proj.to_latlon(95, 55),
            proj.to_latlon(95, 95), proj.to_latlon(55, 95),
            proj.to_latlon(55, 55),
        ])
        wetland = OSMFeature(2, "way", {"natural": "wetland", "wetland": "marsh"}, [
            proj.to_latlon(10, 10), proj.to_latlon(140, 10),
            proj.to_latlon(140, 140), proj.to_latlon(10, 140),
            proj.to_latlon(10, 10),
        ])
        rail = OSMFeature(3, "way", {"railway": "rail"}, [
            proj.to_latlon(20, 75), proj.to_latlon(130, 75),
        ])
        import numpy as np
        import tempfile
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([wetland, pond, rail], south, west, north, east,
                                  meters_per_tile=1.0, output_dir=out, map_name="rw")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
            # Inside the lake box (x=65..85, y=73..78) the rail pixels stay intact, not C.WATER.
            rail_band = land[73:79, 65:85]
            has_rail = np.any(np.all(rail_band == C.RAIL_NW_SE, axis=2))
            self.assertTrue(has_rail)
            # And water exists cleanly above the track rather than swallowing it.
            self.assertEqual(tuple(land[60, 75]), C.WATER)


if __name__ == "__main__":
    unittest.main()
