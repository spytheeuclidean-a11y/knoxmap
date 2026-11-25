"""plant_landcover must pick the same growth for a world tile in any chunk."""
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import landcover_veg as LV
from generator.rendering.noise import global_tile_offset

SIZE = 200


class P:
    meters_per_tile = 1.0


def make_grid():
    grid = np.full((SIZE, SIZE), LV.WETLAND[0], dtype="uint8")
    grid[:, :67] = LV.SHRUB
    grid[:, 67:134] = LV.GRASS
    return grid


def run(grid, offset=None):
    h, w = grid.shape
    owned = np.ones((h, w), dtype=bool)
    veg = Image.new("RGB", (w, h), (0, 0, 0))
    land = Image.new("RGB", (w, h), C.DARK_GRASS)

    def go():
        LV.plant_landcover(veg, land, grid, owned, P())

    if offset is None:
        go()
    else:
        with global_tile_offset(*offset):
            go()
    return np.asarray(veg), np.asarray(land)


class ChunkDeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grid = make_grid()
        # The full grid is itself rendered at the world origin, like chunk (0, 0).
        cls.full_veg, cls.full_land = run(cls.grid, (0, 0))

    def _compare(self, y0, y1, x0, x1):
        veg, land = run(self.grid[y0:y1, x0:x1], (x0, y0))
        bad_veg = int(np.any(veg != self.full_veg[y0:y1, x0:x1], axis=2).sum())
        bad_land = int(np.any(land != self.full_land[y0:y1, x0:x1], axis=2).sum())
        self.assertEqual(bad_veg, 0, "veg pixels differ from full grid")
        self.assertEqual(bad_land, 0, "landscape pixels differ from full grid")

    def test_window_matches_full_grid(self):
        self._compare(50, 150, 50, 150)

    def test_same_width_different_row_origin(self):
        self._compare(50, 150, 0, SIZE)

    def test_no_offset_is_deterministic(self):
        a_veg, a_land = run(self.grid)
        b_veg, b_land = run(self.grid)
        self.assertEqual(a_veg.tobytes(), b_veg.tobytes())
        self.assertEqual(a_land.tobytes(), b_land.tobytes())


if __name__ == "__main__":
    unittest.main()
