"""WorldCover lands where it really is, on a turned map and an upright one."""
import unittest

import numpy as np

from generator.rendering import landcover as L
from generator.rendering.projection import Projector

SOUTH, WEST, NORTH, EAST = 45.0, -69.0, 45.004, -68.994


def halves(width, height, bounds=None):
    """West of the bbox's middle meridian 10, east of it 30; north of its
    middle parallel adds 1 - so a tile's class says where it is."""
    s, w, n, e = bounds
    lon = w + (np.arange(width) + 0.5) / width * (e - w)
    lat = n - (np.arange(height) + 0.5) / height * (n - s)
    grid = np.where(lon[None, :] < (WEST + EAST) / 2, 10, 30)
    grid = grid + (lat[:, None] > (SOUTH + NORTH) / 2)
    return grid.astype("uint8")


class GridForMapTest(unittest.TestCase):
    def check(self, rotation):
        proj = Projector.build(SOUTH, WEST, NORTH, EAST, 1.0, rotation)
        grid = L.grid_for_map(halves, proj)
        self.assertEqual(grid.shape, (proj.height, proj.width))
        rng = np.random.default_rng(1)
        px = rng.uniform(0, proj.width, 2000)
        py = rng.uniform(0, proj.height, 2000)
        lat, lon = proj.to_latlon_many(px, py)
        want = np.where(lon < (WEST + EAST) / 2, 10, 30) + (lat > (SOUTH + NORTH) / 2)
        got = grid[py.astype(int), px.astype(int)]
        # Off by a tile at most along the two dividing lines.
        self.assertGreater((got == want).mean(), 0.99)

    def test_upright(self):
        self.check(0.0)

    def test_turned(self):
        self.check(-11.5)
        self.check(30.0)

    def test_many_matches_one(self):
        proj = Projector.build(SOUTH, WEST, NORTH, EAST, 1.0, 20.0)
        lat, lon = proj.to_latlon_many(np.array([10.0, 250.0]), np.array([30.0, 400.0]))
        for i, (x, y) in enumerate(((10.0, 30.0), (250.0, 400.0))):
            la, lo = proj.to_latlon(x, y)
            self.assertAlmostEqual(lat[i], la, places=9)
            self.assertAlmostEqual(lon[i], lo, places=9)


if __name__ == "__main__":
    unittest.main()
