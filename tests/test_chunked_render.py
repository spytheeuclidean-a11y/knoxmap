import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from generator import chunked, osm
from generator.rendering.noise import global_tile_offset, lattices, smooth_noise
from tools.regression_maps import LAT_PER_M, LON_PER_M, SOUTH, WEST, scenario_features
from web.checks import _beyond_this_pc, _too_big_for_memory


class ChunkedRenderTests(unittest.TestCase):
    def test_bmp_writer_24bit_and_8bit_roundtrip(self):
        rng = np.random.default_rng(123)
        rgb = rng.integers(0, 256, (10, 15, 3), dtype=np.uint8)
        gray = rng.integers(0, 256, (10, 15), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as td:
            p24 = Path(td) / "rgb.bmp"
            p8 = Path(td) / "gray.bmp"
            with chunked._BmpWriter(str(p24), 15, 10, 3) as w:
                w.write_block(0, 0, rgb[:5, :8])
                w.write_block(8, 0, rgb[:5, 8:])
                w.write_block(0, 5, rgb[5:, :8])
                w.write_block(8, 5, rgb[5:, 8:])
            with chunked._BmpWriter(str(p8), 15, 10, 1) as w:
                w.write_block(0, 0, gray[:6, :])
                w.write_block(0, 6, gray[6:, :])
            self.assertTrue(np.array_equal(np.asarray(Image.open(p24).convert("RGB")), rgb))
            self.assertTrue(np.array_equal(np.asarray(Image.open(p8).convert("L")), gray))

    def test_render_chunked_stitches_2x2_cells(self):
        feats = list(scenario_features("village"))
        feats.append(osm.OSMFeature(
            999001, "relation", {"landuse": "forest"}, [],
            role_geoms=[("outer", [
                (SOUTH + 50 * LAT_PER_M, WEST + 50 * LON_PER_M),
                (SOUTH + 120 * LAT_PER_M, WEST + 50 * LON_PER_M),
                (SOUTH + 120 * LAT_PER_M, WEST + 120 * LON_PER_M),
                (SOUTH + 50 * LAT_PER_M, WEST + 120 * LON_PER_M),
                (SOUTH + 50 * LAT_PER_M, WEST + 50 * LON_PER_M),
            ])],
        ))
        with tempfile.TemporaryDirectory() as td:
            res = chunked.render_chunked(
                feats,
                SOUTH, WEST,
                SOUTH + 550 * LAT_PER_M, WEST + 550 * LON_PER_M,
                1.0,
                td, "stitched",
                chunk_cells=1,
                halo_tiles=16,
            )
            self.assertEqual((res.width, res.height), (600, 600))
            self.assertEqual((res.cells_x, res.cells_y), (2, 2))
            for suffix in (
                ".bmp", "_veg.bmp", "_road_hierarchy.bmp",
                "_ground_base.bmp", "_veg_base.bmp", "_ZombieSpawnMap.bmp",
                "_preview.png", "_buildings.geojson", "_areas.geojson",
                "_fences.geojson", "_fence_openings.geojson",
                "_structures.json", "_places.json", "_info.json",
            ):
                self.assertTrue((Path(td) / f"stitched{suffix}").exists(), suffix)
            info = json.loads((Path(td) / "stitched_info.json").read_text(encoding="utf-8"))
            self.assertTrue(info["chunked"])
            self.assertEqual(info["chunk_count"], 4)
            with Image.open(Path(td) / "stitched.bmp") as im:
                self.assertEqual(im.size, (600, 600))

    def test_beyond_this_pc_caps_large_map_at_chunk_memory(self):
        # 16 GB PC should allow a 15000x15000 chunked map instead of requiring ~4.5 GB * N.
        with mock.patch("knoxlog.memory_status", return_value=(16 * 10**9, 8 * 10**9, 8 * 10**9)):
            self.assertIsNone(_beyond_this_pc(15000, 15000))
            self.assertIsNone(_too_big_for_memory(15000, 15000))

    def test_global_noise_matches_across_chunk_offsets(self):
        specs = [(60, 0.7), (20, 0.3)]
        with global_tile_offset(0, 0):
            lats_a = lattices(256, 256, specs, seed=42)
            a = smooth_noise(
                np.arange(100, 140, dtype=np.float32),
                np.arange(110, 160, dtype=np.float32),
                lats_a,
            )
        with global_tile_offset(90, 80):
            lats_b = lattices(128, 128, specs, seed=42)
            b = smooth_noise(
                np.arange(20, 60, dtype=np.float32),
                np.arange(20, 70, dtype=np.float32),
                lats_b,
            )
        self.assertTrue(np.allclose(a, b, atol=1e-6))

    def test_render_chunked_resumes_from_checkpoint(self):
        feats = scenario_features("village")
        with tempfile.TemporaryDirectory() as td:
            calls = 0

            ckpt_file = Path(td) / ".resumed_chunks.json"

            def stop_after_two():
                if not ckpt_file.exists():
                    return False
                try:
                    return len(json.loads(ckpt_file.read_text(encoding="utf-8")).get("done", [])) >= 2
                except Exception:
                    return False

            orig_render = chunked.R.render if hasattr(chunked, "R") else None
            self.assertIsNone(orig_render)
            import generator.renderer as R
            real_render = R.render

            def counting_render(*args, **kwargs):
                nonlocal calls
                calls += 1
                return real_render(*args, **kwargs)

            with mock.patch.object(R, "render", side_effect=counting_render):
                with self.assertRaises(Exception):
                    chunked.render_chunked(
                        feats,
                        SOUTH, WEST,
                        SOUTH + 550 * LAT_PER_M, WEST + 550 * LON_PER_M,
                        1.0,
                        td, "resumed",
                        chunk_cells=1,
                        halo_tiles=16,
                        should_stop=stop_after_two,
                    )
                self.assertTrue(ckpt_file.exists())
                done_so_far = len(json.loads(ckpt_file.read_text(encoding="utf-8")).get("done", []))
                self.assertGreaterEqual(done_so_far, 2)

                calls = 0
                res = chunked.render_chunked(
                    feats,
                    SOUTH, WEST,
                    SOUTH + 550 * LAT_PER_M, WEST + 550 * LON_PER_M,
                    1.0,
                    td, "resumed",
                    chunk_cells=1,
                    halo_tiles=16,
                )
                self.assertEqual(calls, 4 - done_so_far)
                self.assertFalse((Path(td) / ".resumed_chunks.json").exists())
                self.assertFalse((Path(td) / ".resumed_preview_wip.png").exists())
                self.assertEqual((res.width, res.height), (600, 600))


if __name__ == "__main__":
    unittest.main()
