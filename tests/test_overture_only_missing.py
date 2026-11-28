"""Which Overture/Microsoft footprints are added next to the mapped buildings."""
import unittest

from generator.osm import OSMFeature
from generator.overture import only_missing

LAT0, LON0 = 52.22, -0.08
M = 1 / 111320.0                     # a metre of latitude, in degrees


def box(x0, y0, x1, y1, ident=-1_000_000_001, building="yes"):
    """A rectangle given in metres east and north of (LAT0, LON0)."""
    mx = M / 0.6129                  # cos(52.22 deg): a metre of longitude
    ring = [(LAT0 + y * M, LON0 + x * mx)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return OSMFeature(osm_id=ident, kind="way", tags={"building": building},
                      geometry=ring)


class OnlyMissingTest(unittest.TestCase):
    house = box(0, 0, 10, 8, ident=1, building="house")

    def kept(self, cand):
        return only_missing([cand], [self.house])

    def test_a_footprint_inside_a_house_is_that_house(self):
        self.assertEqual(self.kept(box(1, 1, 9, 7)), [])

    def test_a_terrace_traced_as_one_block_is_the_mapped_houses(self):
        # two mapped houses, one block over both whose centre is in the gap:
        # built, its leftover became a shed in front of the houses (Cambourne)
        houses = [box(0, 0, 9, 8, ident=1), box(11, 0, 20, 8, ident=2)]
        self.assertEqual(only_missing([box(0, -2, 20, 10)], houses), [])

    def test_a_footprint_just_touching_a_house_is_kept(self):
        self.assertEqual(len(self.kept(box(9, 2, 19, 10))), 1)

    def test_a_footprint_clear_of_the_house_is_kept(self):
        self.assertEqual(len(self.kept(box(3, 12, 7, 16))), 1)


if __name__ == "__main__":
    unittest.main()
