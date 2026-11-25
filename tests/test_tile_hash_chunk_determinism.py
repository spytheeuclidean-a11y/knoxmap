"""Per-tile hashes must pick the same result for a world tile in any chunk.

Each test renders a full grid inside ``global_tile_offset(0, 0)`` (the origin
chunk) and compares it with a sub-window rendered inside
``global_tile_offset(ox, oy)``. Only the per-tile id fed to ``hash01`` is
allowed to differ between the runs, so each input is built to keep the other
chunk-dependent parts (plot cuts, centroid seeds, quantile thresholds) equal.
"""
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import fields as F
from generator.rendering import homesteads as H
from generator.rendering.noise import global_tile_offset


class P:
    meters_per_tile = 1.0


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def diff_count(a, b):
    return int(np.any(a != b, axis=2).sum())


class PolygonFieldTufts(unittest.TestCase):
    """A small field is one plot (pid constant), so only the tufts' ids can differ."""

    SIZE = 300
    BOX = (100, 100, 160, 150)        # field rectangle in full-grid tiles

    def _run(self, x0, y0, w, h, shift):
        land = Image.new("RGB", (w, h), C.LIGHT_GRASS)
        veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
        bx0, by0, bx1, by1 = self.BOX
        bx0, bx1 = bx0 + shift, bx1 + shift
        ring = rect(bx0 - x0, by0 - y0, bx1 - x0, by1 - y0)
        with global_tile_offset(x0, y0):
            F.paint_fields(land, veg, P(), [ring], None)
        return np.asarray(veg)

    def test_window_matches_full_grid(self):
        # Slide the field along until its plot lies fallow, so it grows tufts
        # (a field's plot is chosen from its global position).
        for shift in range(40):
            full = self._run(0, 0, self.SIZE, self.SIZE, shift)
            if (full == np.array(C.SHORT_GRASS)).all(axis=2).sum() > 50:
                break
        else:
            self.fail("no fallow plot among 40 positions")
        x0, y0, w, h = 90, 95, 100, 80
        win = self._run(x0, y0, w, h, shift)
        self.assertEqual(diff_count(win, full[y0:y0 + h, x0:x0 + w]), 0)


class CroplandTileIds(unittest.TestCase):
    """The plot cuts depend on the window width, so assert on the ids handed
    to ``_paint_plots`` rather than on pixels."""

    def _captured(self, w, h, ox, oy):
        seen = []
        real = F._paint_plots

        def spy(land, vegp, field, pid, furrow_h, tile_ids, salt):
            seen.append(tile_ids.copy())
            return real(land, vegp, field, pid, furrow_h, tile_ids, salt)

        land = Image.new("RGB", (w, h), C.LIGHT_GRASS)
        veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
        with mock.patch.object(F, "_paint_plots", spy), global_tile_offset(ox, oy):
            F.paint_fields(land, veg, P(), [], np.ones((h, w), dtype=bool))
        return seen

    def test_ids_are_global_whatever_the_width(self):
        ox, oy = 1234, 5678
        h = 600
        starts = {max(0, t - 1) for t in range(0, h, F.STRIP_ROWS)}
        for w in (120, 170):
            seen = self._captured(w, h, ox, oy)
            self.assertTrue(seen)
            for ids in seen:
                gy, gx = ids >> 32, ids & 0xFFFFFFFF
                self.assertTrue((gx == ox + np.arange(w)[None, :]).all())
                self.assertTrue((gy == gy[0:1, :] + np.arange(len(ids))[:, None]).all())
                self.assertIn(int(gy[0, 0]) - oy, starts)


class RockTiles(unittest.TestCase):
    """`_threshold` is patched to a constant so the noise gate is open
    everywhere and only the per-tile hashes decide rocks, boulders and bushes."""

    SIZE = 200

    def _run(self, grid, ox, oy):
        h, w = grid.shape
        owned = np.ones((h, w), dtype=bool)
        land = Image.new("RGB", (w, h), C.DIRT)
        veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
        with mock.patch.object(F, "_threshold", return_value=-1.0), \
                global_tile_offset(ox, oy):
            F.paint_rocks(land, veg, P(), grid, owned)
        return np.asarray(veg)

    def test_window_matches_full_grid(self):
        grid = np.full((self.SIZE, self.SIZE), 100, dtype="uint8")
        grid[:, 100:] = 60
        full = self._run(grid, 0, 0)
        self.assertTrue((full == np.array(C.ROCKS)).all(axis=2).any())
        y0, y1, x0, x1 = 40, 160, 30, 170
        win = self._run(grid[y0:y1, x0:x1], x0, y0)
        self.assertEqual(diff_count(win, full[y0:y1, x0:x1]), 0)


class HomesteadEdgeThinning(unittest.TestCase):
    """The clearing shape comes from a centroid-derived seed, so it cannot be
    compared across windows; assert on the ids handed to the edge-thinning hash."""

    HOUSE = [(60, 60), (72, 60), (72, 70), (60, 70)]

    def _edge_ids(self, w, h, ox, oy):
        land = Image.new("RGB", (w, h), C.DARK_GRASS)
        veg = Image.new("RGB", (w, h), C.TREES)
        calls = []
        real = H.hash01

        def spy(values, salt):
            if salt == H.HOME_SEED + 1:
                calls.append(values.copy())
            return real(values, salt)

        with mock.patch.object(H, "hash01", spy), global_tile_offset(ox, oy):
            H.clear_homesteads(veg, land, [self.HOUSE], [], 1.0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_ids_do_not_depend_on_width(self):
        a = self._edge_ids(150, 150, 0, 0)
        b = self._edge_ids(190, 150, 0, 0)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_ids_carry_the_chunk_offset(self):
        ox, oy = 1000, 2000
        a = self._edge_ids(150, 150, 0, 0)
        b = self._edge_ids(150, 150, ox, oy)
        self.assertEqual((b - a).tolist(), np.full(a.shape, (oy << 32) + ox).tolist())


if __name__ == "__main__":
    unittest.main()
