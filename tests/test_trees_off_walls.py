import unittest

import numpy as np

from generator import pz_colors as C
from knoxbuild.yards import _clear_trees_near_walls


class TreesOffWalls(unittest.TestCase):
    def test_trees_beside_a_building_go_and_far_ones_stay(self):
        veg = np.zeros((40, 40, 3), dtype=np.uint8)
        veg[:] = C.VEG_NOTHING
        occ = np.zeros((40, 40), dtype=bool)
        occ[15:20, 15:20] = True
        veg[20, 16] = C.TREES            # right against the south wall
        veg[21, 16] = C.TREE_SMALL       # a tile out
        veg[22, 16] = C.TREES            # three out: left alone
        veg[24, 16] = C.TREE_BIG         # a big one needs more room: five out
        veg[26, 16] = C.TREE_BIG         # six out: left alone
        veg[30, 30] = C.TREE_BIG         # far away
        veg[18, 21] = C.BUSHES           # a bush is not a tree
        _clear_trees_near_walls(veg, occ)
        for y, x, kept in ((20, 16, False), (21, 16, False), (22, 16, True), (24, 16, False),
                           (26, 16, True), (30, 30, True), (18, 21, True)):
            self.assertEqual(tuple(veg[y, x]) != tuple(C.VEG_NOTHING), kept, (y, x))


if __name__ == "__main__":
    unittest.main()
