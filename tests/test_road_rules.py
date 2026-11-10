"""Tests for road detail rules patching, curb catalogues, and B42 compatibility."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image

import knoxpaths
from worlded import patch_rules_roads
import knoxmap_setup


class RoadRulesTests(unittest.TestCase):
    def test_patch_rules_roads_b42_soil_resilience(self):
        """Build 42 lacks floors_exterior_natural_01_18; ensure Yard bed_soil rule survives."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir()
            rules_file = cfg / "Rules.txt"
            # Start with CRLF and older litter rule containing trash_01_13
            rules_file.write_text(
                "rule\r\n{\r\n    label = KnoxMap road Litter\r\n    bitmap = 1\r\n"
                "    color = 12 36 208\r\n    tiles = [\r\n        trash_01_0\r\n"
                "        trash_01_13\r\n    ]\r\n    layer = 0_FloorOverlay6\r\n}\r\n",
                encoding="utf-8",
            )

            two_x = root / "Tiles" / "2x"
            two_x.mkdir(parents=True)
            # Simulate B42 floors_exterior_natural_01.png where 18 is blank
            img = Image.new("RGBA", (8 * 128, 7 * 256), (0, 0, 0, 0))
            arr = np.array(img)
            for idx in [8, 9, 10, 11, 16, 17]:
                r, c = divmod(idx, 8)
                arr[r * 256 : (r + 1) * 256, c * 128 : (c + 1) * 128, 3] = 255
            Image.fromarray(arr).save(two_x / "floors_exterior_natural_01.png")

            ret = patch_rules_roads.main(["patch_rules_roads.py", str(root)])
            self.assertEqual(ret, 0)

            txt = rules_file.read_text(encoding="utf-8")
            self.assertNotIn("trash_01_13", txt)
            self.assertIn("KnoxMap road Yard bed_soil", txt)
            self.assertIn("floors_exterior_natural_01_16", txt)
            self.assertTrue(knoxpaths.road_rules_ok(root))

    def test_ensure_road_catalogue(self):
        """Verify ensure_road_catalogue adds curb and marking sheets to empty catalogue."""
        with tempfile.TemporaryDirectory() as tmp:
            tilesets = Path(tmp) / "Tilesets.txt"
            tilesets.write_text("version = 1\n", encoding="utf-8")
            knoxmap_setup.ensure_road_catalogue(tilesets)

            content = tilesets.read_text(encoding="utf-8")
            self.assertIn("street_curbs_01", content)
            self.assertIn("street_trafficlines_01", content)
            self.assertIn("floors_exterior_natural_01", content)


if __name__ == "__main__":
    unittest.main()
