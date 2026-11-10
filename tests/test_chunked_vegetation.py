"""Tests for chunked/strip-based vegetation rasterization optimization."""
import unittest
import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import vegetation as V


class DummyProjector:
    meters_per_tile = 1.0

    @staticmethod
    def to_px(lat, lon):
        return lon, lat


class ChunkedVegetationTests(unittest.TestCase):
    def setUp(self):
        self.proj = DummyProjector()

    def test_wild_growth_chunked_deterministic(self):
        size = (400, 400)
        land = Image.new("RGB", size, C.MEDIUM_GRASS)
        # Add a strip of road that wild growth must avoid
        for x in range(size[0]):
            for y in range(80, 90):
                land.putpixel((x, y), C.DARK_ASPHALT)

        veg = Image.new("RGB", size, C.VEG_NOTHING)
        planted = V._paint_wild_growth(veg, land, self.proj, 1.0)
        self.assertGreater(planted, 0)

        # Verify no trees planted on road
        px = veg.load()
        for x in range(size[0]):
            for y in range(80, 90):
                self.assertEqual(px[x, y], C.VEG_NOTHING)

    def test_groves_chunked_output(self):
        size = (500, 500)
        land = Image.new("RGB", size, C.MEDIUM_GRASS)
        veg = Image.new("RGB", size, C.VEG_NOTHING)

        planted = V._paint_groves(veg, land, self.proj, 1.0)
        self.assertGreater(planted, 0)

        # Trees sit on dark grass
        veg_arr = np.array(veg)
        land_arr = np.array(land)
        has_tree = (veg_arr == C.TREES).all(axis=2)
        if has_tree.any():
            self.assertTrue((land_arr[has_tree] == C.DARK_GRASS).all())

    def test_gardens_chunked_placement(self):
        size = (400, 400)
        land = Image.new("RGB", size, C.MEDIUM_GRASS)
        veg = Image.new("RGB", size, C.VEG_NOTHING)

        # Building footprint at (100, 100) -> (150, 150)
        feats = [
            OSMFeature(1, "way", {"building": "yes"},
                       [(100, 100), (100, 150), (150, 150), (150, 100), (100, 100)])
        ]

        planted = V._paint_gardens(veg, land, feats, self.proj, 1.0)
        self.assertGreater(planted, 0)

        # Verify no trees inside building footprint
        px = veg.load()
        for y in range(101, 149):
            for x in range(101, 149):
                self.assertEqual(px[x, y], C.VEG_NOTHING)

    def test_parks_chunked_placement(self):
        size = (400, 400)
        land = Image.new("RGB", size, C.DARK_GRASS)
        veg = Image.new("RGB", size, C.VEG_NOTHING)

        park_feats = [
            OSMFeature(1, "way", {"leisure": "park"},
                       [(50, 50), (50, 250), (250, 250), (250, 50), (50, 50)])
        ]

        planted = V._paint_parks(veg, land, park_feats, self.proj, 1.0)
        self.assertGreater(planted, 0)

        # Verify vegetation was planted inside the park
        veg_arr = np.array(veg)
        park_interior = veg_arr[60:240, 60:240]
        self.assertTrue((park_interior != C.VEG_NOTHING).any())

    def test_plant_big_trees_chunked(self):
        size = (300, 300)
        land = Image.new("RGB", size, C.DARK_GRASS)
        veg = Image.new("RGB", size, C.TREES)

        counts = V._plant_big_trees(veg, land, [], [], [], self.proj, 1.0)
        self.assertIsInstance(counts, dict)
        self.assertGreater(sum(counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
