"""British fronts and yards: no concrete apron round houses tagged only
building=yes (docs/REGIONAL_PROFILES.md, GB step 3)."""
import unittest

from PIL import Image

from generator.pz_colors import MEDIUM_GRASS
from generator.rendering import roads
from tests.test_dense_blocks import H, W, building, paved_fraction, proj, square, street

BLOCK = [square(100, 100, 160, 100), square(160, 100, 160, 160),
         square(160, 160, 100, 160), square(100, 160, 100, 100)]


def run(houses, country):
    landscape = Image.new("RGB", (W, H), MEDIUM_GRASS)
    buckets = {"road_minor": [street(ring) for ring in BLOCK]}
    roads._pave_dense_ground(landscape, houses, buckets, proj(), country=country)
    return landscape


def terraces(kind="yes", w=11, d=22):
    """Two rows of four, backs to each other: over half the block built on."""
    return [building(102 + 14 * i, y, w, d, kind) for i in range(4) for y in (102, 136)]


class BritishFronts(unittest.TestCase):
    def test_british_houses_tagged_yes_get_no_apron(self):
        self.assertEqual(paved_fraction(run(terraces(), "GB"), (101, 101, 159, 159)), 0.0)

    def test_elsewhere_they_still_do(self):
        self.assertGreater(paved_fraction(run(terraces(), None), (101, 101, 159, 159)), 0.2)

    def test_big_british_buildings_tagged_yes_still_get_one(self):
        # Over GB_HOUSE_MAX_M2: a works or a block of flats, not a house.
        big = [building(102, 102, 56, 30), building(102, 136, 56, 22)]
        self.assertGreater(paved_fraction(run(big, "GB"), (101, 101, 159, 159)), 0.2)


if __name__ == "__main__":
    unittest.main()
