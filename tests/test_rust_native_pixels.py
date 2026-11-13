"""Native pixel passes must match their Python fallbacks bit-for-bit."""
import contextlib
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageFilter

from generator import pz_colors as C
from generator import renderer
from generator.rendering import native_pixels, vegetation
from generator.roadgraph import rustsearch
from tools.regression_maps import LAT_PER_M, LON_PER_M, SOUTH, WEST, scenario_features


class NativePixelsFallback(unittest.TestCase):
    def test_missing_worker_leaves_images_unchanged(self):
        veg = Image.new("RGB", (4, 4), C.TREES)
        land = Image.new("RGB", (4, 4), C.MEDIUM_ASPHALT)
        before = veg.tobytes()
        with mock.patch.object(native_pixels, "exe", return_value=None), \
                mock.patch.object(native_pixels, "MIN_CLEAR_PIXELS", 0):
            self.assertFalse(
                native_pixels.clear_road_vegetation(
                    veg, land, (C.MEDIUM_ASPHALT,), (C.TREES,), C.VEG_NOTHING
                )
            )
        self.assertEqual(veg.tobytes(), before)

    def test_box_any_missing_worker_returns_none(self):
        with mock.patch.object(native_pixels, "exe", return_value=None), \
                mock.patch.object(native_pixels, "MIN_BOX_PIXELS", 0):
            self.assertIsNone(native_pixels.box_any(b"\x01\x00\x00\x00", 2, 2, 1))


@unittest.skipUnless(rustsearch.available(), "build rust/knoxroute for native parity")
class NativePixelsParity(unittest.TestCase):
    def setUp(self):
        self.p1 = mock.patch.object(native_pixels, "MIN_CLEAR_PIXELS", 0)
        self.p2 = mock.patch.object(native_pixels, "MIN_BOX_PIXELS", 0)
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    def test_box_any_matches_maxfilter(self):
        rng = np.random.default_rng(99)
        mask = rng.random((137, 193)) < 0.03
        img = Image.fromarray(mask.astype(np.uint8) * 255, "L")
        raw = native_pixels.box_any(img.tobytes(), 193, 137, 5)
        self.assertIsNotNone(raw)
        rs_out = np.frombuffer(raw, dtype=bool).reshape(137, 193)
        pil_out = np.asarray(img.filter(ImageFilter.MaxFilter(2 * 5 + 1))) > 0
        self.assertTrue(np.array_equal(pil_out, rs_out))

    def test_clear_road_vegetation_matches_python(self):
        w, h = 129, 260
        rng = np.random.default_rng(42)
        land_pal = np.array([C.MEDIUM_GRASS, C.MEDIUM_ASPHALT, C.PALE_CONCRETE, C.WATER], dtype=np.uint8)
        veg_pal = np.array([C.VEG_NOTHING, C.TREES, C.BUSHES, C.FLOWERS, C.TREE_BIG], dtype=np.uint8)
        land = Image.fromarray(land_pal[rng.integers(0, len(land_pal), (h, w))], "RGB")
        veg_py = Image.fromarray(veg_pal[rng.integers(0, len(veg_pal), (h, w))], "RGB")
        veg_rs = veg_py.copy()

        with mock.patch.object(native_pixels, "exe", return_value=None):
            vegetation._clear_road_vegetation(veg_py, land)
        orig_clear = native_pixels.clear_road_vegetation
        def checked_clear(*args, **kwargs):
            ok = orig_clear(*args, **kwargs)
            self.assertTrue(ok, "native clear_road_vegetation fell back to Python")
            return ok
        with mock.patch.object(native_pixels, "clear_road_vegetation", side_effect=checked_clear):
            vegetation._clear_road_vegetation(veg_rs, land)
        self.assertEqual(veg_py.tobytes(), veg_rs.tobytes())

    def test_full_render_matches_python_bit_for_bit(self):
        feats = scenario_features("village")
        with tempfile.TemporaryDirectory() as td:
            hashes = []
            for backend in ("python", "rust"):
                folder = Path(td) / backend
                ctx = (
                    mock.patch.object(native_pixels, "exe", return_value=None)
                    if backend == "python"
                    else contextlib.nullcontext()
                )
                with ctx:
                    renderer.render(
                        feats, SOUTH, WEST,
                        SOUTH + 260 * LAT_PER_M, WEST + 260 * LON_PER_M,
                        1.0, str(folder), "parity",
                    )
                hashes.append({
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in folder.iterdir()
                    if p.suffix in (".bmp", ".png") or p.name.endswith("_structures.json")
                })
            self.assertEqual(*hashes)
