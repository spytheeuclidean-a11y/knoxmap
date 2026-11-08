"""Which crossings get a flyover (generator/structures.py: plan_bridges).

A flyover rises on ramps, and the ramps only line up with the deck where the
crossing is square to the tile grid. A diagonal one never joins, so it is left
at ground level: a junction a player can use, not a bridge they cannot.
"""
import unittest
from types import SimpleNamespace

from generator.osm import OSMFeature
from generator.structures import Plan, plan_bridges


def proj():
    return SimpleNamespace(width=120, height=120, meters_per_tile=1.0,
                           to_px=lambda la, lo: (lo, la))


def way(tags, points):
    return OSMFeature(osm_id=1, kind='way', tags=tags,
                      geometry=[(y, x) for x, y in points])


def build(overpass):
    ground = way({"highway": "residential"}, [(10, 60), (110, 60)])
    upper = way({"highway": "primary", "bridge": "yes", "layer": "1"}, overpass)
    plan = Plan()
    plan_bridges({"road_minor": [ground], "road_major": [upper]}, proj(), 1.0,
                 lambda feat, cat: 8.0, plan)
    return plan


class Flyovers(unittest.TestCase):
    def test_a_square_crossing_gets_its_ramps(self):
        plan = build([(60, 20), (60, 100)])
        self.assertEqual(plan.bridges, 1)
        self.assertTrue(any(layer == "Floor" and tile.startswith("ramps_01")
                            for (_x, _y, _z, layer), tile in plan.tiles.items()))

    def test_a_diagonal_crossing_is_left_on_the_ground(self):
        plan = build([(20, 20), (100, 100)])
        self.assertEqual(plan.bridges, 0)
        self.assertEqual(plan.tiles, {})
        self.assertEqual(plan.straight, [])


if __name__ == "__main__":
    unittest.main()
