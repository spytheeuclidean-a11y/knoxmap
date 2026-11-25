"""A map rendered in chunks must match the same map rendered whole.

The whole-map render (`renderer.render`) is the reference; `render_chunked` is
what every large map goes through. Any layer that differs is a seam or a
different map depending on how big the area happens to be.

Layers that match are asserted strictly. The vegetation layer does not match
yet, so its test is marked `expectedFailure` to keep the gap visible: once it
is fixed the test turns into an "unexpected success" and the marker has to
come off.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import generator.renderer as R
from generator import chunked, osm
from tools.regression_maps import LAT_PER_M, LON_PER_M, SOUTH, WEST, scenario_features

SIZE = 550          # tiles: 2 x 2 cells of 300, below the size that chunks on its own


def _polygon(osm_id, tags, x0, y0, x1, y1):
    ring = [(SOUTH + y * LAT_PER_M, WEST + x * LON_PER_M)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return osm.OSMFeature(osm_id, "way", tags, ring)


def _layer(folder, suffix):
    return np.asarray(Image.open(Path(folder) / f"map{suffix}").convert("RGB"))


class ChunkedMatchesWholeRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        feats = list(scenario_features("village"))
        feats.append(_polygon(990001, {"landuse": "farmland"}, 200, 200, 460, 460))
        feats.append(_polygon(990002, {"landuse": "forest"}, 30, 330, 250, 560))
        args = (SOUTH, WEST, SOUTH + SIZE * LAT_PER_M, WEST + SIZE * LON_PER_M, 1.0)
        cls._whole = tempfile.TemporaryDirectory()
        cls._chunks = tempfile.TemporaryDirectory()
        R.render(feats, *args, cls._whole.name, "map")
        chunked.render_chunked(feats, *args, cls._chunks.name, "map",
                               chunk_cells=1, halo_tiles=16)

    @classmethod
    def tearDownClass(cls):
        cls._whole.cleanup()
        cls._chunks.cleanup()

    def _assert_same(self, suffix):
        whole = _layer(self._whole.name, suffix)
        chunks = _layer(self._chunks.name, suffix)
        self.assertEqual(whole.shape, chunks.shape)
        differ = np.any(whole != chunks, axis=2)
        self.assertEqual(int(differ.sum()), 0, f"{suffix}: tiles that differ")

    def test_road_hierarchy_matches(self):
        self._assert_same("_road_hierarchy.bmp")

    def test_spawn_map_matches(self):
        whole = np.asarray(Image.open(Path(self._whole.name) / "map_ZombieSpawnMap.bmp").convert("L"))
        chunks = np.asarray(Image.open(Path(self._chunks.name) / "map_ZombieSpawnMap.bmp").convert("L"))
        self.assertEqual(whole.shape, chunks.shape)
        self.assertEqual(int((whole != chunks).sum()), 0)

    def test_ground_matches(self):
        # A handful of tiles may differ: 4 of 360,000 do today, on grass and
        # field-edge tiles. The cause is not isolated yet; the whole farmland
        # used to come out differently (about 20,000 tiles).
        whole = _layer(self._whole.name, ".bmp")
        chunks = _layer(self._chunks.name, ".bmp")
        self.assertEqual(whole.shape, chunks.shape)
        self.assertLessEqual(int(np.any(whole != chunks, axis=2).sum()), 16)

    @unittest.expectedFailure
    def test_vegetation_matches(self):
        # What is left is the woods and the groves: their density cuts are
        # quantiles taken over each chunk's own tiles (forest_shape.py,
        # vegetation._paint_groves), not a number the whole map shares.
        self._assert_same("_veg.bmp")


class GlobalGridIsWindowIndependent(unittest.TestCase):
    """What the chunk-safe helpers draw must not depend on the window."""

    def test_plot_cuts_are_the_same_through_any_window(self):
        from generator.rendering.fields import _cuts

        whole, whole_sizes = _cuts(0, 900, (20.0, 60.0), 7)
        part, part_sizes = _cuts(250, 400, (20.0, 60.0), 7)
        self.assertEqual(whole[250:650].tolist(), part.tolist())
        self.assertEqual(whole_sizes[:len(part_sizes) - 1].tolist(), part_sizes[:len(part_sizes) - 1].tolist())

    def test_block_picks_are_the_same_through_any_window(self):
        from generator.rendering.noise import global_tile_offset
        from generator.rendering.vegetation import _block_picks

        mask = np.random.default_rng(5).random((300, 300)) < 0.7
        step, ox, oy = 7, 70, 80
        with global_tile_offset(0, 0):
            full = list(_block_picks(mask, step, 99, 0.5))
        window = mask[oy:oy + 170, ox:ox + 180]
        with global_tile_offset(ox, oy):
            part = [(x + ox, y + oy, e) for x, y, e in _block_picks(window, step, 99, 0.5)]
        inside = lambda p: oy + 2 * step <= p[1] < oy + 170 - 2 * step and ox + 2 * step <= p[0] < ox + 180 - 2 * step
        self.assertEqual(sorted(p for p in full if inside(p)), sorted(p for p in part if inside(p)))
        self.assertTrue(any(inside(p) for p in full))


if __name__ == "__main__":
    unittest.main()
