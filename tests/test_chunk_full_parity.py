"""A map rendered in chunks must match the same map rendered whole.

The whole-map render (`renderer.render`) is the reference; `render_chunked` is
what every large map goes through. Any layer that differs is a seam or a
different map depending on how big the area happens to be.

Layers that match today are asserted strictly. Layers that do not are marked
`expectedFailure` so the gap stays visible: once one is fixed its test turns
into an "unexpected success" and the marker has to come off.
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

    @unittest.expectedFailure
    def test_ground_matches(self):
        # Observed: the farmland (and a few village tiles) come out differently.
        self._assert_same(".bmp")

    @unittest.expectedFailure
    def test_vegetation_matches(self):
        # Observed: well over half of the vegetation tiles differ.
        self._assert_same("_veg.bmp")


if __name__ == "__main__":
    unittest.main()
