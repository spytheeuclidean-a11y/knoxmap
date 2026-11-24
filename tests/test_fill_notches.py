import unittest

import numpy as np

from knoxbuild.footprint import Footprint, fill_notches


def fp_of(rows):
    m = np.array([[c == "#" for c in r] for r in rows])
    return Footprint(2, 2, m, 0.0, 1.0, 1.0)


class FillNotches(unittest.TestCase):
    def test_an_l_becomes_a_box_on_free_ground(self):
        fp = fp_of(["######", "######", "##....", "##...."])
        occ = np.zeros((12, 12), dtype=bool)
        occ[2:6, 2:8] |= fp.mask
        fill_notches(fp, occ, None)
        self.assertTrue(fp.mask.all())
        self.assertTrue(occ[2:6, 2:8].all())

    def test_a_neighbour_or_a_road_keeps_its_ground(self):
        fp = fp_of(["######", "######", "##....", "##...."])
        occ = np.zeros((12, 12), dtype=bool)
        occ[2:6, 2:8] |= fp.mask
        occ[4, 5] = True                      # a neighbour's tile
        avoid = np.zeros((12, 12), dtype=np.uint8)
        avoid[5, 7] = 2                       # a road
        fill_notches(fp, occ, avoid)
        self.assertFalse(fp.mask[2, 3])       # row 4, col 5
        self.assertFalse(fp.mask[3, 5])       # row 5, col 7
        self.assertEqual(int(fp.mask.sum()), 24 - 2)


if __name__ == "__main__":
    unittest.main()


class OutlineOfAFootprint(unittest.TestCase):
    def test_it_is_the_placed_shape_not_a_box(self):
        from knoxbuild.footprint import footprint_outline
        from shapely.geometry import Polygon
        fp = fp_of(["######", "######", "##....", "##...."])
        poly = Polygon(footprint_outline(fp))
        self.assertEqual(poly.area, 16)
        self.assertEqual(poly.bounds, (2.0, 2.0, 8.0, 6.0))
