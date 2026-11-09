"""Tests for the 2.5D isometric game view endpoints."""
import json
import os
import shutil
import unittest
from unittest.mock import patch
from PIL import Image
from app import app
from web.common import OUTPUT_DIR


class IsoViewEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_map_name = "_test_iso_map"
        cls.map_dir = OUTPUT_DIR / cls.test_map_name
        cls.lots_dir = cls.map_dir / "lots"
        cls.pics_dir = cls.map_dir / "pictures"
        cls.lots_dir.mkdir(parents=True, exist_ok=True)
        cls.pics_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy lotheader so map is recognized as compiled
        (cls.lots_dir / "10_10.lotheader").write_bytes(b"lotheader")

        # Create dummy info file
        info = {
            "width_tiles": 300,
            "height_tiles": 300,
            "cells_x": 1,
            "cells_y": 1,
            "building_count": 5,
        }
        (cls.map_dir / f"{cls.test_map_name}_info.json").write_text(json.dumps(info), encoding="utf-8")

        # Create dummy town overview picture
        dummy_pic = Image.new("RGBA", (100, 100), (40, 120, 40, 255))
        dummy_pic.save(cls.pics_dir / "town.png")

        # Mock render_lots.render to return a valid PIL image without requiring actual lots files
        cls.render_patcher = patch("tools.render_lots.render")
        cls.mock_render = cls.render_patcher.start()
        cls.mock_render.return_value = Image.new("RGBA", (200, 150), (100, 150, 200, 255))

    @classmethod
    def tearDownClass(cls):
        cls.render_patcher.stop()
        if cls.map_dir.is_dir():
            shutil.rmtree(cls.map_dir, ignore_errors=True)

    def setUp(self):
        self.client = app.test_client()

    def test_iso_info_unknown_map(self):
        resp = self.client.get("/api/iso-info/NonExistentMapName12345")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_iso_info_compiled_map(self):
        resp = self.client.get(f"/api/iso-info/{self.test_map_name}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["name"], self.test_map_name)
        self.assertTrue(data["compiled"])
        self.assertEqual(data["width_tiles"], 300)
        self.assertEqual(data["height_tiles"], 300)
        self.assertEqual(data["building_count"], 5)
        self.assertIn("pictures", data)

    def test_iso_render_unknown_map(self):
        resp = self.client.get("/api/iso-render/NonExistentMapName12345")
        self.assertEqual(resp.status_code, 404)

    def test_iso_render_invalid_box(self):
        resp = self.client.get(f"/api/iso-render/{self.test_map_name}?box=invalid,coords")
        self.assertEqual(resp.status_code, 400)

    def test_iso_render_cached_box(self):
        # Request a valid box render
        resp = self.client.get(f"/api/iso-render/{self.test_map_name}?box=100,100,20,20&scale=1.0&roofs=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 100)

        # Second request should be served from cache
        resp_cached = self.client.get(f"/api/iso-render/{self.test_map_name}?box=100,100,20,20&scale=1.0&roofs=1")
        self.assertEqual(resp_cached.status_code, 200)
        self.assertEqual(resp_cached.data, resp.data)

    def test_iso_render_custom_rectangular_box_with_interiors(self):
        # Request a non-square area with furnished interiors (roofs=0)
        resp = self.client.get(f"/api/iso-render/{self.test_map_name}?box=120,80,40,30&scale=1.0&roofs=0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 100)

    def test_iso_render_custom_rectangular_box_with_roofs(self):
        # Request the same area with roofs (roofs=1)
        resp = self.client.get(f"/api/iso-render/{self.test_map_name}?box=120,80,40,30&scale=1.0&roofs=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 100)


if __name__ == "__main__":
    unittest.main()


class IsoRenderCache(unittest.TestCase):
    """A recompiled map must not be served from the old render's cache."""

    def setUp(self):
        self.name = "_test_iso_cache"
        self.map_dir = OUTPUT_DIR / self.name
        (self.map_dir / "lots").mkdir(parents=True, exist_ok=True)
        (self.map_dir / "lots" / "10_10.lotheader").write_bytes(b"lotheader")
        self.client = app.test_client()
        self.patch = patch("tools.render_lots.render",
                           return_value=Image.new("RGBA", (40, 40), (10, 20, 30, 255)))
        self.render = self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.map_dir, ignore_errors=True)

    def _ask(self):
        return self.client.get(f"/api/iso-render/{self.name}?box=0,0,20,20")

    def test_a_newer_lot_file_draws_a_new_picture(self):
        self.assertEqual(self._ask().status_code, 200)
        self.assertEqual(self.render.call_count, 1)
        self.assertEqual(self._ask().status_code, 200)
        self.assertEqual(self.render.call_count, 1, "the second request came from cache")
        lot = self.map_dir / "lots" / "10_10.lotheader"
        os.utime(lot, ns=(lot.stat().st_atime_ns, lot.stat().st_mtime_ns + 10 ** 9))
        self.assertEqual(self._ask().status_code, 200)
        self.assertEqual(self.render.call_count, 2, "a recompile must not reuse the old render")


class IsoLargeSelection(unittest.TestCase):
    """A box bigger than 200 tiles is drawn whole at a smaller scale."""

    def setUp(self):
        self.name = "_test_iso_big"
        self.map_dir = OUTPUT_DIR / self.name
        (self.map_dir / "lots").mkdir(parents=True, exist_ok=True)
        (self.map_dir / "lots" / "10_10.lotheader").write_bytes(b"lotheader")
        self.client = app.test_client()
        self.patch = patch("tools.render_lots.render",
                           return_value=Image.new("RGBA", (40, 40), (10, 20, 30, 255)))
        self.render = self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.map_dir, ignore_errors=True)

    def test_a_wide_box_keeps_its_width_and_gives_up_sharpness(self):
        r = self.client.get(f"/api/iso-render/{self.name}?box=0,0,400,400&scale=1.0")
        self.assertEqual(r.status_code, 200)
        x, y, w, h = self.render.call_args.args[1:5]
        self.assertEqual((w, h), (400, 400), "the box was cropped instead of drawn whole")
        scale = self.render.call_args.kwargs["scale"]
        self.assertAlmostEqual(scale, 412 / 800, places=2)

    def test_a_box_at_the_ceiling_keeps_full_scale(self):
        self.client.get(f"/api/iso-render/{self.name}?box=0,0,200,200&scale=1.0")
        self.assertEqual(self.render.call_args.kwargs["scale"], 1.0)
