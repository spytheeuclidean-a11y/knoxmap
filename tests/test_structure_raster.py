"""The fast centre test must cover exactly the same tiles as scalar GEOS."""
import math
import unittest

from shapely.geometry import LineString, Point, Polygon, box

from generator.structures import _covered_tiles, _cells


class StructureRasterTests(unittest.TestCase):
    def test_matches_scalar_predicate_in_row_order(self):
        shapes = [box(.5, .5, 9.5, 10.5), box(-8, -9, -2, -1),
                  LineString([(-3, 4), (15, 20)]).buffer(2),
                  Polygon([(0, 0), (12, 0), (12, 12), (0, 12)],
                          holes=[[(2, 2), (2, 8), (8, 8), (8, 2)]]),
                  box(0, 0, 2, 2).union(box(5, 5, 8, 8))]
        for shape in shapes:
            with self.subTest(shape=shape.wkt):
                expected = [(x, y) for y in range(-10, 25) for x in range(-10, 25)
                            if shape.contains(Point(x + .5, y + .5))]
                self.assertEqual(list(_covered_tiles(shape, -10, -10, 25, 25)), expected)

    def test_clips_to_requested_bounds(self):
        self.assertEqual(list(_covered_tiles(box(-10, -10, 10, 10), 0, 0, 2, 2)),
                         [(0, 0), (1, 0), (0, 1), (1, 1)])
        self.assertEqual(list(_covered_tiles(box(0, 0, 5, 5), 4, 0, 4, 5)), [])

    def test_monument_centroid_fallback_and_boundary(self):
        self.assertEqual(_cells(box(1.1, 1.1, 1.2, 1.2)), [(1, 1)])
        shape = box(.5, .5, 3.5, 3.5)
        x0, y0, x1, y1 = (math.floor(v) for v in shape.bounds)
        expected = [(x, y) for y in range(y0, y1+1) for x in range(x0, x1+1)
                    if shape.contains(Point(x+.5, y+.5))]
        self.assertEqual(_cells(shape), expected)
