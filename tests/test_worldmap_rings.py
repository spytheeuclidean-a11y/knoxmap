"""Polygons in worldmap.xml are whole tiles, and rounding must not break them.

A ring that repeats a point, has no area or crosses itself after rounding
crashed the game's paper map (IndexOutOfBoundsException in
WorldMapRenderer.fillPolygon). knoxbuild/worldmap._cell_ring writes only rings
that are still polygons once rounded.
"""
import unittest

from shapely.geometry import Polygon

from knoxbuild.worldmap import _cell_ring


def valid_ring(ring):
    return (len(ring) >= 3 and len(set(ring)) == len(ring)
            and Polygon(ring).is_valid and Polygon(ring).area >= 1)


class CellRings(unittest.TestCase):
    def test_a_plain_square_is_written_as_it_is(self):
        self.assertEqual(_cell_ring(Polygon([(310, 20), (320, 20), (320, 30), (310, 30)]), 300, 0),
                         [(10, 20), (20, 20), (20, 30), (10, 30)])

    def test_points_rounded_together_are_written_once(self):
        ring = _cell_ring(Polygon([(0, 0), (0.2, 0.1), (10, 0), (10, 10), (0, 10)]), 0, 0)
        self.assertTrue(valid_ring(ring), ring)

    def test_a_strip_rounded_flat_is_left_out(self):
        # a road strip under a tile wide: every point rounds onto one line
        self.assertIsNone(_cell_ring(Polygon([(0, 0.1), (20, 0.2), (20, 0.4), (0, 0.3)]), 0, 0))

    def test_a_ring_rounded_into_crossing_itself_is_mended_or_left_out(self):
        # a thin bow whose waist crosses over once rounded
        poly = Polygon([(0, 0), (10, 0.6), (20, 0), (20, 2), (10, 1.4), (0, 2)])
        ring = _cell_ring(poly, 0, 0)
        self.assertTrue(ring is None or valid_ring(ring), ring)


if __name__ == "__main__":
    unittest.main()
