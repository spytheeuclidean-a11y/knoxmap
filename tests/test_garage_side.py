import unittest

import numpy as np

from knoxbuild.street_context import free_way_side


class FreeWaySide(unittest.TestCase):
    def test_a_garage_behind_a_house_faces_the_way_round_it(self):
        occ = np.zeros((30, 30), dtype=bool)
        road = np.zeros((30, 30), dtype=np.uint8)
        road[0:2, :] = 2                      # the street, along the north
        occ[5:16, 4:20] = True                # a house against its north wall
        occ[16:20, 8:12] = True               # the garage, behind the house
        # Open ground runs round the east end of the house; nothing to the west
        # of the lot but a fence line of buildings.
        occ[5:20, 0:4] = True
        self.assertEqual(free_way_side(8, 16, 4, 4, occ, road), "E")

    def test_no_way_out_is_none(self):
        occ = np.ones((10, 10), dtype=bool)
        occ[4:6, 4:6] = False
        road = np.zeros((10, 10), dtype=np.uint8)
        road[0, :] = 2
        self.assertIsNone(free_way_side(4, 4, 2, 2, occ, road))

    def test_a_street_in_front_wins(self):
        occ = np.zeros((20, 20), dtype=bool)
        road = np.zeros((20, 20), dtype=np.uint8)
        road[0:2, :] = 2
        occ[8:12, 8:12] = True
        self.assertEqual(free_way_side(8, 8, 4, 4, occ, road), "N")


if __name__ == "__main__":
    unittest.main()
