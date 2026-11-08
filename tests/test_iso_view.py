"""Tests for the 2.5D isometric game view endpoints."""
import unittest
from app import app


class IsoViewEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_iso_info_unknown_map(self):
        resp = self.client.get("/api/iso-info/NonExistentMapName12345")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_iso_info_compiled_map(self):
        resp = self.client.get("/api/iso-info/Bum_Bum")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["name"], "Bum_Bum")
        self.assertTrue(data["compiled"])
        self.assertGreater(data["width_tiles"], 0)
        self.assertGreater(data["height_tiles"], 0)
        self.assertIn("pictures", data)

    def test_iso_render_unknown_map(self):
        resp = self.client.get("/api/iso-render/NonExistentMapName12345")
        self.assertEqual(resp.status_code, 404)

    def test_iso_render_invalid_box(self):
        resp = self.client.get("/api/iso-render/Bum_Bum?box=invalid,coords")
        self.assertEqual(resp.status_code, 400)

    def test_iso_render_cached_box(self):
        # Request a valid box render
        resp = self.client.get("/api/iso-render/Bum_Bum?box=1000,1000,20,20&scale=1.0&roofs=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 1000)

        # Second request should be served from cache
        resp_cached = self.client.get("/api/iso-render/Bum_Bum?box=1000,1000,20,20&scale=1.0&roofs=1")
        self.assertEqual(resp_cached.status_code, 200)
        self.assertEqual(resp_cached.data, resp.data)

    def test_iso_render_custom_rectangular_box_with_interiors(self):
        # Request a non-square area with furnished interiors (roofs=0)
        resp = self.client.get("/api/iso-render/Bum_Bum?box=1100,950,40,30&scale=1.0&roofs=0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 1000)

    def test_iso_render_custom_rectangular_box_with_roofs(self):
        # Request the same area with roofs (roofs=1)
        resp = self.client.get("/api/iso-render/Bum_Bum?box=1100,950,40,30&scale=1.0&roofs=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/png")
        self.assertGreater(len(resp.data), 1000)


if __name__ == "__main__":
    unittest.main()
