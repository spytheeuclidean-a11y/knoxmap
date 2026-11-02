"""A large building three storeys up is a block of flats, not a house
(knoxbuild/build.flats_by_height)."""
import unittest

from knoxbuild.build import flats_by_height
from knoxbuild.settings import Settings


class TallFlats(unittest.TestCase):
    def test_a_big_building_three_storeys_up_is_flats(self):
        # Piqua_9234, 54 x 35 and four storeys, was one house: sixteen
        # offices, sixteen storerooms and eight laundries a floor.
        self.assertTrue(flats_by_height(None, 4, "yes", 54 * 35, Settings()))

    def test_houses_stay_houses(self):
        s = Settings()
        self.assertFalse(flats_by_height(None, 2, "yes", 54 * 35, s))     # two storeys says nothing
        self.assertFalse(flats_by_height(None, 3, "yes", 10 * 8, s))      # a small tall house
        self.assertFalse(flats_by_height(None, 4, "house", 54 * 35, s))   # the mapper says a house
        self.assertFalse(flats_by_height("shop", 4, "yes", 54 * 35, s))   # already something else

    def test_the_setting_decides_how_big(self):
        self.assertFalse(flats_by_height(None, 4, "yes", 1000, Settings(apartment_footprint=2000)))


if __name__ == "__main__":
    unittest.main()
