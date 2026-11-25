"""Tests for 4-quadrant chunked building generation and BMP window I/O."""
from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

import knoxfiles
from generator.osm import OSMFeature
from generator import renderer
from generator.rendering.projection import Projector
from knoxbuild import bitmaps, chunked_build, placement
from knoxbuild.build import build
from knoxbuild.buildtiles import level_tiles, parse_tbx
from knoxbuild.fences import FENCE_TILE_DEPENDENCIES, FENCE_TILE_PROFILE
from knoxbuild.settings import Settings


class BitmapWindowTests(unittest.TestCase):
    def test_read_and_write_window_roundtrip_24bit_and_8bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            rgb_path = os.path.join(tmp, "rgb.bmp")
            base = np.zeros((20, 24, 3), dtype=np.uint8)
            base[:, :] = (10, 20, 30)
            Image.fromarray(base, mode="RGB").save(rgb_path, format="BMP")

            patch = np.full((6, 8, 3), (200, 100, 50), dtype=np.uint8)
            bitmaps.write_window(rgb_path, 5, 4, patch)
            got = bitmaps.read_window(rgb_path, 5, 4, 8, 6, bits=24)
            np.testing.assert_array_equal(got, patch)
            # Outside pixels untouched
            outside = bitmaps.read_window(rgb_path, 0, 0, 4, 4, bits=24)
            self.assertTrue(np.all(outside == (10, 20, 30)))

            gray_path = os.path.join(tmp, "gray.bmp")
            gbase = np.full((16, 16), 7, dtype=np.uint8)
            Image.fromarray(gbase, mode="L").save(gray_path, format="BMP")
            gpatch = np.full((4, 5), 42, dtype=np.uint8)
            bitmaps.write_window(gray_path, 3, 2, gpatch)
            ggot = bitmaps.read_window(gray_path, 3, 2, 5, 4, bits=8)
            np.testing.assert_array_equal(ggot, gpatch)


class QuadrantBuildTests(unittest.TestCase):
    def test_should_chunk_build_threshold(self):
        self.assertFalse(chunked_build.should_chunk_build(12, 12))
        self.assertFalse(chunked_build.should_chunk_build(2, 100))
        self.assertTrue(chunked_build.should_chunk_build(13, 12))
        self.assertTrue(chunked_build.should_chunk_build(16, 16))

    def test_chunk_grid_scales_for_50x50_and_100x100_maps(self):
        self.assertEqual(chunked_build._chunk_grid(16, 16), (2, 2))     # 4 parts
        self.assertEqual(chunked_build._chunk_grid(50, 50), (4, 2))     # 8 parts
        self.assertEqual(chunked_build._chunk_grid(40, 70), (2, 4))     # 8 parts
        self.assertEqual(chunked_build._chunk_grid(100, 100), (4, 4))   # 16 parts

    def test_build_chunked_stitches_four_quadrants(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Render a 4x4 cell (1200x1200) map with 4 houses, one in each quadrant.
            south, west = 40.0, 20.0
            dlat = 1050 / 111320.0
            dlon = 1050 / (111320.0 * np.cos(np.radians(south)))
            feats = []
            # Place a road across the middle and 4 houses in NW, NE, SW, SE
            feats.append(OSMFeature(1, "way", {"highway": "residential"},
                                    [(south + 0.5 * dlat, west + 0.05 * dlon),
                                     (south + 0.5 * dlat, west + 0.95 * dlon)]))
            for idx, (fx, fy) in enumerate([(0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)], 2):
                la0 = south + (fy - 0.015) * dlat
                la1 = south + (fy + 0.015) * dlat
                lo0 = west + (fx - 0.015) * dlon
                lo1 = west + (fx + 0.015) * dlon
                feats.append(OSMFeature(idx, "way", {"building": "house"},
                                        [(la0, lo0), (la0, lo1), (la1, lo1), (la1, lo0), (la0, lo0)]))

            proj = Projector.build(south, west, south + dlat, west + dlon, 1.0)
            feats.extend([
                OSMFeature(6, "way", {"barrier": "fence", "fence_type": "bars"},
                           [proj.to_latlon(560, 150), proj.to_latlon(640, 150)]),
                OSMFeature(7, "node", {"barrier": "gate"}, [proj.to_latlon(600.5, 150)]),
            ])
            renderer.render(feats, south, west, south + dlat, west + dlon,
                            meters_per_tile=1.0, output_dir=tmp, map_name="qmap")

            # Standalone placement at (0, 0) must not be clobbered to (70, 0) by quadrant sub-builds.
            placement.save(tmp, (0, 0), standalone_flag=True)

            fence = "fencing_demo_01_0"
            gate = "fixtures_doors_fences_demo_01_0"
            profile = dict.fromkeys(("west1", "west2", "north1", "north2", "nw"), fence)
            knoxfiles.write(os.path.join(tmp, FENCE_TILE_PROFILE), {
                "mod_id": "DemoFences", "styles": {"black_metal": {
                    **profile, "gate_w": gate, "gate_n": gate}},
            })
            with mock.patch.object(chunked_build, "BUILD_CHUNK_MIN_CELLS", 4):
                rc = build(tmp, settings=Settings.from_dict({"preset": "town", "seed": 42}))
            self.assertEqual(rc, 0)
            self.assertEqual(placement.project_origin(tmp, "qmap"), (0, 0))
            self.assertEqual(placement.where_is(tmp, "qmap")["built"], (0, 0))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".quadrants")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "qmap.pzw")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "qmap_ZombieSpawnMap.bmp")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "qmap_oversized.json")))
            with open(os.path.join(tmp, "qmap_placements.csv"), newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            # Every stitched .tbx file exists in buildings/
            for r in rows:
                self.assertTrue(os.path.isfile(os.path.join(tmp, "buildings", r["file"])))
            fence_lots = [name for name in os.listdir(os.path.join(tmp, "buildings"))
                          if "_fences_" in name]
            layers = [level_tiles(parse_tbx(Path(tmp, "buildings", name).read_text(encoding="utf-8")), 0)
                      for name in fence_lots]
            pieces = [tile for lot in layers for square in lot.values() for tile in square]
            self.assertEqual(len(fence_lots), 2)
            self.assertEqual(pieces.count(gate), 1)
            self.assertEqual(pieces.count(fence), 79)
            with open(os.path.join(tmp, FENCE_TILE_DEPENDENCIES), encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"DemoFences": [fence, gate]})

    def _seam_town(self, tmp, spans):
        """A 4x4-cell map built in four parts, with a 16-tile-deep house over
        each (x0, x1) given relative to the seam between parts 0 and 1.
        Returns the placements CSV rows and the .pzw text."""
        south, west = 40.0, 20.0
        dlat = 1050 / 111320.0
        dlon = 1050 / (111320.0 * np.cos(np.radians(south)))
        feats = [OSMFeature(1, "way", {"highway": "residential"},
                            [(south + 0.5 * dlat, west + 0.05 * dlon),
                             (south + 0.5 * dlat, west + 0.95 * dlon)])]
        proj = Projector.build(south, west, south + dlat, west + dlon, 1.0)
        seam = chunked_build._quadrant_boxes(4, 4, proj.width, proj.height)[2][1][1]
        road_y = proj.to_px(south + 0.5 * dlat, west)[1]
        for idx, (x0, x1) in enumerate(spans, 2):
            x0, x1, y0, y1 = seam + x0, seam + x1, road_y - 30, road_y - 14
            ring = [proj.to_latlon(x, y) for x, y in
                    [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
            feats.append(OSMFeature(idx, "way", {"building": "house"}, ring))
        renderer.render(feats, south, west, south + dlat, west + dlon,
                        meters_per_tile=1.0, output_dir=tmp, map_name="qmap")
        placement.save(tmp, (0, 0), standalone_flag=True)
        with mock.patch.object(chunked_build, "BUILD_CHUNK_MIN_CELLS", 4):
            rc = build(tmp, settings=Settings.from_dict({"preset": "town", "seed": 42}))
        self.assertEqual(rc, 0)
        with open(os.path.join(tmp, "qmap_placements.csv"), newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with open(os.path.join(tmp, "qmap.pzw"), encoding="utf-8") as f:
            return rows, f.read()

    def test_houses_either_side_of_a_seam_do_not_share_tiles(self):
        # Each part used to be built with its own empty `occupied`, so a house
        # whose lot ran over the seam and the neighbour's house just past it
        # both claimed the same tiles. The compile then let the later lot's
        # rooms replace the earlier one's wall squares: a building with a wall
        # missing where it touched its neighbour. Each house is centred on its
        # own side of the seam, so each part builds one of them.
        with tempfile.TemporaryDirectory() as tmp:
            rows, _pzw = self._seam_town(tmp, [(-14, 6), (0, 20)])
            self.assertEqual(len(rows), 2)
            a, b = ((int(r["tile_x"]), int(r["tile_y"]), int(r["width"]), int(r["height"]))
                    for r in rows)
            overlap_x = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            overlap_y = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            self.assertFalse(overlap_x > 0 and overlap_y > 0, f"lots overlap: {a} {b}")

    def test_house_centred_past_a_seam_with_its_corner_before_it_is_kept(self):
        # Part 1 builds this house (its centre is past the seam), but its lot's
        # corner is in part 1's halo, west of the seam. Placements were kept by
        # their corner, so the house was built, listed in the CSV - and never
        # put on the map.
        with tempfile.TemporaryDirectory() as tmp:
            rows, pzw = self._seam_town(tmp, [(-8, 14)])
            self.assertEqual(len(rows), 1)
            self.assertIn(rows[0]["file"], pzw)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "buildings", rows[0]["file"])))

    def test_stitched_placements_preserve_levels_and_negative_base_level(self):
        from knoxbuild.world import Placement, render_pzw

        p = Placement("buildings/q0_b_bsmt.tbx", tile_x=10, tile_y=12,
                      width=8, height=6, on_top=False, levels=2, base_level=-2)
        stitched = Placement(
            tbx_path="buildings/q0_b_bsmt.tbx",
            tile_x=p.tile_x + 300, tile_y=p.tile_y + 300,
            width=p.width, height=p.height, on_top=p.on_top,
            levels=p.levels, base_level=p.base_level,
        )
        pzw = render_pzw(2, 2, "qmap.bmp", [stitched], "qmap")
        self.assertIn('level="-2"', pzw)

    def test_installation_basement_crossing_quadrant_edge_follows_parent(self):
        from knoxbuild.world import Placement

        # Quadrant interior starts at ix0=60 (halo hx0=0); parent sits at x=62 (inside),
        # while its installation basement shifts west by dx=-10 to x=52 (outside ix0).
        ix0, iy0, qw, qh = 60, 0, 300, 300
        parent = Placement("buildings/school_0001.tbx", tile_x=62, tile_y=20, width=16, height=16)
        bsmt = Placement("buildings/school_0001_bsmt.tbx", tile_x=52, tile_y=15,
                         width=30, height=26, levels=1, base_level=-1)
        kept_parents = {
            os.path.basename(p.tbx_path)[:-4]
            for p in (parent, bsmt)
            if not os.path.basename(p.tbx_path).endswith("_bsmt.tbx")
            and ix0 <= p.tile_x < ix0 + qw and iy0 <= p.tile_y < iy0 + qh
        }
        kept = [
            p for p in (parent, bsmt)
            if (os.path.basename(p.tbx_path)[:-len("_bsmt.tbx")] in kept_parents
                if os.path.basename(p.tbx_path).endswith("_bsmt.tbx")
                else (ix0 <= p.tile_x < ix0 + qw and iy0 <= p.tile_y < iy0 + qh))
        ]
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[1].base_level, -1)


if __name__ == "__main__":
    unittest.main()
