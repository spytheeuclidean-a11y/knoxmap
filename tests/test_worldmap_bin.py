"""The paper map's cells stay inside what the game can index."""
import unittest

from knoxbuild import worldmap_bin as W


def square(x, y, side=3, corners=8):
    """A building-sized outline with `corners` points."""
    pts = [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]
    while len(pts) < corners:
        (ax, ay), (bx, by) = pts[-1], pts[0]
        pts.append(((ax + bx) / 2, (ay + by) / 2))
    return [pts]


class CellBudget(unittest.TestCase):
    def test_a_packed_city_cell_keeps_its_triangles_under_16_bits(self):
        # About 2,000 buildings and a few roads in one 256-tile cell, as a
        # city centre at 2 m a tile has: 16,000 points fit the old point
        # budget but triangulate to about 48,000 indices, past the 32767 the
        # game can address.
        features = [(square(x * 5, y * 5), [("building", "yes")])
                    for x in range(50) for y in range(40)]
        features += [(square(0, y * 20, side=250, corners=40), [("highway", "primary")])
                     for y in range(10)]
        kept = W._within_budget(features)
        self.assertTrue(kept)
        self.assertLessEqual(sum(W._indices(p, props) for p, props in kept), W.CELL_INDEX_BUDGET)
        self.assertLessEqual(sum(W._points(p) for p, _ in kept), W.CELL_POINT_BUDGET)
        self.assertLess(W.CELL_INDEX_BUDGET, 32767)

    def test_an_ordinary_cell_is_left_alone(self):
        features = [(square(x * 10, y * 10), [("building", "yes")])
                    for x in range(10) for y in range(10)]
        self.assertEqual(W._within_budget(features), features)


if __name__ == "__main__":
    unittest.main()
