import unittest
from collections import Counter

from knoxbuild.layout import _blocks, build_building


class HouseRoomQuotas(unittest.TestCase):
    def test_large_house_has_a_bounded_whole_building_room_count(self):
        for seed in range(3):
            with self.subTest(seed=seed):
                building = build_building(28, 24, levels=3, seed=seed, kind="house")
                counts = Counter(room.kind for room in building.rooms)
                bedrooms = counts["bedroom"] + counts["kidsbedroom"]
                self.assertLessEqual(bedrooms, 5)
                self.assertLessEqual(counts["bathroom"], 2)
                self.assertGreater(bedrooms, 0)

    def test_single_storey_house_has_at_most_two_bedrooms_and_one_bath(self):
        building = build_building(14, 12, seed=19, kind="house")
        counts = Counter(room.kind for room in building.rooms)

        self.assertLessEqual(counts["bedroom"] + counts["kidsbedroom"], 2)
        self.assertLessEqual(counts["bathroom"], 1)
        self.assertEqual(counts["bathroom"], 1)


class TinyHouses(unittest.TestCase):
    def test_every_storey_of_a_tiny_house_is_furnished(self):
        # A two-storey house of 5x8 had the stairs down its middle and every
        # room a one-tile strip round them; 7x7 and under, each floor was the
        # stair hall alone. Neither had a stick of furniture.
        for w in range(5, 10):
            for h in range(5, 10):
                for seed in range(3):
                    b = build_building(w, h, levels=2, seed=seed, kind="house")
                    for lvl, s in enumerate(b.storeys):
                        self.assertTrue(any(_blocks(f[0]) for f in s.furniture),
                                        (w, h, seed, lvl))


if __name__ == "__main__":
    unittest.main()
