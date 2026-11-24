import math
import unittest

from generator.rendering.infill import MIN_SIDE_TILES, _squared


def lot(cx, cy, w, d, degrees):
    """A w x d lot, its width along a direction `degrees` from the x axis."""
    t = math.radians(degrees)
    tx, ty, nx, ny = math.cos(t), math.sin(t), -math.sin(t), math.cos(t)
    hw, hd = w / 2, d / 2
    return [(cx - tx * hw - nx * hd, cy - ty * hw - ny * hd),
            (cx + tx * hw - nx * hd, cy + ty * hw - ny * hd),
            (cx + tx * hw + nx * hd, cy + ty * hw + ny * hd),
            (cx - tx * hw + nx * hd, cy - ty * hw + ny * hd)]


def on_axes(c):
    xs = sorted({round(x, 6) for x, _y in c})
    ys = sorted({round(y, 6) for _x, y in c})
    return len(xs) == 2 and len(ys) == 2


class Squared(unittest.TestCase):
    def test_an_axis_lot_is_unchanged(self):
        c = _squared(lot(50, 50, 12, 9, 0), 1.0)
        self.assertTrue(on_axes(c))
        self.assertAlmostEqual(c[1][0] - c[0][0], 12)
        self.assertAlmostEqual(c[3][1] - c[0][1], 9)

    def test_a_slightly_turned_lot_is_turned_square_and_keeps_its_size(self):
        c = _squared(lot(50, 50, 12, 9, 5), 1.0)
        self.assertTrue(on_axes(c))
        self.assertAlmostEqual(c[1][0] - c[0][0], 12)
        self.assertAlmostEqual(c[3][1] - c[0][1], 9)

    def test_a_lot_up_a_street_is_squared_the_other_way_round(self):
        c = _squared(lot(50, 50, 12, 9, 92), 1.0)
        self.assertTrue(on_axes(c))
        self.assertAlmostEqual(c[1][0] - c[0][0], 9)
        self.assertAlmostEqual(c[3][1] - c[0][1], 12)

    def test_a_diagonal_lot_becomes_the_biggest_axis_rectangle_inside_it(self):
        from shapely.geometry import Polygon
        original = lot(50, 50, 16, 10, 45)
        c = _squared(original, 1.0)
        self.assertTrue(on_axes(c))
        self.assertTrue(Polygon(original).buffer(1e-6).contains(Polygon(c)))
        self.assertGreater(Polygon(c).area, 0.25 * Polygon(original).area)

    def test_a_lot_too_small_to_build_is_refused(self):
        self.assertIsNone(_squared(lot(50, 50, 12, MIN_SIDE_TILES - 1, 0), 1.0))
        self.assertIsNone(_squared(lot(50, 50, 6, 5, 45), 1.0))


if __name__ == "__main__":
    unittest.main()
