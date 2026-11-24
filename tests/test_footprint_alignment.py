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

    def test_road_avoidance_moves_building_completely_clear(self):
        polygon = [(12, 12), (20, 12), (20, 20), (12, 20)]
        avoid = np.zeros((40, 40), dtype=bool)
        avoid[12:14, :] = True

        footprint, reason = place(polygon, np.zeros_like(avoid), avoid=avoid)

        self.assertEqual(reason, "ok")
        self.assertFalse(avoid[footprint.y0:footprint.y0 + footprint.height,
                               footprint.x0:footprint.x0 + footprint.width].any())

    def test_building_still_stands_where_nothing_is_clear_of_the_road(self):
        # A spot off the road is taken when there is one (the test above), but
        # where there is none the building stands on the least road it can
        # rather than being dropped. Dropping it emptied the towns: a footprint
        # that fronts a pavement cannot reach zero, and in a town most of them
        # do - the selftest's school, shop and medical building all came out
        # "0 laid out".
        polygon = [(12, 12), (20, 12), (20, 20), (12, 20)]
        avoid = np.ones((40, 40), dtype=bool)

        footprint, reason = place(polygon, np.zeros_like(avoid), avoid=avoid)

        self.assertEqual(reason, "ok")
        self.assertIsNotNone(footprint)

    def test_rectilinear_is_the_default_alignment(self):
        self.assertEqual(Settings().building_alignment, "rectilinear")
        self.assertEqual(Settings.from_dict({}).building_alignment, "rectilinear")
        self.assertEqual(Settings.from_dict({"preset": "city"}).building_alignment, "rectilinear")
        self.assertEqual(Settings.from_dict({"building_alignment": "real"}).building_alignment,
                         "real")

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

    def test_clipped_lot_rejects_thin_sliver(self):
        from knoxbuild.footprint import place

        occupied = np.zeros((40, 40), dtype=bool)
        lots = np.zeros((40, 40), dtype=bool)
        # Existing lot covers rows 12..30, leaving only a 2-tile-deep strip (10..12).
        lots[12:30, 5:35] = True
        poly = [(10.0, 10.0), (30.0, 10.0), (30.0, 18.0), (10.0, 18.0)]
        fp, reason = place(poly, occupied, min_side=3, lots=lots, alignment="rectangle")
        self.assertIsNone(fp)
        self.assertEqual(reason, "taken")


if __name__ == "__main__":
    unittest.main()
