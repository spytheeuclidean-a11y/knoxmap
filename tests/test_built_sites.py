"""A building site already built on is a neighbourhood, not bare dirt
(generator/rendering/landcover.built_sites)."""
import unittest
from types import SimpleNamespace

from generator.osm import OSMFeature
from generator.rendering.landcover import BUILT_SITE_BUILDINGS, built_sites


def proj():
    # Geometry is written as (y, x) tile pairs, so projects straight through.
    return SimpleNamespace(width=900, height=900, meters_per_tile=1.0,
                           to_px=lambda la, lo: (lo, la))


def area(x0, y0, x1, y1, **tags):
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return OSMFeature(osm_id=1, kind="way", tags=tags, geometry=[(y, x) for x, y in ring])


def houses(n, x0=110, y0=110):
    return [area(x0 + 20 * i, y0, x0 + 20 * i + 10, y0 + 10, building="house") for i in range(n)]


class BuiltSites(unittest.TestCase):
    def test_a_site_with_its_houses_up_is_built(self):
        site = area(100, 100, 400, 400, landuse="construction")
        self.assertEqual(built_sites([site], houses(BUILT_SITE_BUILDINGS), proj()), [site])

    def test_a_site_with_nothing_on_it_stays_a_site(self):
        site = area(100, 100, 400, 400, landuse="construction")
        self.assertEqual(built_sites([site], houses(2), proj()), [])

    def test_houses_outside_it_do_not_count(self):
        site = area(100, 100, 400, 400, landuse="construction")
        self.assertEqual(built_sites([site], houses(8, x0=500, y0=500), proj()), [])

    def test_one_big_building_covering_enough_of_it_counts(self):
        site = area(100, 100, 400, 400, landuse="construction")
        block = area(150, 150, 220, 220, building="apartments")
        self.assertEqual(built_sites([site], [block], proj()), [site])

    def test_a_quarry_or_brownfield_is_left_as_it_is(self):
        quarry = area(100, 100, 400, 400, landuse="quarry")
        brown = area(100, 100, 400, 400, landuse="brownfield")
        self.assertEqual(built_sites([quarry, brown], houses(8), proj()), [])


if __name__ == "__main__":
    unittest.main()
