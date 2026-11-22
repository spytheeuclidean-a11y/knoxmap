import unittest

from knoxbuild.build import SHED_HOUSE_SIDE_TILES, too_small_for_rooms
from knoxbuild.layout import build_building


def rooms(w, h):
    return min(len(build_building(w, h, levels=1, seed=s, kind=None, street="S").storeys[0].rooms)
               for s in range(4))


class SmallHousesAreSheds(unittest.TestCase):
    def test_the_limit_is_where_the_layout_stops_making_rooms(self):
        # A footprint is too small exactly when the layout gives it one room.
        for h in range(4, 10):
            for w in range(4, 10):
                with self.subTest(w=w, h=h):
                    self.assertEqual(too_small_for_rooms(w, h), rooms(w, h) == 1)

    def test_either_side_over_the_limit_is_a_house(self):
        self.assertFalse(too_small_for_rooms(SHED_HOUSE_SIDE_TILES + 1, 4))
        self.assertFalse(too_small_for_rooms(4, SHED_HOUSE_SIDE_TILES + 1))
        self.assertTrue(too_small_for_rooms(SHED_HOUSE_SIDE_TILES, SHED_HOUSE_SIDE_TILES))


if __name__ == "__main__":
    unittest.main()
