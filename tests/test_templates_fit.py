"""A long link must not make every template comparison quadratic."""
import unittest

import shapely

from generator.roadgraph import templates


class Sampling(unittest.TestCase):
    def test_a_long_line_is_sampled_at_most_max(self):
        real = shapely.LineString([(0, y) for y in range(0, 40000, 2)])
        pts = templates._samples(real)
        self.assertLessEqual(len(pts), templates.MAX_SAMPLES)

    def test_a_short_line_keeps_every_sample(self):
        real = shapely.LineString([(0, y) for y in range(0, 40, 2)])
        pts = templates._samples(real)
        self.assertGreater(len(pts), 5)


if __name__ == "__main__":
    unittest.main()
