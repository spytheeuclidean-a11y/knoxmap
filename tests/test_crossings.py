"""Crosswalks and stop lines where streets meet.

The pictures are lane-line tiles, so these tests only have to prove that a
crossing lands on the street either side of a junction, that the stripes run
the way the street does, and that a street carrying on is not a junction.
"""
import unittest
from types import SimpleNamespace

from PIL import Image

from generator import pz_colors as C
from generator import osm
from generator.rendering import crossings
from generator.rendering import roads


def projection():
    return SimpleNamespace(meters_per_tile=1.0,
                           to_px=lambda lat, lon: (lon, lat))


def cross_junction(split=True):
    """A nine-wide street crossing another, as OSM splits them at a junction."""
    ground = Image.new("RGB", (40, 40), C.DARK_GRASS)
    for y in range(40):
        for x in range(16, 25):
            ground.putpixel((x, y), C.MEDIUM_ASPHALT)
    for y in range(16, 25):
        for x in range(40):
            ground.putpixel((x, y), C.MEDIUM_ASPHALT)
    vegetation = Image.new("RGB", ground.size, C.VEG_NOTHING)
    tags = {"highway": "secondary"}
    if split:
        # Four ways meeting at the node, as the ways are split in OSM.
        geometry = [[(0, 20), (20, 20)], [(20, 0), (20, 20)],
                    [(20, 20), (20, 40)], [(20, 20), (40, 20)]]
    else:
        # One street carrying on: two ways split at a node, in line.
        geometry = [[(0, 20), (20, 20)], [(20, 20), (40, 20)]]
    features = [osm.OSMFeature(index, "way", tags, coords)
                for index, coords in enumerate(geometry)]
    return vegetation, ground, {"road_medium": features}


def painted(vegetation, colours):
    return {(x, y) for x in range(vegetation.width) for y in range(vegetation.height)
            if vegetation.getpixel((x, y)) in colours}


class JunctionDetection(unittest.TestCase):
    def test_a_point_where_four_ways_meet_is_a_junction(self):
        _vegetation, _ground, buckets = cross_junction()
        ways = crossings._street_ways(buckets, projection())
        self.assertEqual(crossings.junction_points(ways), [(20.0, 20.0)])

    def test_a_street_split_in_line_is_not_a_junction(self):
        _vegetation, _ground, buckets = cross_junction(split=False)
        ways = crossings._street_ways(buckets, projection())
        self.assertEqual(crossings.junction_points(ways), [])

    def test_a_side_street_ending_on_another_is_a_junction(self):
        ground = Image.new("RGB", (40, 40), C.DARK_GRASS)
        for y in range(40):
            for x in range(16, 25):
                ground.putpixel((x, y), C.MEDIUM_ASPHALT)
        for y in range(16, 25):
            for x in range(16, 40):
                ground.putpixel((x, y), C.MEDIUM_ASPHALT)
        tags = {"highway": "secondary"}
        # The through street is one way; the side street ends on its length.
        through = osm.OSMFeature(1, "way", tags, [(0, 20), (40, 20)])
        side = osm.OSMFeature(2, "way", tags, [(20, 20), (20, 40)])
        ways = crossings._street_ways({"road_medium": [through, side]}, projection())
        self.assertIn((20.0, 20.0), crossings.junction_points(ways))


class Crossings(unittest.TestCase):
    def test_stripes_run_along_each_street_just_outside_the_junction(self):
        vegetation, ground, buckets = cross_junction()
        counts = crossings.paint_crossings(vegetation, ground, buckets, projection())
        self.assertGreater(counts["crosswalk"], 0)
        # The junction box is the crossing street's width: x and y 16..24. A
        # crossing across the east-west street is a column of stripes a tile
        # or two outside it, laid as lines running east-west.
        self.assertEqual(vegetation.getpixel((27, 20)), C.LINE_WHITE_N)
        self.assertEqual(vegetation.getpixel((14, 20)), C.LINE_WHITE_N)
        # And across the north-south street, lines running north-south.
        self.assertEqual(vegetation.getpixel((20, 26)), C.LINE_WHITE_W)
        self.assertEqual(vegetation.getpixel((20, 15)), C.LINE_WHITE_W)

    def test_a_stop_line_sits_behind_each_crossing_on_the_approach_side(self):
        vegetation, ground, buckets = cross_junction()
        crossings.paint_crossings(vegetation, ground, buckets, projection())
        lines = painted(vegetation, {C.LINE_WHITE_N, C.LINE_WHITE_W})
        # Right-hand traffic: eastbound stops west of the junction on the
        # southern half, westbound stops east of it on the northern half.
        self.assertIn((11, 23), lines)
        self.assertNotIn((11, 18), lines)
        self.assertIn((30, 18), lines)
        self.assertNotIn((30, 23), lines)

    def test_a_street_carrying_on_gets_no_crossing(self):
        vegetation, ground, buckets = cross_junction(split=False)
        counts = crossings.paint_crossings(vegetation, ground, buckets, projection())
        self.assertEqual(counts, {"crosswalk": 0, "stop_line": 0, "kerb_cut": 0})
        self.assertEqual(painted(vegetation, {C.LINE_WHITE_N, C.LINE_WHITE_W}), set())

    def test_a_crossing_never_covers_a_kerb_or_a_pavement(self):
        vegetation, ground, buckets = cross_junction()
        # A kerb where a stripe would go: the crossing steps around it.
        ground.putpixel((27, 20), C.PALE_CONCRETE)
        crossings.paint_crossings(vegetation, ground, buckets, projection())
        self.assertNotEqual(vegetation.getpixel((27, 20)), C.LINE_WHITE_N)

    def test_a_crossing_drops_the_kerb_at_each_end(self):
        vegetation, ground, buckets = cross_junction()
        # Kerbs at the edge of the carriageway where the crossings come out.
        for x in (27, 14):
            for y in (15, 25):
                vegetation.putpixel((x, y), C.KERB_W)
        counts = crossings.paint_crossings(vegetation, ground, buckets, projection())
        self.assertGreater(counts["kerb_cut"], 0)
        self.assertEqual(vegetation.getpixel((27, 15)), C.VEG_NOTHING)
        self.assertEqual(vegetation.getpixel((27, 25)), C.VEG_NOTHING)

    def test_the_road_pass_lays_crossings(self):
        vegetation, ground, buckets = cross_junction()
        roads._paint_road_details(vegetation, ground, buckets, projection())
        self.assertTrue(painted(vegetation, {C.LINE_WHITE_N, C.LINE_WHITE_W}))


if __name__ == "__main__":
    unittest.main()
