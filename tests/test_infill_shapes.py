import unittest

from shapely.geometry import Polygon

from generator.rendering.infill import _outline, _shaped, _trimmed
from tests.test_infill import fill, polys, row, street, way

FRAME = (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)      # the street along x, out from it along y


def ell(x0, y0, w=15, d=12, notch_w=6, notch_d=5):
    """An L: a w x d box with a corner taken out."""
    return Polygon([(x0, y0), (x0 + w, y0), (x0 + w, y0 + d - notch_d),
                    (x0 + w - notch_w, y0 + d - notch_d), (x0 + w - notch_w, y0 + d),
                    (x0, y0 + d)])


class Outline(unittest.TestCase):
    def test_an_l_shape_is_a_template(self):
        t = _outline(ell(10, 4), FRAME)
        self.assertEqual(len(t), 6)
        self.assertTrue(all(0 <= u <= 1 and 0 <= v <= 1 for u, v in t))

    def test_a_box_is_not(self):
        self.assertIsNone(_outline(Polygon([(0, 4), (15, 4), (15, 16), (0, 16)]), FRAME))

    def test_a_turned_building_is_not(self):
        from shapely import affinity
        self.assertIsNone(_outline(affinity.rotate(ell(10, 4), 30), FRAME))


class Shaped(unittest.TestCase):
    def test_the_template_is_copied_into_a_box_facing_away_from_the_street(self):
        t = _outline(ell(10, 4), FRAME)
        b = [(0, 0), (20, 0), (20, 10), (0, 10)]
        pts = _shaped(b, (1.0, 0.0), (0.0, 1.0), t, 1.0)
        poly = Polygon(pts)
        self.assertLess(poly.area, 200)
        self.assertGreater(poly.area, 0.55 * 200)
        # the notch is where the template's was: at the far end from the street
        self.assertTrue(poly.contains(Polygon([(1, 1), (2, 1), (2, 2), (1, 2)])))


class Trimmed(unittest.TestCase):
    def test_boxes_are_smaller_and_big_first(self):
        got = _trimmed([(0, 0), (20, 0), (20, 10), (0, 10)], 1.0)
        areas = [(c[2][0] - c[0][0]) * (c[2][1] - c[0][1]) for c in got]
        self.assertEqual(areas, sorted(areas, reverse=True))
        self.assertLess(areas[0], 200)
        self.assertTrue(all(a >= 16 for a in areas))


class CarriedToTheEnd(unittest.TestCase):
    def test_a_gap_that_ends_against_a_side_street_is_filled_up_to_it(self):
        # a row, a gap, and a side street across the end of the gap: the last
        # lot would have run into the road and was dropped whole.
        houses = row(40, 4, 18, 15, 130, 142)
        side = way(9, [(130, 150), (130, 60)], highway="residential")
        made = fill(houses, roads=[street(), side])
        right_of_row = [p for p in polys(made) if p.bounds[0] > 108]
        self.assertTrue(right_of_row)
        for p in right_of_row:
            self.assertFalse(p.intersects(Polygon([(126, 100), (134, 100), (134, 150), (126, 150)])))


class RowOfEls(unittest.TestCase):
    def test_a_hole_in_a_row_of_l_shaped_houses_gets_plain_boxes(self):
        def el(i):
            x = 40 + i * 20
            pts = [(x, 130), (x + 15, 130), (x + 15, 137), (x + 9, 137), (x + 9, 142), (x, 142), (x, 130)]
            return way(100 + i, pts, building="house")
        houses = [el(i) for i in range(12) if i not in (4, 5, 6)]
        made = [p for p in polys(fill(houses)) if 110 < p.bounds[0] < 190]
        self.assertGreaterEqual(len(made), 2)
        for p in made:
            self.assertGreaterEqual(p.area, 0.99 * (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1]))


if __name__ == "__main__":
    unittest.main()
