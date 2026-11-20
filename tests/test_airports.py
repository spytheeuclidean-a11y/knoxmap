"""Airports: the runway, what taxis along it, and the ground it stands on.

An airfield used to come out as a field with a few service roads on it -
`aeroway` was neither downloaded nor painted, so the one piece of a town a
player can see from anywhere was the one piece that was not there.

A runway is drawn like a road and is nothing like one: thirty metres of
concrete that everything else gives way to, on mown grass that nothing grows
on. Those two facts are what these check.
"""
import io
import os
import unittest

from generator import osm
from generator.osm import classify
from generator.rendering.landcover import (AREA_CATEGORIES, GREEN_CATEGORIES,
                                           LANDSCAPE_FILL, LANDSCAPE_ORDER)
from generator.rendering.widths import (MAX_TAGGED_WIDTH_M, ROAD_WIDTHS_M,
                                        RUNWAY_SHOULDER_M, _road_markings,
                                        _way_width_m)
from generator import pz_colors as C

AIRPORT = ("runway", "taxiway", "apron", "airfield")


class Way:
    """Enough of an OSMFeature for the width rules."""

    def __init__(self, **tags):
        self.tags = tags


class WhatTheMapCallsIt(unittest.TestCase):
    def test_the_parts_of_an_airfield(self):
        for tags, cat in (({"aeroway": "runway"}, "runway"),
                          ({"aeroway": "landingstrip"}, "runway"),
                          ({"aeroway": "taxiway"}, "taxiway"),
                          ({"aeroway": "taxilane"}, "taxiway"),
                          ({"aeroway": "apron"}, "apron"),
                          ({"aeroway": "helipad"}, "apron")):
            with self.subTest(tags=tags):
                self.assertEqual(osm.classify(tags, area=False), cat)
                self.assertEqual(osm.classify(tags, area=True), cat)

    def test_the_aerodrome_is_ground_and_not_a_line(self):
        # The boundary of an airport is a polygon; drawn as a line it would
        # be a concrete ring road round the whole field.
        self.assertEqual(osm.classify({"aeroway": "aerodrome"}, area=True),
                         "airfield")
        self.assertIsNone(osm.classify({"aeroway": "aerodrome"}, area=False))

    def test_a_terminal_is_a_building_rather_than_ground(self):
        for value in ("terminal", "hangar", "tower"):
            with self.subTest(value=value):
                self.assertIsNone(osm.classify({"aeroway": value}, area=True))

    def test_they_are_asked_for_in_the_download(self):
        query = "\n".join(osm.FEATURE_QUERIES) if hasattr(osm, "FEATURE_QUERIES") \
            else open(osm.__file__, encoding="utf-8").read()
        for value in ("runway", "taxiway", "apron", "aerodrome"):
            with self.subTest(value=value):
                self.assertIn(f'"aeroway"="{value}"', query)


class HowWideAndWhatColour(unittest.TestCase):
    def test_a_runway_is_the_widest_thing_in_town(self):
        self.assertGreater(ROAD_WIDTHS_M["runway"],
                           max(v for k, v in ROAD_WIDTHS_M.items()
                               if k != "runway"))
        self.assertGreater(ROAD_WIDTHS_M["runway"], ROAD_WIDTHS_M["taxiway"])

    def test_a_tagged_runway_width_is_believed(self):
        # The cap that keeps a street from being sixty metres wide would
        # otherwise cut every real runway down to thirty.
        self.assertEqual(_way_width_m(Way(aeroway="runway", width="45"),
                                      "runway"), 45.0)
        self.assertGreater(MAX_TAGGED_WIDTH_M["runway"], 30.0)

    def test_an_absurd_width_is_still_refused(self):
        self.assertLessEqual(_way_width_m(Way(aeroway="runway", width="4000"),
                                          "runway"),
                             MAX_TAGGED_WIDTH_M["runway"])
        self.assertEqual(_way_width_m(Way(highway="residential", width="60"),
                                      "road_minor"), 30.0)

    def test_every_part_is_painted(self):
        for cat in AIRPORT:
            with self.subTest(cat=cat):
                self.assertIn(cat, LANDSCAPE_FILL)
                self.assertIn(cat, LANDSCAPE_ORDER)

    def test_the_runway_is_laid_over_everything_it_crosses(self):
        order = LANDSCAPE_ORDER
        self.assertGreater(order.index("runway"), order.index("taxiway"))
        self.assertGreater(order.index("taxiway"), order.index("apron"))
        self.assertGreater(order.index("apron"), order.index("road_major"))
        # And the field is under all of it.
        self.assertLess(order.index("airfield"), order.index("apron"))

    def test_it_is_laid_the_way_the_game_lays_its_own(self):
        # Vanilla's airfield: the runway is grey asphalt in a pale shoulder,
        # and the apron is the big pale slab. The other way round reads as a
        # car park with a path through it.
        # The runway is the darkest asphalt the palette has: painted the
        # same mid-grey as a street it was a very wide street. Dark strip,
        # pale shoulder, pale bars - that silhouette is an airfield.
        self.assertEqual(LANDSCAPE_FILL["runway"], C.DARK_ASPHALT)
        self.assertNotEqual(LANDSCAPE_FILL["runway"], LANDSCAPE_FILL["taxiway"])
        self.assertEqual(LANDSCAPE_FILL["apron"], C.PALE_CONCRETE)
        self.assertGreater(RUNWAY_SHOULDER_M, 0)
        # ...and the shoulder is painted, which OnTheGround checks. It was
        # written down here and nowhere else for long enough to ship: a test
        # that a number is above zero is not a test that anything uses it.

    def test_a_runway_is_marked_down_the_middle_and_not_in_lanes(self):
        marks = _road_markings(Way(aeroway="runway"), "runway")
        self.assertEqual(marks, [("white", 0.0)])
        # A taxiway is yellow down the middle, which is what the colour means
        # on an airfield and what tells it from the runway it leads to.
        self.assertEqual(_road_markings(Way(aeroway="taxiway"), "taxiway"),
                         [("yellow", 0.0)])

    def test_the_marking_pass_is_told_about_runways(self):
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "generator", "rendering",
                "roads.py"), encoding="utf-8") as f:
            self.assertIn('"runway"', f.read())


class NothingGrowsOnAnAirfield(unittest.TestCase):
    def test_the_grass_is_the_ordinary_green(self):
        # The pale grass is a wheat field: the strip came out standing in a
        # crop. An airfield is mown green, like the game's own.
        self.assertEqual(LANDSCAPE_FILL["airfield"], C.MEDIUM_GRASS)

    def test_and_the_planting_is_kept_off_it_by_its_own_outline(self):
        import numpy as np
        from PIL import Image
        from generator.rendering.vegetation import _paint_wild_growth

        class Proj:
            meters_per_tile = 1.0

        size = (120, 120)
        land = Image.new("RGB", size, LANDSCAPE_FILL["airfield"])
        clear = np.zeros((size[1], size[0]), dtype=bool)
        clear[20:100, 20:100] = True
        veg = Image.new("RGB", size, (0, 0, 0))
        _paint_wild_growth(veg, land, Proj(), density=1.0, exclude=clear)
        planted = np.array(veg.convert("RGB"))
        self.assertFalse(np.any(np.any(planted[20:100, 20:100] != 0, axis=2)),
                         "something was planted on the airfield")

    def test_but_it_is_still_green_space(self):
        # So a built-up block does not pave the whole aerodrome over.
        self.assertIn("airfield", GREEN_CATEGORIES)

    def test_a_building_on_the_apron_knows_where_it_stands(self):
        self.assertIn("airfield", AREA_CATEGORIES)
        self.assertIn("apron", AREA_CATEGORIES)


class FencedLikeTheGameFencesItsOwn(unittest.TestCase):
    def test_a_big_airfield_gets_a_perimeter(self):
        from knoxbuild.fences import FENCED_SITES, style_for
        self.assertIn("airfield", FENCED_SITES)
        self.assertEqual(style_for({}, "airfield"), "tall_chainlink")

    def test_but_not_a_strip_in_somebody_s_field(self):
        from knoxbuild.fences import FENCED_SITES
        self.assertGreater(FENCED_SITES["airfield"], FENCED_SITES["military"])


class ThereIsSomethingOnIt(unittest.TestCase):
    def test_the_apron_is_laid_out_in_stalls_like_a_car_park(self):
        # The game has no aeroplanes, and an empty slab of concrete is what
        # reads as unfinished. Vanilla's own apron has vehicles on it.
        from knoxbuild import zones_detect
        import inspect
        self.assertIn('("parking", "apron")', inspect.getsource(zones_detect))


class AHangarIsOneSpan(unittest.TestCase):
    """Laid out as a warehouse, a hangar came out a row of offices and
    stockrooms - which is what an airport looked like."""

    def test_the_map_says_it_is_a_hangar(self):
        from knoxbuild.build import classify_building
        for tags in ({"aeroway": "hangar"}, {"building": "hangar"}):
            with self.subTest(tags=tags):
                self.assertEqual(classify_building(tags), "hangar")

    def test_a_terminal_and_a_tower_are_classified_distinctly(self):
        from knoxbuild.build import classify_building
        self.assertEqual(classify_building({"aeroway": "terminal"}), "terminal")
        self.assertEqual(classify_building({"aeroway": "control_tower"}), "civic")

    def test_an_ordinary_hangar_is_a_single_room(self):
        from knoxbuild.layout import build_building
        from knoxbuild.settings import Settings
        for w, h in ((30, 18), (46, 26)):
            with self.subTest(size=(w, h)):
                built = build_building(w, h, levels=1, kind="hangar", seed=3,
                                       settings=Settings())
                self.assertEqual(len(built.rooms), 1)

    def test_a_huge_one_is_still_cut_into_bays(self):
        # Not vanity: the game spawns loot per room, so one room the size of
        # a street would hold almost nothing.
        from knoxbuild.layout import build_building
        from knoxbuild.settings import Settings
        built = build_building(110, 50, levels=1, kind="hangar", seed=3,
                               settings=Settings())
        self.assertGreater(len(built.rooms), 1)

    def test_it_is_a_single_storey(self):
        from knoxbuild.build import DEFAULT_LEVELS
        self.assertEqual(DEFAULT_LEVELS["hangar"], (1, 1))

    def test_even_when_the_mapper_measured_the_roof(self):
        # A height tag on a hangar measures one tall space, not two floors.
        # Eight metres came out as a hangar with a first floor in it.
        import random
        from knoxbuild.build import building_levels
        from knoxbuild.settings import Settings
        rng = random.Random(1)
        for tags in ({"height": "8"}, {"building:levels": "3"}, {}):
            with self.subTest(tags=tags):
                levels, _ = building_levels(tags, "hangar", 900, rng,
                                            Settings(), 2.0)
                self.assertEqual(levels, 1)
        # and nothing else is clamped
        self.assertEqual(building_levels({"height": "8"}, "industrial", 900,
                                         rng, Settings(), 2.0)[0], 2)

    def test_its_rooms_are_ones_the_game_knows(self):
        import re
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "knoxbuild", "layout", "core.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        defined = set(re.findall(r'^    "(\w+)": \(C\.', src, re.M))
        plans = re.search(r'"hangar":\s*\((\[[^\]]*\]),\s*(\[[^\]]*\])', src, re.S)
        self.assertIsNotNone(plans)
        import ast
        used = set(ast.literal_eval(plans.group(1)) + ast.literal_eval(plans.group(2)))
        self.assertTrue(used <= defined, f"no such rooms: {sorted(used - defined)}")

    def test_it_holds_a_hangar_s_worth_of_people(self):
        # Unlisted kinds take 25 m2 a head, which put an office block's
        # crowd in a shed with two mechanics in it.
        from knoxbuild.population import occupants
        _, daytime = occupants("hangar", 1200, 1, 2.0, 45.0)
        _, works = occupants("industrial", 1200, 1, 2.0, 45.0)
        self.assertLess(daytime, works / 2)
        self.assertGreater(daytime, 0)

    def test_it_is_never_thinned_away_as_housing(self):
        from knoxbuild.procedural import HOUSING
        self.assertNotIn("hangar", HOUSING)

    def test_its_roof_is_flat_and_bare(self):
        # The game's own airfield roofs its hangar in shallow pale metal and
        # its terminal flat. A house gable kit over a twenty-six tile span is
        # thirteen tiles tall - a barn - and the air handling units a flat
        # roof usually gets are what made it read as a distribution shed.
        import re
        from knoxbuild.layout import build_building
        from knoxbuild.settings import Settings
        from knoxbuild.tbx import render_tbx

        def roofing(kind):
            built = build_building(40, 24, levels=1, kind=kind, seed=5,
                                   settings=Settings())
            doc = render_tbx(built, "t")
            return (len(re.findall(r"Slope", doc)),
                    len(re.findall(r"rooftop_", doc)))

        slopes, clutter = roofing("hangar")
        gable_slopes, _ = roofing("garage")
        flat_slopes, flat_clutter = roofing("industrial")
        self.assertEqual(clutter, 0)
        self.assertGreater(flat_clutter, 0)
        self.assertEqual(slopes, flat_slopes)
        self.assertLess(slopes, gable_slopes / 3)

    def test_its_floor_is_a_warehouse_as_far_as_the_game_is_concerned(self):
        # The separate room key is for the roof; the loot has to stay a
        # warehouse's, and a room the game has no name for spawns nothing.
        from knoxbuild.layout.core import ROOM_STYLE
        from knoxbuild.catalog import ROOM_COLORS
        self.assertEqual(ROOM_STYLE["hangar"][1], "Warehouse")
        self.assertIn("hangar", ROOM_COLORS)

    def test_it_is_not_offered_twice_in_the_building_editor(self):
        # Its game name is "Warehouse", which the editor already offers
        # under the warehouse room: two entries with one name.
        from knoxbuild.designer import room_kinds
        for kind in (None, "industrial", "hangar", "house"):
            with self.subTest(kind=kind):
                names = [r["label"] for r in room_kinds(kind)]
                self.assertEqual(len(names), len(set(names)))

    def test_it_is_white_ish(self):
        # walls_commercial_03_048 is the palest wall the tools ship that is
        # not somebody's branding: smooth white-grey block, no coursing.
        # Tile 16 off the same sheet - what the vanilla terminal is built of -
        # is tan brick, which under a roof came out as a large barn.
        import random
        from knoxbuild.build import pick_style
        from knoxbuild.catalog import AIRFIELD_WALL
        from knoxbuild.settings import Settings
        rng = random.Random(4)
        for i in range(8):
            style = pick_style("hangar", 100 + i, 200 + i, rng, Settings())
            with self.subTest(i=i):
                self.assertEqual(style["exterior"]["tiles"]["West"], AIRFIELD_WALL)

    def test_terminal_is_glass_and_hangar_is_solid_walled(self):
        # An airport terminal has a glass curtain wall (1, 1); a hangar has
        # solid industrial walls with sparse high windows (8, 12).
        from knoxbuild.layout import build_building
        from knoxbuild.layout.furnishing import FACADE_SPACING
        from knoxbuild.settings import Settings
        self.assertEqual(FACADE_SPACING["terminal"], (1, 1))
        self.assertEqual(FACADE_SPACING["hangar"], (8, 12))
        term = build_building(40, 24, levels=1, kind="terminal", seed=5,
                              settings=Settings())
        panes = sum(len(storey.windows) for storey in term.storeys)
        self.assertGreater(panes, 60)

    def test_terminal_has_gate_seating_and_checkin_counters(self):
        from knoxbuild.layout import build_building
        from knoxbuild.settings import Settings
        built = build_building(32, 20, levels=1, kind="terminal", seed=7,
                               settings=Settings())
        furn = [item[0] for s in built.storeys for item in s.furniture]
        self.assertGreaterEqual(furn.count("chair"), 8)
        self.assertTrue(any(k in furn for k in ("counter_2", "counter")))
        self.assertIn("register", furn)

    def test_hangar_keeps_center_open_and_has_no_bookshelves(self):
        from knoxbuild.layout import build_building
        from knoxbuild.settings import Settings
        built = build_building(30, 20, levels=1, kind="hangar", seed=5,
                               settings=Settings())
        s = built.storeys[0]
        furn = [item[0] for item in s.furniture]
        self.assertNotIn("shelf", furn)
        self.assertTrue(any(k in furn for k in ("metal_rack", "crate", "counter")))
        # Central aircraft bay must remain clear of furniture.
        center = {(x, y) for x in range(8, 22) for y in range(6, 14)}
        in_center = [(x, y) for _k, x, y, _o in s.furniture if (x, y) in center]
        self.assertEqual(in_center, [])

    def test_that_style_is_taken_from_the_catalog_not_retyped(self):
        # A second copy of the same forty tile names is a second copy to
        # get wrong.
        from knoxbuild import catalog as C
        donors = [v for vs in C.SPECIAL_STYLE_VARIANTS.values() for v in vs
                  if v["exterior"]["tiles"].get("West") == C.AIRFIELD_WALL]
        self.assertTrue(donors)
        self.assertEqual(C.SPECIAL_STYLES["hangar"]["exterior"],
                         donors[0]["exterior"])


class TheBuildingsOnIt(unittest.TestCase):
    def test_a_terminal_keeps_the_tag_that_says_it_is_one(self):
        from generator.rendering.buildings import BUILDING_TAGS
        for key in ("aeroway", "military", "emergency", "sport", "landuse"):
            with self.subTest(key=key):
                self.assertIn(key, BUILDING_TAGS)


class ThePianoKeys(unittest.TestCase):
    """The bars at a runway end, which are what say 'airfield' on the ground."""

    SOUTH, WEST, NORTH, EAST = 40.0, -85.0, 40.0180, -84.9770

    def at(self, fx, fy):
        return (self.NORTH - (self.NORTH - self.SOUTH) * fy,
                self.WEST + (self.EAST - self.WEST) * fx)

    def painted(self, pts):
        """Tiles of marking laid on a runway through those points."""
        import numpy as np
        from PIL import Image

        from generator.osm import OSMFeature
        from generator.rendering.airfield import paint_runway_markings
        from generator.rendering.projection import Projector

        proj = Projector.build(self.SOUTH, self.WEST, self.NORTH, self.EAST,
                               2.0, 0.0)
        feat = OSMFeature(1, "way", {"aeroway": "runway"}, pts)
        # A strip of asphalt under it, as the landcover pass would have left.
        from PIL import ImageDraw
        land = Image.new("RGB", (proj.width, proj.height), C.DARK_GRASS)
        draw = ImageDraw.Draw(land)
        px = [proj.to_px(la, lo) for la, lo in feat.geometry]
        draw.line(px, fill=C.DARK_ASPHALT, width=15)
        count = paint_runway_markings(land, {"runway": [feat]}, proj)
        return count, np.asarray(land), px

    def test_a_runway_along_the_grid_gets_its_bars(self):
        count, _ground, _px = self.painted([self.at(0.5, 0.05), self.at(0.5, 0.95)])
        self.assertGreater(count, 0)

    def test_so_does_one_on_the_diagonal(self):
        # Half of them land at 45 degrees once the grid has them, and the
        # game ships no diagonal line tile - which is why these are painted
        # into the ground rather than laid as markings.
        count, _ground, _px = self.painted([self.at(0.05, 0.05), self.at(0.95, 0.95)])
        self.assertGreater(count, 0)

    def test_threshold_bars_are_denser_at_the_ends_than_the_middle(self):
        import numpy as np
        pts = [self.at(0.5, 0.05), self.at(0.5, 0.95)]
        _count, ground, px = self.painted(pts)
        marks = np.all(ground == C.PALE_CONCRETE, axis=2)
        ys = np.nonzero(marks)[0]
        self.assertTrue(ys.size)
        top, bottom = min(px[0][1], px[-1][1]), max(px[0][1], px[-1][1])
        span = bottom - top
        middle = (top + bottom) / 2.0
        # Ends have full-width piano keys + edge stripes; middle has only edge
        # stripes and dashed centerline, so ends carry much higher mark density.
        at_ends = int(np.sum((ys <= top + span * 0.15) | (ys >= bottom - span * 0.15)))
        in_middle = int(np.sum(np.abs(ys - middle) <= span * 0.15))
        self.assertGreater(in_middle, 0, "expected edge stripes / centerline in middle")
        self.assertGreater(at_ends, in_middle)

    def test_nothing_is_painted_off_the_strip(self):
        import numpy as np
        _count, ground, _px = self.painted([self.at(0.5, 0.05), self.at(0.5, 0.95)])
        marks = np.all(ground == C.PALE_CONCRETE, axis=2)
        grass = np.all(ground == C.DARK_GRASS, axis=2)
        self.assertEqual(int((marks & grass).sum()), 0)


class WhatTheTagsCallIt(unittest.TestCase):
    def test_a_hangar_tagged_as_one(self):
        from knoxbuild.build import classify_building
        for tags in ({"aeroway": "hangar"}, {"building": "hangar"}):
            with self.subTest(tags=tags):
                self.assertEqual(classify_building(tags), "hangar")

    def test_a_hangar_that_only_says_so_in_its_name(self):
        # Louisville's three UPS hangars are building=yes with the word in
        # the name and nothing else, and came out as brick houses with two
        # hundred rooms in them. Big airports do not tag their hangars.
        from knoxbuild.build import classify_building
        self.assertEqual(
            classify_building({"building": "yes", "name": "UPS Aircraft Hangar"}),
            "hangar")

    def test_a_terminal_however_it_is_tagged(self):
        from knoxbuild.build import classify_building
        for tags in ({"aeroway": "terminal"},
                     {"building": "airport_terminal"},
                     {"building": "yes", "name": "Addington Field Terminal"}):
            with self.subTest(tags=tags):
                self.assertEqual(classify_building(tags), "terminal")
        self.assertEqual(classify_building({"aeroway": "control_tower"}), "civic")

    def test_untagged_airfield_building_is_hangar(self):
        from knoxbuild.areas import KIND_FOR_AREA
        self.assertEqual(KIND_FOR_AREA["airfield"], "hangar")
        self.assertEqual(KIND_FOR_AREA["apron"], "hangar")

    def test_a_height_tag_does_not_put_a_floor_in_a_hangar(self):
        # Louisville's is tagged eight storeys, which measures the roof over
        # one tall space, not eight floors to walk about on.
        from knoxbuild.build import building_levels
        from knoxbuild.settings import Settings
        levels, _ = building_levels({"building": "hangar", "building:levels": "8"},
                                    "hangar", 2000, 1.0, Settings())
        self.assertEqual(levels, 1)


class LaidStraight(unittest.TestCase):
    """straight_roads = 5, the Vanilla 45-degree grid, over an airfield."""

    SOUTH, WEST, NORTH, EAST = 40.0, -85.0, 40.0054, -84.9930

    def setUp(self):
        from generator.rendering.projection import Projector
        self.proj = Projector.build(self.SOUTH, self.WEST, self.NORTH,
                                    self.EAST, 2.0, 0.0)

    def at(self, fx, fy):
        return (self.NORTH - (self.NORTH - self.SOUTH) * fy,
                self.WEST + (self.EAST - self.WEST) * fx)

    def headings(self, feat):
        import math
        pts = [self.proj.to_px(la, lo) for la, lo in feat.geometry]
        out = []
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if abs(bx - ax) < 0.5 and abs(by - ay) < 0.5:
                continue
            out.append(round(math.degrees(math.atan2(by - ay, bx - ax)), 1))
        return out

    def apply(self, feats):
        from generator.osm import classify
        from generator.rendering.geometry import _is_polygon
        from generator.vanilla_grid import apply_vanilla_grid
        return apply_vanilla_grid(feats, self.proj, classify, _is_polygon)

    def test_a_runway_comes_out_as_one_straight_line(self):
        # At an angle nowhere near a multiple of 45 the street router answers
        # with a chamfer, and a real runway came back as fourteen alternating
        # legs. A runway with a dogleg in it is not a runway.
        from generator.osm import OSMFeature
        import math
        pts = [self.at(0.1, 0.8), self.at(0.5, 0.45), self.at(0.9, 0.1)]
        feat = OSMFeature(1, "way", {"aeroway": "runway"}, pts)
        before = [self.proj.to_px(la, lo) for la, lo in feat.geometry]
        length = math.hypot(before[-1][0] - before[0][0],
                            before[-1][1] - before[0][1])
        self.apply([feat])
        self.assertEqual(len(feat.geometry), 2)
        self.assertEqual(len(self.headings(feat)), 1)
        self.assertIn(self.headings(feat)[0],
                      (0.0, 45.0, 90.0, 135.0, 180.0, -45.0, -90.0, -135.0))
        after = [self.proj.to_px(la, lo) for la, lo in feat.geometry]
        kept = math.hypot(after[-1][0] - after[0][0], after[-1][1] - after[0][1])
        self.assertAlmostEqual(kept, length, delta=2.0)

    def test_a_taxiway_that_really_bends_is_left_alone(self):
        from generator.osm import OSMFeature
        pts = [self.at(0.1, 0.1), self.at(0.5, 0.12), self.at(0.5, 0.9)]
        feat = OSMFeature(2, "way", {"aeroway": "taxiway"}, pts)
        before = list(feat.geometry)
        self.apply([feat])
        self.assertEqual(feat.geometry, before)

    def test_the_streets_are_not_touched_by_it(self):
        # The airside rule runs instead of the street router, not as well as
        # it: a street that bends still gets its chamfered corner.
        from generator.osm import OSMFeature
        pts = [self.at(0.1, 0.1), self.at(0.5, 0.12), self.at(0.5, 0.9)]
        feat = OSMFeature(3, "way", {"highway": "residential"}, pts)
        self.apply([feat])
        self.assertGreater(len(self.headings(feat)), 1)


class WhatStandsRoundIt(unittest.TestCase):
    def test_a_hangar_gets_a_yard_not_a_garden(self):
        # It stood in a bed of shrubs and flowers, against the wall an
        # aircraft is rolled through: the yard passes name the kinds that
        # keep their hard ground, and a hangar was in neither list.
        from knoxbuild.works import WORKS_KINDS
        self.assertIn("hangar", WORKS_KINDS)

    def test_the_house_planting_keeps_off_it(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "knoxbuild", "yards.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for guard in ('("house", "garage", "industrial", "hangar")',
                      '("garage", "industrial", "hangar")'):
            with self.subTest(guard=guard):
                self.assertIn(guard, src)


class OnTheGround(unittest.TestCase):
    """Through the whole renderer: what an airfield's ground comes out as."""

    SOUTH, WEST, NORTH, EAST = 40.0, -85.0, 40.0054, -84.9930
    METRES_PER_TILE = 2.0

    @classmethod
    def at(cls, fx, fy):
        return (cls.NORTH - (cls.NORTH - cls.SOUTH) * fy,
                cls.WEST + (cls.EAST - cls.WEST) * fx)

    @classmethod
    def setUpClass(cls):
        import contextlib
        import tempfile

        import numpy as np
        from PIL import Image

        from generator import renderer
        from generator.osm import OSMFeature
        from generator.rendering.projection import Projector

        at = cls.at

        def ring(x0, y0, x1, y1):
            pts = [at(x0, y0), at(x1, y0), at(x1, y1), at(x0, y1)]
            return pts + [pts[0]]

        cls.field = OSMFeature(1, "way", {"aeroway": "aerodrome", "area": "yes"},
                               ring(0.02, 0.02, 0.98, 0.98))
        feats = [
            cls.field,
            # Along the grid, so the markings have somewhere to go.
            OSMFeature(2, "way", {"aeroway": "runway"}, [at(0.08, 0.5), at(0.92, 0.5)]),
            OSMFeature(3, "way", {"aeroway": "taxiway"}, [at(0.08, 0.8), at(0.92, 0.8)]),
            OSMFeature(4, "way", {"aeroway": "apron", "area": "yes"},
                       ring(0.1, 0.86, 0.9, 0.96)),
        ]
        out = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.render(feats, cls.SOUTH, cls.WEST, cls.NORTH, cls.EAST,
                            meters_per_tile=cls.METRES_PER_TILE, output_dir=out,
                            map_name="apt", tree_density=1.0, spawn_density=10)
        with Image.open(os.path.join(out, "apt.bmp")) as im:
            cls.ground = np.asarray(im.convert("RGB"))
        with Image.open(os.path.join(out, "apt_veg.bmp")) as im:
            cls.veg = np.asarray(im.convert("RGB"))
        cls.buckets = {}
        for feat in feats:
            cat = classify(feat.tags, renderer._is_polygon(feat))
            cls.buckets.setdefault(cat, []).append(feat)
        # The map is padded out to whole 300-tile cells, so where the field
        # landed on the bitmap is the projector's business, not a guess.
        cls.proj = Projector.build(cls.SOUTH, cls.WEST, cls.NORTH, cls.EAST,
                                   cls.METRES_PER_TILE, 0.0)
        cls.inside = renderer._polygon_mask([cls.field], cls.proj)
        cls.strips = renderer._strips_mask(cls.buckets, cls.proj, None)
        cls.np = np

    @classmethod
    def growing(cls, veg):
        """Tiles something was planted on, which the paint on a road is not."""
        import numpy as np
        out = np.zeros(veg.shape[:2], dtype=bool)
        for colour in C.VEGETATION_COLORS:
            if colour == C.VEG_NOTHING:
                continue
            out |= np.all(veg == colour, axis=2)
        return out

    def test_the_runway_has_a_pale_shoulder_either_side(self):
        # Down a column through the runway: concrete, asphalt, concrete.
        # Thirty metres of bare tarmac in a field is a very wide road, which
        # is what every runway looked like - RUNWAY_SHOULDER_M was written
        # down and nothing ever painted it.
        x, _ = self.proj.to_px(*self.at(0.5, 0.5))
        column = [tuple(px) for px in self.ground[:, int(x)]]
        strip = [row for row in column
                 if row in (tuple(C.DARK_ASPHALT), tuple(C.PALE_CONCRETE))]
        self.assertTrue(strip, "no runway was painted")
        self.assertEqual(strip[0], tuple(C.PALE_CONCRETE))
        self.assertEqual(strip[-1], tuple(C.PALE_CONCRETE))
        self.assertIn(tuple(C.DARK_ASPHALT), strip)

    def test_the_taxiway_is_marked_yellow_and_the_runway_white(self):
        np = self.np
        self.assertTrue(np.all(self.veg == C.LINE_WHITE_N, axis=2).any(),
                        "the runway has no centre line")
        self.assertTrue(np.all(self.veg == C.LINE_YELLOW_N, axis=2).any(),
                        "the taxiway has no centre line")

    def test_nothing_is_planted_between_the_runways(self):
        # An aerodrome is mown from the fence in: anything taller than grass
        # is something an aircraft can hit. The passes that scatter trees over
        # open grass had the largest sheet of open grass in the town to work
        # with, and the strip came out lined with trees on both sides.
        planted = int(self.growing(self.veg)[self.inside].sum())
        self.assertEqual(planted, 0, f"{planted} tiles grew on the airfield")

    def test_nothing_stands_beside_the_runway(self):
        # The furniture pass works off the tarmac, not off what the tarmac
        # is for: a runway was given street lamps reaching out over it and a
        # drain in its gutter. It keeps its edge lines, which a real one has.
        from generator.rendering import furniture        # noqa: F401
        np = self.np
        strip = self.strips
        for name in ("LAMP_N", "LAMP_S", "LAMP_E", "LAMP_W", "STORM_DRAIN",
                     "FIRE_HYDRANT"):
            colour = getattr(C, name, None)
            if colour is None:
                continue
            with self.subTest(what=name):
                on = np.all(self.veg == colour, axis=2) & strip
                self.assertEqual(int(on.sum()), 0, f"{name} on the runway")
        self.assertTrue((np.all(self.veg == C.EDGE_LINE_N, axis=2)
                         | np.all(self.veg == C.EDGE_LINE_S, axis=2))[strip].any(),
                        "the runway lost its edge lines too")

    def test_the_mapper_s_own_woods_still_stand(self):
        # Only the guesses are kept off. A wood someone mapped inside the
        # fence is read from the map, and a corner of trees is a real one.
        import contextlib
        import tempfile

        from PIL import Image

        from generator import renderer
        from generator.osm import OSMFeature

        at = self.at
        pts = [at(0.2, 0.2), at(0.4, 0.2), at(0.4, 0.4), at(0.2, 0.4)]
        wood = OSMFeature(5, "way", {"natural": "wood"}, pts + [pts[0]])
        out = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.render([self.field, wood], self.SOUTH, self.WEST,
                            self.NORTH, self.EAST,
                            meters_per_tile=self.METRES_PER_TILE,
                            output_dir=out, map_name="wood", tree_density=1.0,
                            spawn_density=10)
        with Image.open(os.path.join(out, "wood_veg.bmp")) as im:
            veg = self.np.asarray(im.convert("RGB"))
        self.assertGreater(int(self.growing(veg).sum()), 0,
                           "the mapped wood was mown away with the guesses")


if __name__ == "__main__":
    unittest.main()
