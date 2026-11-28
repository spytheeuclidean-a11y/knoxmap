"""The paper map's cells stay inside what the game can index."""
import unittest

from knoxbuild import worldmap_bin as W


def square(x, y, side=3, corners=8):
    """A building-sized outline with `corners` points."""
    pts = [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]
    while len(pts) < corners:
        (ax, ay), (bx, by) = pts[-1], pts[0]
        pts.append(((ax + bx) / 2, (ay + by) / 2))
    return [pts]


class CellBudget(unittest.TestCase):
    def test_a_packed_city_cell_keeps_its_triangles_under_16_bits(self):
        # About 2,000 buildings and a few roads in one 256-tile cell, as a
        # city centre at 2 m a tile has: 16,000 points fit the old point
        # budget but triangulate to about 48,000 indices, past the 32767 the
        # game can address.
        features = [(square(x * 5, y * 5), [("building", "yes")])
                    for x in range(50) for y in range(40)]
        features += [(square(0, y * 20, side=250, corners=40), [("highway", "primary")])
                     for y in range(10)]
        kept = W._within_budget(features)
        self.assertTrue(kept)
        self.assertLessEqual(sum(W._indices(p, props) for p, props in kept), W.CELL_INDEX_BUDGET)
        self.assertLessEqual(sum(W._points(p) for p, _ in kept), W.CELL_POINT_BUDGET)
        self.assertLessEqual(W.CELL_INDEX_BUDGET, 18000)  # highest value tested in-game

    def test_an_ordinary_cell_is_left_alone(self):
        features = [(square(x * 10, y * 10), [("building", "yes")])
                    for x in range(8) for y in range(8)]
        self.assertEqual(W._within_budget(features), features)

    def test_building_heavy_cell_is_counted_with_full_zoom_copies(self):
        # 1,500 8-point buildings = 12,000 points; previously counted 1x (36,000),
        # or 10,000 points = 30,000, overflowing 16-bit buffers when PZ keeps 6x copies.
        features = [(square(x * 6, y * 6), [("building", "yes")])
                    for x in range(40) for y in range(38)]
        kept = W._within_budget(features)
        self.assertLess(len(kept), len(features))
        self.assertLessEqual(sum(W._indices(p, props) for p, props in kept), W.CELL_INDEX_BUDGET)
        self.assertLessEqual(sum(W._points(p) for p, _ in kept), W.CELL_POINT_BUDGET)

    def test_roads_stay_whole_while_buildings_can_give_way(self):
        # Simplifying a thin road outline at 3 tiles turns it into wedges and
        # spikes on the paper map (Cambourne); buildings go coarse or go first.
        road = (square(0, 100, side=250, corners=60), [("highway", "residential")])
        features = [road] + [(square(x * 6, y * 6), [("building", "yes")])
                             for x in range(40) for y in range(38)]
        kept = W._within_budget(features)
        self.assertIn(road, kept)
        self.assertLessEqual(sum(W._indices(p, props) for p, props in kept), W.CELL_INDEX_BUDGET)

    def test_footways_and_driveways_stay_off_the_paper_map(self):
        from knoxbuild.worldmap import _on_paper
        self.assertFalse(_on_paper("paved_path", {"highway": "footway"}))
        self.assertFalse(_on_paper("road_service", {"highway": "service", "service": "driveway"}))
        self.assertTrue(_on_paper("road_service", {"highway": "service", "service": "alley"}))
        self.assertTrue(_on_paper("road_minor", {"highway": "residential"}))
        self.assertTrue(_on_paper("dirt_path", {"highway": "track"}))

    def test_connected_road_segments_merge_into_continuous_polygons(self):
        from shapely.geometry import LineString
        from shapely.ops import linemerge, unary_union

        # 20 collinear segments along y=50 would be 20 polygons without merging.
        segs = [LineString([(i * 10, 50), ((i + 1) * 10, 50)]) for i in range(20)]
        merged = linemerge(unary_union(segs))
        self.assertEqual(merged.geom_type, "LineString")
        simplified = merged.simplify(0.5)
        self.assertEqual(len(simplified.coords), 2)


if __name__ == "__main__":
    unittest.main()
