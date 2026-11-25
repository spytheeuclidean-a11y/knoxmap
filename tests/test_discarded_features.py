"""Mapped things the pipeline used to drop or flatten into something else.

Three answers were decided here by what Project Zomboid does with a colour,
not by how the ground looks: a colour carries the game's behaviour with it.
`C.WATER` is swimming, no spawns and no street furniture, so a drainage ditch
cannot borrow it. A rail tile is steel and gravel, so a disused bed cannot keep
it. `PALE_CONCRETE` is a walkway the railings follow, so a breakwater cannot
keep it.
"""
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.osm import OSMFeature, classify, rail_is_disused
from generator.rendering import landcover, rails, roads, widths


class _Proj:
    meters_per_tile = 1.0
    width = 60
    height = 40


def _classify(tags, area=False):
    return classify(dict(tags), area)


def _rail_colours():
    return {C.RAIL_NE_SW, C.RAIL_NW_SE, C.RAIL_NE_SW_W, C.RAIL_NE_SW_E,
            C.RAIL_NW_SE_N, C.RAIL_NW_SE_S}


class Drainage(unittest.TestCase):
    """A ditch holds water and is not the open water of a river."""

    def test_every_drainage_value_is_its_own_category(self):
        for value in ("drain", "ditch", "dam", "weir"):
            with self.subTest(value=value):
                self.assertEqual(_classify({"waterway": value}), "drainage")

    def test_a_river_is_still_water(self):
        for value in ("river", "riverbank", "canal", "stream"):
            with self.subTest(value=value):
                self.assertEqual(_classify({"waterway": value}), "water")

    def test_drainage_is_painted_a_dry_channel_and_not_open_water(self):
        # Not C.WATER: that colour is how every pass below knows to keep
        # zombies out, turn doors away and stand no furniture.
        self.assertIn("drainage", landcover.LANDSCAPE_ORDER)
        self.assertEqual(landcover.LANDSCAPE_FILL["drainage"], C.CLAY)
        self.assertNotEqual(landcover.LANDSCAPE_FILL["drainage"], C.WATER)
        self.assertIn(landcover.LANDSCAPE_FILL["drainage"], C.LANDSCAPE_COLORS)

    def test_a_drainage_line_is_drawn_narrower_than_a_river(self):
        # Without a width of its own a ditch is drawn at the 3 m fallback, as
        # wide as a lane, right across the field it drains.
        self.assertIn("drain", landcover.WATERWAY_WIDTH_M)
        self.assertIn("ditch", landcover.WATERWAY_WIDTH_M)
        self.assertLessEqual(landcover.WATERWAY_WIDTH_M["drain"],
                             landcover.WATERWAY_WIDTH_M["stream"])


class Breakwater(unittest.TestCase):
    """A wave barrier is rock, not a walkway with a railing."""

    def test_a_breakwater_and_a_groyne_are_their_own_category(self):
        for value in ("breakwater", "groyne"):
            with self.subTest(value=value):
                self.assertEqual(_classify({"man_made": value}), "breakwater")

    def test_a_pier_is_still_a_pier(self):
        self.assertEqual(_classify({"man_made": "pier"}), "pier")

    def test_a_breakwater_is_rock_and_not_the_concrete_of_a_pier(self):
        self.assertIn("breakwater", landcover.LANDSCAPE_ORDER)
        self.assertEqual(landcover.LANDSCAPE_FILL["breakwater"], C.GRAVEL_DIRT)
        self.assertNotEqual(landcover.LANDSCAPE_FILL["breakwater"],
                            landcover.LANDSCAPE_FILL["pier"])
        self.assertIn(landcover.LANDSCAPE_FILL["breakwater"], C.LANDSCAPE_COLORS)

    def test_a_breakwater_is_wider_than_a_pier(self):
        # It is a wall of stone with a road along its top, not a jetty.
        self.assertIn("breakwater", widths.ROAD_WIDTHS_M)
        self.assertGreater(widths.ROAD_WIDTHS_M["breakwater"],
                           widths.ROAD_WIDTHS_M["pier"])


class DisusedTrack(unittest.TestCase):
    """A track carrying no trains keeps its bed and loses its steel."""

    def test_disused_and_preserved_are_disused(self):
        for value in ("disused", "preserved"):
            with self.subTest(value=value):
                self.assertTrue(rail_is_disused({"railway": value}))
                self.assertEqual(_classify({"railway": value}), "railway")

    def test_a_working_railway_is_not_disused(self):
        for value in ("rail", "light_rail", "narrow_gauge"):
            with self.subTest(value=value):
                self.assertFalse(rail_is_disused({"railway": value}))

    def test_the_bed_of_a_disused_track_is_overgrown(self):
        self.assertEqual(landcover.DISUSED_RAIL_FILL, C.DIRT_GRASS)
        self.assertNotEqual(landcover.DISUSED_RAIL_FILL, landcover.LANDSCAPE_FILL["railway"])
        self.assertIn(landcover.DISUSED_RAIL_FILL, C.LANDSCAPE_COLORS)

    def test_no_steel_is_laid_on_a_disused_bed(self):
        img = Image.new("RGB", (60, 40), C.MEDIUM_GRASS)
        feat = OSMFeature(1, "way", {"railway": "disused"}, [[0.0, 0.0], [0.0, 1.0]])
        with mock.patch.object(rails, "_feature_coords_px",
                              return_value=[[(5, 20), (50, 20)]]):
            roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]}, _Proj())
        painted = {img.getpixel((x, y)) for x in range(60) for y in range(40)}
        self.assertEqual(painted & _rail_colours(), set())

    def test_a_working_track_still_gets_its_steel(self):
        # The other half of the same branch: what was right stays right.
        img = Image.new("RGB", (60, 40), C.DIRT)
        feat = OSMFeature(1, "way", {"railway": "rail"}, [[0.0, 0.0], [0.0, 1.0]])
        with mock.patch.object(rails, "_feature_coords_px",
                              return_value=[[(5, 20), (50, 20)]]):
            roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]}, _Proj())
        painted = {img.getpixel((x, y)) for x in range(60) for y in range(40)}
        self.assertTrue(painted & _rail_colours())

    def test_a_disused_line_comes_out_overgrown_and_without_rail_tiles(self):
        from generator import renderer
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0018, -84.9978
        proj = Projector.build(south, west, north, east, 1.0, 0.0)
        disused = OSMFeature(1, "way", {"railway": "disused"}, [
            proj.to_latlon(20, 75), proj.to_latlon(130, 75),
        ])
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([disused], south, west, north, east,
                                  meters_per_tile=1.0, output_dir=out, map_name="ds")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
        band = {tuple(px) for row in land[68:83] for px in row}
        self.assertEqual(band & _rail_colours(), set())
        self.assertIn(C.DIRT_GRASS, band)


class Rendered(unittest.TestCase):
    """The three, painted: the categories above are only worth what they lay."""

    def test_a_drain_comes_out_clay_and_never_water(self):
        from generator import renderer
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0012, -84.9985
        proj = Projector.build(south, west, north, east, 1.0, 0.0)
        drain = OSMFeature(1, "way", {"waterway": "drain"},
                           [proj.to_latlon(5, 30), proj.to_latlon(80, 30)])
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([drain], south, west, north, east,
                                  meters_per_tile=1.0, output_dir=out, map_name="dr")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
        row = {tuple(int(v) for v in px) for px in land[30]}
        self.assertIn(C.CLAY, row)
        self.assertNotIn(C.WATER, row)

    def test_a_breakwater_gets_no_railing(self):
        # plan_piers rails what stands over water to walk along. A wave
        # barrier is not something you walk along.
        from generator import structures
        from generator.rendering.projection import Projector

        proj = Projector.build(40.0, -85.0, 40.0012, -84.9985, 1.0, 0.0)
        for value in ("breakwater", "groyne"):
            with self.subTest(value=value):
                feat = OSMFeature(1, "way", {"man_made": value},
                                  [proj.to_latlon(20, 10), proj.to_latlon(20, 60)])
                plan = structures.Plan()
                structures.plan_piers({"breakwater": [feat]}, proj, 1.0,
                                      widths._way_width_m, plan)
                self.assertEqual(plan.water_rails, [])

    def test_a_disused_track_mapped_as_an_area_is_overgrown_too(self):
        from generator import renderer
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0012, -84.9985
        proj = Projector.build(south, west, north, east, 1.0, 0.0)
        yard = OSMFeature(1, "way", {"railway": "disused"}, [
            proj.to_latlon(20, 20), proj.to_latlon(60, 20),
            proj.to_latlon(60, 50), proj.to_latlon(20, 50),
            proj.to_latlon(20, 20),
        ])
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render([yard], south, west, north, east,
                                  meters_per_tile=1.0, output_dir=out, map_name="da")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
        painted = {tuple(int(v) for v in px) for row in land for px in row}
        self.assertIn(C.DIRT_GRASS, painted)
        self.assertEqual(painted & _rail_colours(), set())

    def test_a_working_area_after_a_disused_one_keeps_its_own_colour(self):
        # The disused colour used to be written into the category's fill and
        # left there, so this depended on the order the ways arrived in.
        from generator import renderer
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0018, -84.9978
        proj = Projector.build(south, west, north, east, 1.0, 0.0)

        def yard(fid, value, x0, y0, x1, y1):
            return OSMFeature(fid, "way", {"railway": value}, [
                proj.to_latlon(x0, y0), proj.to_latlon(x1, y0),
                proj.to_latlon(x1, y1), proj.to_latlon(x0, y1),
                proj.to_latlon(x0, y0),
            ])

        feats = [yard(1, "disused", 10, 10, 40, 40), yard(2, "rail", 50, 50, 80, 80)]
        with tempfile.TemporaryDirectory() as out:
            res = renderer.render(feats, south, west, north, east,
                                  meters_per_tile=1.0, output_dir=out, map_name="ord")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
        self.assertEqual(tuple(int(v) for v in land[25, 25]), C.DIRT_GRASS)
        self.assertEqual(tuple(int(v) for v in land[65, 65]), C.DIRT)

    def test_the_chunked_path_lays_no_steel_on_a_disused_bed(self):
        # The chunked renderer plans every rail section up front and paints
        # them from that plan; a filter only on the whole-map path would leave
        # the bigger maps laying steel.
        from generator.chunked import render_chunked
        from generator.rendering.projection import Projector

        south, west, north, east = 40.0, -85.0, 40.0012, -84.9985
        proj = Projector.build(south, west, north, east, 1.0, 0.0)
        disused = OSMFeature(1, "way", {"railway": "disused"},
                             [proj.to_latlon(20, 10), proj.to_latlon(20, 90)])
        with tempfile.TemporaryDirectory() as out:
            res = render_chunked([disused], south, west, north, east, 1.0, out, "ck")
            land = np.asarray(Image.open(res.landscape_path).convert("RGB"))
        painted = {tuple(int(v) for v in px) for row in land for px in row}
        self.assertEqual(painted & _rail_colours(), set())
        self.assertIn(C.DIRT_GRASS, painted)


if __name__ == "__main__":
    unittest.main()
