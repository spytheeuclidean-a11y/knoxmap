"""The shared smooth noise, and the colours fields and rock fields paint."""
import unittest

import numpy as np

from generator import pz_colors as C
from generator.rendering import noise


class SmoothNoiseTest(unittest.TestCase):
    def field(self, seed=1):
        lats = noise.lattices(120, 160, [(20, 1.0)], seed)
        return noise.smooth_noise(np.arange(120, dtype=np.float32),
                                  np.arange(160, dtype=np.float32), lats)

    def test_range_and_shape(self):
        n = self.field()
        self.assertEqual(n.shape, (120, 160))
        self.assertGreaterEqual(float(n.min()), 0.0)
        self.assertLessEqual(float(n.max()), 1.0)

    def test_deterministic(self):
        self.assertTrue(np.array_equal(self.field(5), self.field(5)))
        self.assertFalse(np.array_equal(self.field(5), self.field(6)))

    def test_smooth(self):
        n = self.field()
        self.assertLess(float(np.abs(np.diff(n, axis=1)).max()), 0.2)
        self.assertLess(float(np.abs(np.diff(n, axis=0)).max()), 0.2)


class NewColoursTest(unittest.TestCase):
    def test_unique(self):
        new = {"DIRT_ROWS_H", "DIRT_ROWS_V", "CORN_1", "CORN_2", "BOULDERS", "ROCKS"}
        values = {name: getattr(C, name) for name in dir(C)
                  if name.isupper() and isinstance(getattr(C, name), tuple)
                  and len(getattr(C, name)) == 3}
        for name in new:
            clash = [other for other, v in values.items()
                     if other != name and v == values[name]]
            self.assertEqual(clash, [], name)
        for name in ("DIRT_ROWS_H", "DIRT_ROWS_V"):
            self.assertIn(values[name], C.LANDSCAPE_COLORS)
        for name in ("CORN_1", "CORN_2", "BOULDERS", "ROCKS"):
            self.assertIn(values[name], C.VEGETATION_COLORS)


if __name__ == "__main__":
    unittest.main()
