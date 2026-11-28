"""British back gardens: long and narrow, a small shed at the far end
(docs/REGIONAL_PROFILES.md, GB step 4)."""
import unittest

from generator.rendering.infill import _back_sheds
from tests.test_gb_boundaries import street as gb_street
from tests.test_infill import PROJ, polys, row, street


def terrace():
    """Twelve terraced houses 6 m wide, wall to wall, 9 m deep: 54 m2 each."""
    return row(40, 12, 6, 6, 156, 165)


class BritishSheds(unittest.TestCase):
    def sheds(self, houses, country):
        return polys(_back_sheds({"road_minor": [street()]}, [], houses, PROJ,
                                 country=country))

    def test_terraced_houses_get_sheds_in_britain(self):
        self.assertTrue(self.sheds(terrace(), "GB"))
        self.assertEqual(self.sheds(terrace(), None), [])     # too small elsewhere

    def test_a_british_shed_is_small_and_at_the_far_end_of_its_own_garden(self):
        houses = polys(terrace())
        for shed in self.sheds(terrace(), "GB"):
            x0, y0, x1, y1 = shed.bounds
            self.assertLessEqual(x1 - x0, 3.01)
            self.assertLessEqual(y1 - y0, 3.01)
            self.assertGreaterEqual(y0, 165 + 7 - 0.01)        # well back from the house
            mid = (x0 + x1) / 2
            own = [h for h in houses if h.bounds[0] <= mid <= h.bounds[2]]
            self.assertTrue(own, "within its own house's width")
            self.assertGreaterEqual(x0, own[0].bounds[0] - 0.01)
            self.assertLessEqual(x1, own[0].bounds[2] + 0.01)


class BritishGardens(unittest.TestCase):
    def back_fences(self, region):
        fences, *_ = gb_street(region)
        return [f for f in fences if not all(y == 28 for _x, y in f[0])]

    def test_a_british_back_garden_is_as_wide_as_the_house_and_deeper(self):
        gb, default = self.back_fences("gb"), self.back_fences(None)
        self.assertTrue(gb and default)

        def depth(f):
            return 14 - min(y for _x, y in f[0])            # back wall at y = 14

        def width(f):
            xs = [x for x, _y in f[0]]
            return max(xs) - min(xs)

        self.assertGreater(min(map(depth, gb)), max(map(depth, default)))
        self.assertTrue(all(width(f) == 6 for f in gb), [width(f) for f in gb])
        self.assertTrue(any(width(f) > 6 for f in default))


if __name__ == "__main__":
    unittest.main()
