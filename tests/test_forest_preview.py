"""The forest sliders' live preview."""
import io
import unittest

from PIL import Image

from app import app
from generator.rendering import forest_preview as P


class Preview(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def picture(self, query=""):
        res = self.client.get(f"/api/forest-preview{query}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "image/png")
        return Image.open(io.BytesIO(res.data))

    def test_a_picture(self):
        self.assertEqual(self.picture("?forest_density=1&forest_stand_m=60&forest_edge_m=6").size,
                         (2 * P.SIZE, 2 * P.SIZE))

    def test_bad_and_missing_values_still_draw(self):
        self.picture()
        self.picture("?forest_density=banana&forest_stand_m=-5&forest_edge_m=nan&tree_density=99")

    def test_settings_change_the_picture(self):
        a = self.picture("?forest_density=0.5").tobytes()
        b = self.picture("?forest_density=2").tobytes()
        self.assertNotEqual(a, b)

    def test_cached(self):
        self.assertIs(P.preview_png(1.0, 60, 6), P.preview_png(1.0, 60, 6))
