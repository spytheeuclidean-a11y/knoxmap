import os
import tempfile
import unittest
from unittest import mock

from generator import msbuildings

BOX = (35.955, -83.925, 35.965, -83.915)
SQUARE = [[-83.92, 35.96], [-83.9199, 35.96], [-83.9199, 35.9601],
          [-83.92, 35.9601], [-83.92, 35.96]]


class MicrosoftBuildings(unittest.TestCase):
    def test_knox_county_quadkey(self):
        self.assertEqual(msbuildings.quadkeys(*BOX), ["032003002"])

    def test_box_across_tiles_gets_every_tile(self):
        self.assertGreater(len(msbuildings.quadkeys(35.0, -85.0, 37.0, -83.0)), 1)

    def test_touches(self):
        shape = {"type": "Polygon", "coordinates": [SQUARE]}
        self.assertTrue(msbuildings._touches(shape, *BOX))
        self.assertFalse(msbuildings._touches(shape, 10, 10, 11, 11))

    def test_add_missing_fills_and_caches(self):
        rows = [{"id": None, "height": 5.0, "levels": None, "class": None,
                 "geometry": {"type": "Polygon", "coordinates": [SQUARE]}}]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(msbuildings, "fetch", return_value=rows) as f:
            feats, stats = msbuildings.add_missing([], BOX, d, "m")
            self.assertEqual(stats["added"], 1)
            self.assertEqual(feats[0].tags["height"], "5")
            self.assertTrue(os.path.exists(msbuildings.cache_path(d, "m")))
            _, again = msbuildings.add_missing([], BOX, d, "m")
            self.assertTrue(again["cached"])
            self.assertEqual(f.call_count, 1)


if __name__ == "__main__":
    unittest.main()
