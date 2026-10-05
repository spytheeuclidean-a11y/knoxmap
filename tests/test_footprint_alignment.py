import unittest

import numpy as np
from shapely.affinity import rotate, translate
from shapely.geometry import Point, Polygon

from knoxbuild.footprint import place, rectilinearize_polygon
from knoxbuild.settings import Settings


class BuildingAlignment(unittest.TestCase):
    def setUp(self):
        l_shape = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
        self.shape = translate(rotate(l_shape, 27, origin="centroid"),
                               xoff=30, yoff=30)
        self.coords = list(self.shape.exterior.coords)

    def place(self, alignment):
        result, reason = place(self.coords, np.zeros((80, 80), dtype=bool),
                               alignment=alignment)
        self.assertEqual(reason, "ok")
        return result

    def test_rectilinear_keeps_l_outline_and_removes_diagonal_steps(self):
        real = self.place("real")
        rectilinear = self.place("rectilinear")
        real_left = [np.flatnonzero(row)[0] for row in real.mask if row.any()]
        rect_left = [np.flatnonzero(row)[0] for row in rectilinear.mask if row.any()]
        widths = [np.count_nonzero(row) for row in rectilinear.mask if row.any()]
        self.assertGreater(len(set(real_left)), 1)
        self.assertEqual(len(set(rect_left)), 1)
        self.assertGreater(len(set(widths)), 1)

    def test_rectangle_fills_the_rotated_bounds(self):
        rectilinear = self.place("rectilinear")
        rectangle = self.place("rectangle")
        self.assertLess(rectilinear.tiles, rectangle.tiles * 0.8)
        self.assertTrue(rectangle.mask.all())

    def test_smart_rectifies_near_grid_l_but_keeps_strong_diagonal(self):
        source = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
        near = translate(rotate(source, 6, origin="centroid"), xoff=30, yoff=30)
        far = translate(rotate(source, 27, origin="centroid"), xoff=30, yoff=30)
        near_smart, _ = place(list(near.exterior.coords), np.zeros((80, 80), dtype=bool),
                              snap_degrees=8, alignment="smart")
        far_smart, _ = place(list(far.exterior.coords), np.zeros((80, 80), dtype=bool),
                             snap_degrees=8, alignment="smart")
        far_real, _ = place(list(far.exterior.coords), np.zeros((80, 80), dtype=bool),
                            alignment="real")
        left_edges = [np.flatnonzero(row)[0] for row in near_smart.mask if row.any()]
        widths = [np.count_nonzero(row) for row in near_smart.mask if row.any()]
        self.assertEqual(len(set(left_edges)), 1)
        self.assertGreater(len(set(widths)), 1)
        np.testing.assert_array_equal(far_smart.mask, far_real.mask)

    def test_entrance_point_follows_rectilinearized_outline(self):
        footprint = self.place("rectilinear")
        source_point = self.shape.exterior.coords[0]
        moved_point = footprint.transform_point(*source_point)
        aligned = rectilinearize_polygon(self.shape)
        self.assertLess(Point(*moved_point).distance(aligned.boundary), 1e-6)

    def test_rectilinear_simplification_removes_small_jogs(self):
        rough = Polygon([(0, 0), (10, 0), (10, 4), (9, 4), (9, 5),
                         (10, 5), (10, 10), (0, 10)])
        clean = rectilinearize_polygon(rough)
        self.assertLess(len(clean.exterior.coords), len(rough.exterior.coords))
        self.assertLessEqual(abs(clean.area - rough.area), 1.0)

    def test_legacy_angle_settings_migrate(self):
        self.assertEqual(Settings.from_dict({"square_buildings": 0}).building_alignment,
                         "real")
        self.assertEqual(Settings.from_dict({"square_buildings": 15}).building_alignment,
                         "smart")
        self.assertEqual(Settings.from_dict({"square_buildings": 45}).building_alignment,
                         "rectangle")
        self.assertEqual(Settings.from_dict({"straight_roads": 1}).building_alignment,
                         "rectangle")
        self.assertEqual(Settings.from_dict({"building_alignment": "rectilinear",
                                             "square_buildings": 0}).building_alignment,
                         "rectilinear")

    def test_settings_api_exposes_alignment_choices(self):
        from app import app

        response = app.test_client().get("/api/settings")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["types"]["building_alignment"], "enum")
        self.assertEqual([value for value, _label in body["options"]["building_alignment"]],
                         ["real", "smart", "rectilinear", "rectangle"])

    def test_alignment_is_a_name_not_a_number(self):
        from app import app
        from knoxbuild.settings import LIMITS

        self.assertIs(type(Settings().building_alignment), str)
        self.assertNotIn("building_alignment", LIMITS)
        body = app.test_client().get("/api/settings").get_json()
        self.assertNotIn("building_alignment", body["limits"])
        self.assertEqual(body["current"]["building_alignment"], "smart")
        # A number is not a choice: the default stays.
        for junk in (2, "2", 1.5, True, None):
            self.assertEqual(Settings.from_dict({"building_alignment": junk})
                             .building_alignment, "smart", junk)


if __name__ == "__main__":
    unittest.main()
