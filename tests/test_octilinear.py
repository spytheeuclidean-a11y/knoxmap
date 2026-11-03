import inspect
import unittest
from types import SimpleNamespace

from generator import octilinear, osm, renderer
from knoxbuild.settings import Settings
from shapely.geometry import LineString, Point


class OctilinearRoadDefaults(unittest.TestCase):
    def test_straight_roads_are_default_but_can_be_disabled(self):
        self.assertEqual(Settings().straight_roads, 1)
        self.assertEqual(Settings.from_dict({}).straight_roads, 1)
        self.assertEqual(Settings.from_dict({"straight_roads": 0}).straight_roads, 0)
        # By name, not by position: counted off the end of the argument list
        # this moved every time the renderer gained a knob, and said nothing
        # about straight roads when it did.
        straight = inspect.signature(renderer.render).parameters["straight_roads"]
        self.assertEqual(straight.default, 1)

    def test_curves_become_straight_runs_and_keep_shared_junctions(self):
        projection = SimpleNamespace(
            width=128,
            height=128,
            to_px=lambda lat, lon: (lon, lat),
            to_latlon=lambda x, y: (y, x),
        )
        main = osm.OSMFeature(
            1, "way", {"highway": "primary"},
            [(10, 10), (20, 18), (30, 25), (40, 34), (50, 45)])
        side = osm.OSMFeature(
            2, "way", {"highway": "residential"},
            [(20, 18), (25, 28), (30, 38)])

        count = octilinear.straighten_roads(
            [main, side], projection, osm.classify, renderer._is_polygon)

        self.assertEqual(count, 2)
        self.assertLess(Point(*side.geometry[0]).distance(LineString(main.geometry)), 1e-8)
        for feature in (main, side):
            pixels = [projection.to_px(*point) for point in feature.geometry]
            for (x0, y0), (x1, y1) in zip(pixels, pixels[1:]):
                dx, dy = round(x1 - x0), round(y1 - y0)
                self.assertTrue(dx == 0 or dy == 0 or abs(dx) == abs(dy))


class StraighteningKnowsWhenToStop(unittest.TestCase):
    """The fit has no limit of its own on how far it may drag the town, and on
    a big map it used it: a main road at a slight angle straightened by moving
    its far end a couple of blocks, which cut the road beyond it off."""

    def projection(self, side=4000):
        return SimpleNamespace(width=side, height=side,
                               to_px=lambda lat, lon: (lon, lat),
                               to_latlon=lambda x, y: (y, x))

    def test_nothing_is_dragged_further_than_the_cap(self):
        import math

        projection = self.projection()
        # Two thousand tiles of road at three degrees: straight on the tiles
        # only if one end moves fifty tiles.
        points = [(x, 100 + x * math.tan(math.radians(3)))
                  for x in range(0, 2001, 100)]
        road = osm.OSMFeature(1, "way", {"highway": "primary"},
                              [(y, x) for x, y in points])
        octilinear.straighten_roads([road], projection, osm.classify,
                                    renderer._is_polygon)
        drawn = [projection.to_px(*p) for p in road.geometry]
        for x, y in ((0, 100.0), (2000, 204.8)):
            nearest = min(abs(y - py) for px, py in drawn if abs(px - x) < 1e-6)
            self.assertLessEqual(nearest, octilinear.MAX_MOVE_TILES)
        # ...and it is still drawn the way the game draws roads.
        for (x0, y0), (x1, y1) in zip(drawn, drawn[1:]):
            dx, dy = round(x1 - x0), round(y1 - y0)
            self.assertTrue(dx == 0 or dy == 0 or abs(dx) == abs(dy))

    def roundabout(self, tags):
        import math

        projection = self.projection(600)
        ring = [(300 + 7 * math.sin(a * math.pi / 6),
                 300 + 7 * math.cos(a * math.pi / 6)) for a in range(12)]
        ring.append(ring[0])
        arcs = [osm.OSMFeature(i, "way", dict(tags),
                               [(y, x) for x, y in ring[i * 3:i * 3 + 4]])
                for i in range(4)]
        arms = []
        for i, (dx, dy) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1))):
            at = ring[i * 3]
            far = (at[0] + dx * 180 + (4 if dy else 0), at[1] + dy * 180)
            arms.append(osm.OSMFeature(10 + i, "way", {"highway": "primary"},
                                       [(at[1], at[0]), (far[1], far[0])]))
        was = [list(arc.geometry) for arc in arcs]
        octilinear.straighten_roads(arcs + arms, projection, osm.classify,
                                    renderer._is_polygon)
        return arcs, arms, was

    def test_a_roundabout_is_left_exactly_as_it_was_drawn(self):
        # Fitted to the eight directions a roundabout came out as a few
        # crossed triangles. It has no straight sides to fit.
        arcs, arms, was = self.roundabout({"highway": "primary",
                                           "junction": "roundabout"})
        self.assertEqual([arc.geometry for arc in arcs], was)

    def test_the_roads_into_a_roundabout_still_meet_it(self):
        arcs, arms, _was = self.roundabout({"highway": "primary",
                                            "junction": "roundabout"})
        on_the_ring = {point for arc in arcs for point in arc.geometry}
        for arm in arms:
            self.assertIn(arm.geometry[0], on_the_ring)


if __name__ == "__main__":
    unittest.main()