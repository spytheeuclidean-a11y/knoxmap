"""A road drawn as a closed loop stays a road; it does not pave what is inside."""
import unittest

from generator.osm import OSMFeature
from generator.rendering.geometry import _is_polygon
from generator.sketch import features

RING = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]


def way(tags, pts=RING):
    return OSMFeature(1, "way", tags, list(pts))


class ClosedRoads(unittest.TestCase):
    def test_a_loop_of_road_is_not_an_area(self):
        for h in ("residential", "primary", "service", "track", "tertiary_link"):
            with self.subTest(h):
                self.assertFalse(_is_polygon(way({"highway": h})))

    def test_unless_the_mapper_says_it_is(self):
        self.assertTrue(_is_polygon(way({"highway": "service", "area": "yes"})))
        self.assertTrue(_is_polygon(way({"highway": "service", "area:highway": "service"})))

    def test_other_closed_ways_are_still_areas(self):
        self.assertTrue(_is_polygon(way({"building": "yes"})))
        self.assertTrue(_is_polygon(way({"landuse": "forest"})))
        self.assertTrue(_is_polygon(way({"highway": "pedestrian"})))

    def test_an_open_road_is_a_line_and_a_relation_an_area(self):
        self.assertFalse(_is_polygon(way({"highway": "residential"}, RING[:3])))
        self.assertTrue(_is_polygon(OSMFeature(2, "relation", {"type": "multipolygon"}, [])))

    def test_a_drawn_closed_road_keeps_its_inside(self):
        drawn = {"features": [{"type": "Feature", "properties": {"kind": "pedestrian"},
                               "geometry": {"type": "LineString",
                                            "coordinates": [[lo, la] for la, lo in RING]}}]}
        out = features(drawn)
        self.assertTrue(out)
        self.assertFalse(_is_polygon(out[0]))
        drawn["features"][0]["properties"]["kind"] = "footpath"
        self.assertFalse(_is_polygon(features(drawn)[0]))


if __name__ == "__main__":
    unittest.main()
