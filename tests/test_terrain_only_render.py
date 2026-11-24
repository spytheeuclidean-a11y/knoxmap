import json
import os
import tempfile
import unittest

from generator import renderer
from tools.selftest import EAST, NORTH, SOUTH, WEST, box, way


class TerrainOnlyRender(unittest.TestCase):
    def test_a_terrain_only_map_is_written_with_no_homes_from_addresses(self):
        feats = [way({"highway": "residential", "name": "First Street"}, [(40, 100), (400, 100)]),
                 way({"building": "house"}, box(60, 110, 71, 122))]
        with tempfile.TemporaryDirectory() as out:
            renderer.render(feats, SOUTH, WEST, NORTH, EAST, meters_per_tile=2.0,
                            output_dir=out, map_name="t", terrain_only=True)
            with open(os.path.join(out, "t_info.json"), encoding="utf-8") as f:
                info = json.load(f)
        self.assertEqual(info["houses_from_addresses"], 0)
        self.assertEqual(info["building_count"], 0)


if __name__ == "__main__":
    unittest.main()
