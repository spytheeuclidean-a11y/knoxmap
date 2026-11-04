"""The data-layer status/refresh endpoints (offline)."""
import unittest

from app import app


class DatasetsApi(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_status_lists_all_layers(self):
        response = self.client.get("/api/datasets/status")
        self.assertEqual(response.status_code, 200)
        layers = response.get_json()["layers"]
        self.assertEqual(set(layers), {"worldcover", "elevation_3dep",
                                       "natural_earth", "hifld_hospitals",
                                       "climate_normals"})

    def test_status_uses_the_area_for_coverage(self):
        response = self.client.get(
            "/api/datasets/status?south=40&west=-75&north=40.1&east=-74.9")
        self.assertEqual(response.status_code, 200)
        layers = response.get_json()["layers"]
        self.assertTrue(layers["hifld_hospitals"]["available"])   # US
        eu = self.client.get(
            "/api/datasets/status?south=51&west=-1&north=51.1&east=-0.9").get_json()
        self.assertFalse(eu["layers"]["hifld_hospitals"]["available"])

    def test_refresh_needs_a_bbox(self):
        response = self.client.post("/api/datasets/refresh", json={})
        self.assertEqual(response.status_code, 400)

    def test_refresh_rejects_an_inverted_bbox(self):
        response = self.client.post("/api/datasets/refresh", json={
            "south": 40.1, "west": -74.9, "north": 40.0, "east": -75.0})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
