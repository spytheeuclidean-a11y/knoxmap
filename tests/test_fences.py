import json
import os
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from xml.etree import ElementTree

import numpy as np

from knoxbuild.fences import (STYLES, TALLER, build_fences, height_m,
                              style_for)


class FenceCollisionTests(unittest.TestCase):
    def test_mapped_fence_is_cut_around_building_footprint(self):
        with TemporaryDirectory() as directory:
            bdir = os.path.join(directory, "buildings")
            os.mkdir(bdir)
            occupied = np.zeros((16, 16), dtype=bool)
            occupied[5:8, 5:7] = True
            projection = SimpleNamespace(width=16, height=16,
                                         to_px=lambda lat, lon: (lon, lat))

            placements, count = build_fences(
                directory, "map", projection, occupied, None, bdir,
                extra=[([(2, 6), (10, 6)], "short_wooden", [])])

            self.assertTrue(placements)
            placed = set()
            for placement in placements:
                root = ElementTree.parse(os.path.join(directory, placement.tbx_path))
                for obj in root.findall(".//floor/object"):
                    x = placement.tile_x + int(obj.get("x"))
                    y = placement.tile_y + int(obj.get("y"))
                    placed.add((x, y))
            self.assertEqual(len(placed), count)
            self.assertFalse(any(occupied[y, x] for x, y in placed))


class FenceHeights(unittest.TestCase):
    """The game has a short and a tall version of most of its fences and OSM
    says which: metal bars two metres tall came out as the waist-high railing
    because a fence's height was never read."""

    def test_metal_bars_are_tall_when_the_mapper_says_they_are(self):
        self.assertEqual(style_for({"barrier": "fence", "fence_type": "metal_bars",
                                    "height": "2"}, None), "tall_metal")
        self.assertEqual(style_for({"barrier": "fence", "fence_type": "metal_bars",
                                    "height": "1"}, None), "black_metal")
        # Said nothing: as it always was.
        self.assertEqual(style_for({"barrier": "fence",
                                    "fence_type": "metal_bars"}, None), "black_metal")

    def test_the_other_fences_follow_their_height_too(self):
        for kind, tall, short in (("chain_link", "tall_chainlink", "short_chainlink"),
                                  ("wood", "tall_wooden", "short_wooden"),
                                  ("picket", "white_picket", "short_picket")):
            with self.subTest(kind=kind):
                self.assertEqual(style_for({"fence_type": kind, "height": "2.0"},
                                           "residential"), tall)
                self.assertEqual(style_for({"fence_type": kind, "height": "0.9"},
                                           "residential"), short)

    def test_a_height_is_read_however_it_was_written(self):
        self.assertAlmostEqual(height_m({"height": "2"}), 2.0)
        self.assertAlmostEqual(height_m({"height": "1.5 m"}), 1.5)
        self.assertAlmostEqual(height_m({"height": "1,8m"}), 1.8)
        self.assertAlmostEqual(height_m({"height": "6'"}), 1.8288, places=3)
        for bad in ("", "tall", "0.05", "40"):
            self.assertIsNone(height_m({"height": bad}), bad)

    def test_every_style_named_by_the_height_rule_is_a_fence_we_have(self):
        for short, (tall, _at) in TALLER.items():
            self.assertIn(short, STYLES)
            self.assertIn(tall, STYLES)


class WaysThroughAFence(unittest.TestCase):
    """A mapper draws the fence as one line and the gate as a node on it, or
    runs a footpath through it. Built from the line alone the fence walls off
    the way in."""

    def fence(self, openings, tags=None):
        directory = self.enterContext(TemporaryDirectory())
        bdir = os.path.join(directory, "buildings")
        os.mkdir(bdir)
        with open(os.path.join(directory, "map_fences.geojson"), "w") as f:
            json.dump({"features": [{
                "type": "Feature",
                "properties": tags or {"barrier": "fence", "fence_type": "wood",
                                       "height": "1.0"},
                "geometry": {"type": "LineString",
                             "coordinates": [[2, 6], [13, 6]]}}]}, f)
        with open(os.path.join(directory, "map_fence_openings.geojson"), "w") as f:
            json.dump({"type": "FeatureCollection", "features": openings}, f)
        projection = SimpleNamespace(width=16, height=16,
                                     to_px=lambda lat, lon: (lon, lat))
        placements, _count = build_fences(
            directory, "map", projection, np.zeros((16, 16), dtype=bool),
            None, bdir)
        out = {}
        for placement in placements:
            root = ElementTree.parse(os.path.join(directory, placement.tbx_path))
            names = [f.find("entry/tile").get("name")
                     for f in root.findall(".//furniture")]
            for obj in root.findall(".//floor/object"):
                out[(placement.tile_x + int(obj.get("x")),
                     placement.tile_y + int(obj.get("y")))] =                     names[int(obj.get("FurnitureTiles"))]
        return out

    def test_a_gate_node_hangs_a_gate_and_the_fence_carries_on(self):
        built = self.fence([{"type": "Feature", "properties": {"opening": "gate"},
                             "geometry": {"type": "Point", "coordinates": [7, 6]}}])
        gates = [x for (x, y), tile in built.items()
                 if tile.startswith("fixtures_doors_fences")]
        self.assertEqual(len(gates), 1, "one gate, not a gateway")
        self.assertLessEqual(abs(gates[0] - 7), 1)
        # ...and the fence either side of it is still there.
        self.assertIn((3, 6), built)
        self.assertIn((11, 6), built)

    def test_a_footpath_through_a_fence_leaves_a_hole(self):
        built = self.fence([{"type": "Feature", "properties": {"opening": "path"},
                             "geometry": {"type": "LineString",
                                          "coordinates": [[10, 2], [10, 11]]}}])
        self.assertNotIn((10, 6), built)
        self.assertIn((4, 6), built)

    def test_a_fence_with_no_gate_tile_gets_a_hole_instead(self):
        built = self.fence(
            [{"type": "Feature", "properties": {"opening": "gate"},
              "geometry": {"type": "Point", "coordinates": [7, 6]}}],
            tags={"barrier": "wall"})          # concrete: the game has no gate
        self.assertNotIn((7, 6), built)
        self.assertIn((4, 6), built)

    def test_nothing_changes_where_no_openings_were_mapped(self):
        built = self.fence([])
        # Eleven tiles of fence from x=2 to x=12, and the post it ends on.
        self.assertEqual(sorted(x for (x, y) in built if y == 6), list(range(2, 14)))


class WhoseFenceItIs(unittest.TestCase):
    """A yard fence is this program's guess; a mapped or drawn one is not.

    Reported in #bug-reports: the fences put round back yards were laid over
    the fences in OpenStreetMap and over hedges drawn in the editor, because
    the made-up ones were built last and the last one to claim an edge kept
    it.
    """

    def built(self, mapped, yard):
        directory = self.enterContext(TemporaryDirectory())
        bdir = os.path.join(directory, "buildings")
        os.mkdir(bdir)
        with open(os.path.join(directory, "map_fences.geojson"), "w") as f:
            json.dump({"features": [{
                "type": "Feature",
                "properties": {"barrier": "hedge"},
                "geometry": {"type": "LineString", "coordinates": mapped}}]}, f)
        projection = SimpleNamespace(width=16, height=16,
                                     to_px=lambda lat, lon: (lon, lat))
        placements, count = build_fences(
            directory, "map", projection, np.zeros((16, 16), dtype=bool),
            None, bdir, extra=[(yard, "white_picket", [])])
        tiles = {}
        for placement in placements:
            root = ElementTree.parse(os.path.join(directory, placement.tbx_path))
            names = [f.find("entry/tile").get("name")
                     for f in root.findall(".//furniture")]
            for obj in root.findall(".//floor/object"):
                tiles[(placement.tile_x + int(obj.get("x")),
                       placement.tile_y + int(obj.get("y")))] = \
                    names[int(obj.get("FurnitureTiles"))]
        return tiles, count

    def test_a_yard_fence_that_crosses_a_mapped_one_is_not_built(self):
        # The hedge runs across where the yard fence would go.
        tiles, count = self.built(mapped=[[2, 8], [12, 8]],
                                  yard=[(6, 4), (6, 12)])
        self.assertTrue(count, "the hedge itself should still be there")
        # Nothing of the yard fence: no tile of it above or below the hedge.
        self.assertNotIn((6, 5), tiles)
        self.assertNotIn((6, 11), tiles)

    def test_one_that_keeps_out_of_the_way_is_built_as_before(self):
        tiles, _count = self.built(mapped=[[2, 2], [12, 2]],
                                   yard=[(6, 8), (12, 8)])
        self.assertTrue(any(y >= 7 for _x, y in tiles),
                        "the yard fence should still be built")


class ParkFenceStyleTest(unittest.TestCase):
    def test_small_park_walls_and_fences_stay_short(self):
        from knoxbuild.fences import style_for

        self.assertEqual(style_for({"barrier": "wall"}, "park"), "black_metal")
        self.assertEqual(style_for({"barrier": "fence", "material": "brick"}, "park"),
                         "black_metal")
        self.assertEqual(style_for({"barrier": "fence", "material": "wood"}, "park"),
                         "short_wooden")
        self.assertEqual(style_for({"barrier": "wall", "height": "0.8"}, None),
                         "black_metal")
        # Explicit tall wall outside parks still uses tall_concrete.
        self.assertEqual(style_for({"barrier": "wall", "height": "2.2"}, None),
                         "tall_concrete")


if __name__ == "__main__":
    unittest.main()