import unittest
from types import SimpleNamespace

from generator import octilinear, osm, renderer, vanilla_grid
from knoxbuild.settings import Settings


class VanillaGridLayoutTests(unittest.TestCase):
    def setUp(self):
        self.proj = SimpleNamespace(
            width=128,
            height=128,
            to_px=lambda lat, lon: (lon, lat),
            to_latlon=lambda x, y: (y, x),
        )

    def _assert_octilinear(self, pts):
        for (y0, x0), (y1, x1) in zip(pts, pts[1:]):
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            self.assertTrue(
                dx == 0 or dy == 0 or abs(dx - dy) < 1e-6,
                f"non-octilinear segment {(x0, y0)} -> {(x1, y1)}",
            )

    def test_settings_accepts_vanilla_45_grid(self):
        self.assertEqual(Settings.from_dict({"straight_roads": 5}).straight_roads, 5)

    def test_every_segment_is_0_45_or_90_degrees_and_junctions_stay_pinned(self):
        main = osm.OSMFeature(
            1, "way", {"highway": "primary"},
            [(10.0, 10.0), (15.0, 35.0), (30.0, 50.0), (45.0, 90.0)],
        )
        cross = osm.OSMFeature(
            2, "way", {"highway": "residential"},
            [(30.0, 50.0), (70.0, 50.0)],
        )
        changed = vanilla_grid.apply_vanilla_grid(
            [main, cross], self.proj, osm.classify, renderer._is_polygon
        )
        self.assertEqual(changed, 2)
        self._assert_octilinear(main.geometry)
        self._assert_octilinear(cross.geometry)
        self.assertIn((30.0, 50.0), main.geometry)
        self.assertIn((30.0, 50.0), cross.geometry)

    def test_right_angle_bend_chamfers_to_45_degrees(self):
        ramp = osm.OSMFeature(
            3, "way", {"highway": "motorway_link"},
            [(10.0, 10.0), (10.0, 40.0), (40.0, 40.0)],
        )
        vanilla_grid.apply_vanilla_grid(
            [ramp], self.proj, osm.classify, renderer._is_polygon
        )
        self._assert_octilinear(ramp.geometry)
        # Should have a 45-degree chamfer leg connecting the two axis legs.
        has_diag = any(
            abs(x1 - x0) > 0 and abs(y1 - y0) > 0 and abs(abs(x1 - x0) - abs(y1 - y0)) < 1e-6
            for (y0, x0), (y1, x1) in zip(ramp.geometry, ramp.geometry[1:])
        )
        self.assertTrue(has_diag)

    def test_diagonal_90_bend_chamfers_to_axis_leg(self):
        ramp = osm.OSMFeature(
            5, "way", {"highway": "motorway_link"},
            [(10.0, 10.0), (40.0, 40.0), (70.0, 10.0)],
        )
        vanilla_grid.apply_vanilla_grid(
            [ramp], self.proj, osm.classify, renderer._is_polygon
        )
        self._assert_octilinear(ramp.geometry)
        has_axis = any(
            abs(x1 - x0) == 0 or abs(y1 - y0) == 0
            for (y0, x0), (y1, x1) in zip(ramp.geometry, ramp.geometry[1:])
        )
        self.assertTrue(has_axis)

    def test_collapse_micro_legs_removes_tiny_interior_jogs(self):
        pts = [(0, 0), (30, 0), (32, 2), (62, 2)]
        cleaned = vanilla_grid._collapse_micro_legs(pts)
        self._assert_octilinear([(float(y), float(x)) for x, y in cleaned])
        self.assertLessEqual(len(cleaned), 3)

    def test_collapse_micro_legs_removes_corner_micro_stub(self):
        # 2-tile horizontal stub (169, 90) -> (171, 90) before vertical leg should
        # collapse cleanly into a single 45-to-90 vertex (171, 88).
        pts = [(169, 250), (90, 171), (90, 169), (169, 90), (171, 90), (171, 31)]
        cleaned = vanilla_grid._collapse_micro_legs(pts)
        self._assert_octilinear([(float(y), float(x)) for x, y in cleaned])
        self.assertNotIn((169, 90), cleaned)
        self.assertIn((171, 88), cleaned)

    def test_replay_supports_mode_5(self):
        road = osm.OSMFeature(
            4, "way", {"highway": "residential"},
            [(10.0, 10.0), (27.0, 40.0)],
        )
        n = octilinear.replay(
            [road], self.proj, osm.classify, renderer._is_polygon,
            {"straight_roads": 5}, ".", "unused",
        )
        self.assertEqual(n, 1)
        self._assert_octilinear(road.geometry)


if __name__ == "__main__":
    unittest.main()
