import json
import math
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image
from shapely.geometry import box

from generator import pz_colors as C
from generator import renderer
from generator.osm import OSMFeature, classify
from generator.rendering.geometry import _is_polygon
from generator.rendering.parking import square_parking_lots
from generator.rendering.projection import Projector
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

            with mock.patch("knoxbuild.yards._rule_ready", return_value=True):
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


class ParkingLotSquaringTest(unittest.TestCase):
    SOUTH, WEST, NORTH, EAST = 40.0, -85.0, 40.0027, -84.9965

    @staticmethod
    def _ring_latlon(proj: Projector, pts_px: list[tuple[float, float]]):
        ring = [proj.to_latlon(x, y) for x, y in pts_px]
        ring.append(ring[0])
        return ring

    def test_angled_splotch_parking_renders_as_orthogonal_rectangle(self):
        proj = Projector.build(self.SOUTH, self.WEST, self.NORTH, self.EAST, 1.0, 0.0)
        # 28-degree rotated blobby 36x22 parking lot around (120, 120).
        cx, cy = 120.0, 120.0
        angle = math.radians(28)
        ca, sa = math.cos(angle), math.sin(angle)
        local_blob = [
            (-18, -10), (-4, -13), (12, -11), (20, -6),
            (17, 10), (3, 12), (-14, 9), (-21, 1),
        ]
        pts_px = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in local_blob]
        lot = OSMFeature(10, "way", {"amenity": "parking"}, self._ring_latlon(proj, pts_px))
        road = OSMFeature(11, "way", {"highway": "residential"},
                          [proj.to_latlon(165, 20), proj.to_latlon(165, 220)])
        bldg_pts = [(105, 160), (145, 160), (145, 185), (105, 185)]
        bldg = OSMFeature(12, "way", {"building": "retail"}, self._ring_latlon(proj, bldg_pts))

        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([lot, road, bldg],
                                  self.SOUTH, self.WEST, self.NORTH, self.EAST,
                                  meters_per_tile=1.0, output_dir=out, map_name="lot")
            with open(os.path.join(out, "lot_areas.geojson"), encoding="utf-8") as f:
                areas = json.load(f)
            parking_feats = [ft for ft in areas["features"]
                             if ft["properties"].get("category") == "parking"]
            self.assertEqual(len(parking_feats), 1)
            coords = parking_feats[0]["geometry"]["coordinates"][0][0]
            px_coords = [proj.to_px(lat, lon) for lon, lat in coords]
            self.assertEqual(len(px_coords), 5)
            for (x0, y0), (x1, y1) in zip(px_coords, px_coords[1:]):
                self.assertTrue(abs(x1 - x0) < 1e-3 or abs(y1 - y0) < 1e-3,
                                f"non-orthogonal parking edge {(x0, y0)} -> {(x1, y1)}")

            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
            # Interior is painted DARK_ASPHALT while sidewalk along the road stays intact.
            self.assertEqual(tuple(land[120, 120]), C.DARK_ASPHALT)
            self.assertIn(C.PALE_CONCRETE, [tuple(land[120, x]) for x in range(158, 165)])

    def test_l_shaped_parking_keeps_orthogonal_arms_without_swallowing_building(self):
        proj = Projector.build(self.SOUTH, self.WEST, self.NORTH, self.EAST, 1.0, 0.0)
        # Slightly ragged L-shape hugging north and west sides of an inner courtyard.
        l_pts = [
            (40, 40), (95, 42), (96, 63), (62, 62),
            (61, 98), (39, 97), (40, 62),
        ]
        lot = OSMFeature(20, "way", {"amenity": "parking"}, self._ring_latlon(proj, l_pts))
        courtyard_bldg = OSMFeature(
            21, "way", {"building": "yes"},
            self._ring_latlon(proj, [(65, 65), (95, 65), (95, 95), (65, 95)]),
        )
        feats = [lot, courtyard_bldg]
        changed = square_parking_lots(feats, proj, classify, _is_polygon)
        self.assertEqual(changed, 1)
        px_rings = [[proj.to_px(la, lo) for la, lo in ring]
                    for role, ring in (feats[0].role_geoms or [("outer", feats[0].geometry)])
                    if role == "outer"]
        self.assertGreater(len(px_rings[0]), 5)
        for ring in px_rings:
            for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
                self.assertTrue(abs(x1 - x0) < 1e-3 or abs(y1 - y0) < 1e-3)
        from shapely.geometry import Point, Polygon
        poly = Polygon(px_rings[0])
        self.assertFalse(poly.contains(Point(80, 80)))

    def test_squaring_preserves_public_sidewalk_under_overlapping_lot(self):
        proj = Projector.build(self.SOUTH, self.WEST, self.NORTH, self.EAST, 1.0, 0.0)
        lot_pts = [(80, 80), (140, 82), (138, 120), (78, 118)]
        lot = OSMFeature(30, "way", {"amenity": "parking"}, self._ring_latlon(proj, lot_pts))
        road = OSMFeature(31, "way", {"highway": "secondary"},
                          [proj.to_latlon(135, 60), proj.to_latlon(135, 140)])
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([lot, road],
                                  self.SOUTH, self.WEST, self.NORTH, self.EAST,
                                  meters_per_tile=1.0, output_dir=out, map_name="sw")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
            # Road is centered at x=135; its west sidewalk should not be eaten by parking asphalt.
            west_row = [tuple(land[100, x]) for x in range(125, 136)]
            self.assertIn(C.PALE_CONCRETE, west_row)


if __name__ == "__main__":
    unittest.main()
