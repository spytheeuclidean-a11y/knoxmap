"""Tests for the 2.5D isometric game view endpoints."""
import json
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
