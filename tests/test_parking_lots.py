import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image
from shapely.geometry import box

from generator import pz_colors as C
from knoxbuild.zones_detect import _detect_zones


class ParkingLotDressingTest(unittest.TestCase):
    def test_osm_parking_lot_gets_stall_lines_and_wheel_stops(self):
        w, h = 60, 60
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, "map.bmp")
            vp = os.path.join(td, "map_veg.bmp")
            land = Image.new("RGB", (w, h), C.DARK_ASPHALT)
            veg = Image.new("RGB", (w, h), C.VEG_NOTHING)
            # Pre-existing tree pixel inside the lot should be preserved.
            veg.putpixel((12, 12), C.TREES)
            land.save(lp, format="BMP")
            veg.save(vp, format="BMP")

            lot = box(6, 6, 42, 30)
            areas = SimpleNamespace(_items=[(lot, {"category": "parking"})])

            zones = _detect_zones(lp, [], areas=areas, veg_path=vp)
            stalls = [z for z in zones if z.kind == "ParkingStall"]
            self.assertGreater(len(stalls), 0)

            with Image.open(vp) as out_img:
                out = np.asarray(out_img.convert("RGB"))

            self.assertEqual(tuple(out[12, 12]), C.TREES)

            has_block = np.any(
                np.all(out == C.PARKING_BLOCK_X[0], axis=2)
                | np.all(out == C.PARKING_BLOCK_Y[0], axis=2)
            )
            has_line = np.any(
                np.all(out == C.EDGE_LINE_W, axis=2)
                | np.all(out == C.EDGE_LINE_N, axis=2)
            )
            has_island_kerb = np.any(np.all(out == C.KERB_NW, axis=2))
            has_lamp = np.any(
                np.all(out == C.LAMP_S, axis=2)
                | np.all(out == C.LAMP_E, axis=2)
            )
            has_greenery = np.any(
                np.all(out == C.BUSHES, axis=2)
                | np.all(out == C.TREE_SMALL, axis=2)
            )
            self.assertTrue(has_block)
            self.assertTrue(has_line)
            self.assertTrue(has_island_kerb)
            self.assertTrue(has_lamp)
            self.assertTrue(has_greenery)

            # No ParkingStall zone should overlap a divider island's curb or lamp.
            for z in stalls:
                patch = out[z.tile_y:z.tile_y + z.height, z.tile_x:z.tile_x + z.width]
                self.assertFalse(np.any(np.all(patch == C.KERB_NW, axis=2)))
                self.assertFalse(np.any(np.all(patch == C.LAMP_S, axis=2)))
                self.assertFalse(np.any(np.all(patch == C.LAMP_E, axis=2)))

    def test_medium_parking_lot_gets_edge_light_pole(self):
        w, h = 40, 40
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, "map.bmp")
            vp = os.path.join(td, "map_veg.bmp")
            Image.new("RGB", (w, h), C.DARK_ASPHALT).save(lp, format="BMP")
            Image.new("RGB", (w, h), C.VEG_NOTHING).save(vp, format="BMP")

            # 4 stalls wide -> no divider island, should still get an edge light pole.
            lot = box(6, 6, 20, 18)
            areas = SimpleNamespace(_items=[(lot, {"category": "parking"})])

            _detect_zones(lp, [], areas=areas, veg_path=vp)
            with Image.open(vp) as out_img:
                out = np.asarray(out_img.convert("RGB"))

            has_lamp = np.any(
                np.all(out == C.LAMP_S, axis=2)
                | np.all(out == C.LAMP_E, axis=2)
            )
            self.assertTrue(has_lamp)


if __name__ == "__main__":
    unittest.main()
