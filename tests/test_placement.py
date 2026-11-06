"""Where a map stands in the game's world (knoxbuild/placement.py).

Moving a map rewrites files somebody's built town is made of, so what matters
is that it changes exactly what carries the world origin and nothing else -
the test is a round trip, byte for byte - that it is honest about needing the
map compiled again, and that nothing can quietly land one map on top of
another.
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from knoxbuild import placement as P
from knoxbuild.world import CELL_SIZE, choose_origin

PZW = """<?xml version="1.0" encoding="UTF-8"?>
<world version="1.0" width="4" height="3">
 <GenerateLots>
  <worldOrigin origin="70,0"/>
 </GenerateLots>
 <cell x="0" y="0">
  <lot x="12" y="30" level="0" width="20" height="16" map="buildings/a.tbx"/>
 </cell>
</world>
"""
WORLDMAP = """<?xml version="1.0" encoding="UTF-8"?>
<world version="1.0">
 <cell x="70" y="0">
  <feature>
   <geometry type="Polygon">
    <coordinates>
     <point x="0" y="0"/>
     <point x="0" y="300"/>
    </coordinates>
   </geometry>
   <properties>
    <property name="water" value="river"/>
   </properties>
  </feature>
 </cell>
 <cell x="71" y="2">
 </cell>
</world>
"""
STREETS = """<streets version="1">
    <street name="Main Street" width="4">
        <points>
            <point x="21000.0" y="150.5"/>
            <point x="21300.4" y="150.5"/>
        </points>
    </street>
</streets>
"""
ANNOTATIONS = """return function(mapUI)
\tlocal symbolsAPI = mapUI.javaObject:getAPIv3():getSymbolsAPIv2()
\tsymbol = symbolsAPI:addUntranslatedText("St Mary's", "text-building", 21137, 524)
\tsymbol:setScale(0.600)
end
"""


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class AMapOnDisk(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name, text in (("town.pzw", PZW), ("worldmap.xml", WORLDMAP),
                           ("streets.xml", STREETS),
                           ("worldmap-annotations.lua", ANNOTATIONS)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8",
                      newline="") as f:
                f.write(text)
        with open(os.path.join(self.dir, "town_info.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"cells_x": 4, "cells_y": 3}, f)

    def compiled(self, cell_x=82, cell_y=0):
        lots = os.path.join(self.dir, "lots")
        os.makedirs(lots, exist_ok=True)
        for name in (f"{cell_x}_{cell_y}.lotheader", f"world_{cell_x}_{cell_y}.lotpack",
                     f"chunkdata_{cell_x}_{cell_y}.bin"):
            open(os.path.join(lots, name), "w").close()

    def text(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()

    def files(self):
        return {name: sha(os.path.join(self.dir, name))
                for name in sorted(os.listdir(self.dir))
                if os.path.isfile(os.path.join(self.dir, name))}


class ChoosingAPlace(AMapOnDisk):
    def test_a_place_is_remembered_beside_the_map(self):
        self.assertIsNone(P.saved(self.dir))
        P.save(self.dir, (120, 40))
        self.assertEqual(P.saved(self.dir), (120, 40))
        self.assertTrue(P.forget(self.dir))
        self.assertIsNone(P.saved(self.dir))

    def test_the_build_uses_the_place_that_was_chosen(self):
        # The whole point: otherwise the map is packed in east of whatever is
        # installed and the choice means nothing.
        P.save(self.dir, (133, 41))
        self.assertEqual(choose_origin(self.dir, 4, 3), (133, 41))

    def test_without_one_the_map_is_packed_in_as_before(self):
        self.assertEqual(choose_origin(self.dir, 4, 3),
                         P.project_origin(self.dir, "town"))

    def test_a_place_that_is_not_two_numbers_is_refused(self):
        for bad in (None, (), ("west", 2), (1,), "70,0"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    P.save(self.dir, bad)

    def test_a_place_outside_the_world_is_refused(self):
        for bad in ((-1, 0), (0, -5), (P.MAX_CELL + 1, 0), (0, 99999)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    P.save(self.dir, bad)

    def test_nonsense_in_the_file_is_no_choice_at_all(self):
        with open(os.path.join(self.dir, P.PLACEMENT_FILE), "w",
                  encoding="utf-8") as f:
            f.write("not json")
        self.assertIsNone(P.saved(self.dir))


class Standalone(AMapOnDisk):
    def test_a_map_is_not_standalone_until_it_is_made_so(self):
        self.assertFalse(P.standalone(self.dir))
        self.assertFalse(P.layout(self.dir, "town")["standalone"])

    def test_standalone_goes_to_the_corner_and_is_remembered(self):
        P.set_standalone(self.dir, "town", True)
        self.assertTrue(P.standalone(self.dir))
        self.assertEqual(P.saved(self.dir), (0, 0))
        self.assertEqual(P.project_origin(self.dir, "town"), (0, 0))
        self.assertTrue(P.layout(self.dir, "town")["standalone"])

    def test_moving_a_standalone_map_keeps_it_standalone(self):
        P.set_standalone(self.dir, "town", True)
        P.save(self.dir, (3, 4))
        self.assertTrue(P.standalone(self.dir))

    def test_taking_standalone_off_leaves_the_map_where_it_is(self):
        P.set_standalone(self.dir, "town", True)
        P.set_standalone(self.dir, "town", False)
        self.assertFalse(P.standalone(self.dir))
        self.assertEqual(P.saved(self.dir), (0, 0))

    def test_taking_standalone_off_says_a_compile_is_needed(self):
        # The map was compiled where it stood (cell 82,0) and standalone parked
        # it at the corner. Standing it back down leaves it at the corner, and
        # the lots in lots/ still name 82,0 - a "no" written down here is what
        # let install refuse the map as moved since it was compiled.
        self.compiled()
        P.set_standalone(self.dir, "town", True)
        done = P.set_standalone(self.dir, "town", False)
        self.assertEqual(done["origin"], [0, 0])
        self.assertTrue(done["needsCompile"])

    def test_standalone_off_is_no_compile_when_the_lots_are_already_there(self):
        self.compiled(cell_x=0, cell_y=0)
        P.set_standalone(self.dir, "town", True)
        self.assertFalse(P.set_standalone(self.dir, "town", False)["needsCompile"])

    def test_forgetting_the_place_forgets_standalone_too(self):
        P.set_standalone(self.dir, "town", True)
        P.forget(self.dir)
        self.assertFalse(P.standalone(self.dir))

    def test_the_server_setup_drops_knox_county_for_a_standalone_map(self):
        from tools import make_map_mod as m
        for flag in (False, True):
            with self.subTest(standalone=flag), tempfile.TemporaryDirectory() as root:
                m.write_server_setup(root, "Town", "Town", "Town", standalone=flag)
                text = open(os.path.join(root, "SERVER SETUP.txt"), encoding="utf-8").read()
                regions = open(os.path.join(root, "server", "Town_spawnregions.lua"),
                               encoding="utf-8").read()
                self.assertEqual("\n      Map=Town;Muldraugh, KY\n" in text, not flag)
                self.assertEqual("\n      Map=Town\n" in text, flag)
                self.assertEqual("Muldraugh" in regions, not flag)


class WhatTheWindowShows(AMapOnDisk):
    def test_knox_county_and_this_map_are_both_on_it(self):
        world = P.layout(self.dir, "town")
        self.assertEqual(world["vanilla"]["w"], P.VANILLA_BOX[2])
        self.assertEqual((world["map"]["x"], world["map"]["y"]), (70, 0))
        self.assertEqual((world["map"]["w"], world["map"]["h"]), (4, 3))
        self.assertEqual(world["clash"], [])

    def test_a_place_on_top_of_the_vanilla_map_is_called_out(self):
        P.save(self.dir, (10, 10))
        world = P.layout(self.dir, "town")
        self.assertIn(P.VANILLA_NAME, world["clash"])

    def test_a_standalone_map_has_nothing_to_clash_with(self):
        P.save(self.dir, (10, 10), standalone_flag=True)
        self.assertEqual(P.layout(self.dir, "town")["clash"], [])

    def test_it_says_whether_the_map_is_compiled_where_it_now_sits(self):
        self.assertFalse(P.layout(self.dir, "town")["compiled"])
        self.compiled()
        self.assertTrue(P.layout(self.dir, "town")["lotsMatch"])
        P.save(self.dir, (120, 40))
        self.assertFalse(P.layout(self.dir, "town")["lotsMatch"])


class MovingOne(AMapOnDisk):
    def test_everything_that_carries_the_origin_is_moved(self):
        done = P.move(self.dir, "town", (120, 40))
        self.assertEqual(set(done["rewrote"]),
                         {"town.pzw", "worldmap.xml", "streets.xml",
                          "worldmap-annotations.lua"})
        pzw, paper, streets, notes = (
            self.text(n) for n in ("town.pzw", "worldmap.xml", "streets.xml",
                                   "worldmap-annotations.lua"))
        self.assertIn('<worldOrigin origin="120,40"/>', pzw)
        # The paper map's points are relative to their cell, so only the cell
        # numbers move: 70,0 -> 120,40 and 71,2 -> 121,42.
        self.assertIn('<cell x="120" y="40">', paper)
        self.assertIn('<cell x="121" y="42">', paper)
        self.assertIn('<point x="0" y="300"/>', paper)
        # Streets and labels are world tiles: 50 cells east, 40 south.
        self.assertIn(f'<point x="{21000.0 + 50 * CELL_SIZE:.1f}" '
                      f'y="{150.5 + 40 * CELL_SIZE:.1f}"/>', streets)
        self.assertIn(f'"text-building", {21137 + 50 * CELL_SIZE}, '
                      f'{524 + 40 * CELL_SIZE})', notes)

    def test_nothing_else_in_the_map_is_touched(self):
        before = self.files()
        P.move(self.dir, "town", (120, 40))
        after = self.files()
        unchanged = {n for n in before if before[n] == after.get(n)}
        self.assertIn("town_info.json", unchanged)

    def test_moving_it_back_gives_exactly_what_was_there(self):
        # It rewrites somebody's built town in place, so a move has to be a
        # change of numbers and nothing else - not a reformatting of the file.
        before = self.files()
        P.move(self.dir, "town", (133, 41))
        P.move(self.dir, "town", (70, 0))
        after = self.files()
        for name, digest in before.items():
            with self.subTest(name=name):
                self.assertEqual(after[name], digest)

    def test_a_map_that_is_compiled_has_to_be_compiled_again(self):
        self.compiled()
        self.assertFalse(P.move(self.dir, "town", (70, 0))["needsCompile"])
        self.assertTrue(P.move(self.dir, "town", (120, 40))["needsCompile"])

    def test_a_map_that_was_never_built_only_needs_building(self):
        os.remove(os.path.join(self.dir, "town.pzw"))
        done = P.move(self.dir, "town", (120, 40))
        self.assertTrue(done["needsBuild"])
        self.assertFalse(done["needsCompile"])
        self.assertEqual(done["rewrote"], [])
        self.assertEqual(P.saved(self.dir), (120, 40))

    def test_the_lots_say_where_the_map_really_is(self):
        self.compiled(cell_x=82, cell_y=0)       # 70 cells = 21000 tiles / 256
        self.assertEqual(P.compiled_corner(self.dir), (82, 0))
        self.assertTrue(P.lots_match(self.dir, (70, 0)))
        self.assertFalse(P.lots_match(self.dir, (71, 0)))

    def test_a_build_keeps_the_place_chosen_for_the_map(self):
        P.save(self.dir, (12, 34))
        self.assertEqual(P.settled_origin(self.dir, "town", 5, 5), (12, 34))

    def test_a_build_keeps_where_the_map_already_stands(self):
        self.compiled(cell_x=82, cell_y=0)
        self.assertEqual(P.settled_origin(self.dir, "town", 70, 1), (70, 0))

    def test_handing_the_choice_back_puts_the_map_where_it_would_have_gone(self):
        # Forgetting the choice is not enough: the project itself says where
        # the map is, so a map that was moved would stay moved.
        before = self.files()
        P.move(self.dir, "town", (150, 80))
        done = P.unplace(self.dir, "town")
        self.assertTrue(done["automatic"])
        self.assertIsNone(P.saved(self.dir))
        self.assertEqual(P.project_origin(self.dir, "town"), (70, 0))
        self.assertEqual(self.files(), before)

    def test_a_map_with_nothing_compiled_cannot_be_in_the_wrong_place(self):
        self.assertIsNone(P.compiled_corner(self.dir))
        self.assertTrue(P.lots_match(self.dir, (500, 500)))


class LeftoversFromWhereTheMapUsedToBe(unittest.TestCase):
    """Compiling after a move writes the new lots beside the old ones.

    The old ones are newer than everything they were compiled from, so nothing
    called them stale: the corner they named stayed the place the map had
    left, and install went on refusing it as "moved since it was last
    compiled" however often it was compiled. Ticking Standalone parks a map at
    cell 0,0, so putting it back somewhere real is exactly that.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        os.makedirs(os.path.join(self.dir, "lots"))
        # A project's .pzw is named after its folder, everywhere in KnoxMap.
        self.pzw = os.path.join(self.dir, os.path.basename(self.dir) + ".pzw")
        self.write_pzw("90,0")

    def write_pzw(self, origin, width=4, height=3):
        with open(self.pzw, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    f'<world version="1.0" width="{width}" height="{height}">\n'
                    f' <GenerateLots>\n  <worldOrigin origin="{origin}"/>\n'
                    ' </GenerateLots>\n</world>\n')

    def lots(self, x, y):
        for name in (f"{x}_{y}.lotheader", f"chunkdata_{x}_{y}.bin",
                     f"world_{x}_{y}.lotpack"):
            open(os.path.join(self.dir, "lots", name), "w").close()

    def left(self):
        return sorted(os.listdir(os.path.join(self.dir, "lots")))

    def test_lots_from_a_place_the_map_has_left_go(self):
        from tools.compile_map import clear_outside_world
        self.lots(0, 0)
        self.lots(1, 0)      # where Standalone had parked the map
        self.lots(105, 0)    # 90 cells = 27000 tiles, over 256
        self.assertEqual(clear_outside_world(Path(self.dir)), 6)
        self.assertEqual(self.left(), ["105_0.lotheader", "chunkdata_105_0.bin",
                                       "world_105_0.lotpack"])

    def test_the_lots_where_the_map_stands_now_stay(self):
        from tools.compile_map import clear_outside_world
        self.lots(105, 0)
        self.lots(109, 0)    # the last of four cells across: 27000..28199 tiles
        self.assertEqual(clear_outside_world(Path(self.dir)), 0)
        self.assertEqual(len(self.left()), 6)

    def test_a_map_at_the_corner_keeps_the_lots_at_the_corner(self):
        from tools.compile_map import clear_outside_world
        self.write_pzw("0,0")
        self.lots(0, 0)
        self.lots(105, 0)    # from before it was put at the corner
        self.assertEqual(clear_outside_world(Path(self.dir)), 3)
        self.assertEqual(self.left(), ["0_0.lotheader", "chunkdata_0_0.bin",
                                       "world_0_0.lotpack"])

    def test_a_project_that_says_nothing_is_left_alone(self):
        from tools.compile_map import clear_outside_world
        self.lots(0, 0)
        os.remove(self.pzw)
        self.assertEqual(clear_outside_world(Path(self.dir)), 0)
        self.assertEqual(len(self.left()), 3)


class WhereAMapReallyIs(AMapOnDisk):
    """The choice, the build and the lots, answered in one place.

    Each caller used to read those three records itself, in its own order, which
    is how one could believe a map was at 70,0 while another read 0,0 - and why
    install refused a map as "moved since it was last compiled" while the panel
    above the button said it was ready.
    """

    def test_where_its_own_files_say_it_is(self):
        here = P.where_is(self.dir, "town")
        self.assertEqual(here["cell"], P.project_origin(self.dir, "town"))
        self.assertEqual(here["source"], "built")
        self.assertIsNone(here["chosen"])

    def test_the_place_chosen_wins_over_where_it_was_built(self):
        P.save(self.dir, (12, 34))
        here = P.where_is(self.dir, "town")
        self.assertEqual(here["cell"], (12, 34))
        self.assertEqual(here["built"], P.project_origin(self.dir, "town"))
        self.assertEqual(here["chosen"], (12, 34))
        self.assertEqual(here["source"], "chosen")

    def test_the_lots_are_reported_separately_from_where_the_map_is_going(self):
        # Compiled at the corner, which is where Standalone parks a map; the
        # project itself says 70,0, whose lots belong at 82,0.
        self.compiled(cell_x=0, cell_y=0)
        here = P.where_is(self.dir, "town")
        self.assertEqual(here["cell"], (70, 0))
        self.assertEqual(here["compiled"], (0, 0))
        self.assertFalse(here["matches"])

    def test_lots_where_the_map_is_going_do_match(self):
        self.compiled(cell_x=82, cell_y=0)  # 70 cells of 300 tiles is lot 82
        self.assertTrue(P.where_is(self.dir, "town")["matches"])

    def test_moving_it_is_what_changes_the_answer(self):
        self.compiled()
        before = P.where_is(self.dir, "town")["cell"]
        P.move(self.dir, "town", (120, 40))
        after = P.where_is(self.dir, "town")
        self.assertNotEqual(before, after["cell"])
        self.assertFalse(after["matches"])

    def test_the_window_is_told_which_record_decided(self):
        P.set_standalone(self.dir, "town", True)
        world = P.layout(self.dir, "town")
        self.assertEqual(world["source"], "chosen")
        self.assertEqual(world["map"]["x"], 0)


class TheWorldAsItReallyIs(unittest.TestCase):
    """Maps are drawn cell by cell: Knox County is 4,065 cells with bites out
    of it, and a box says nothing about what is free next to it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def cells(self, pairs):
        for x, y in pairs:
            open(os.path.join(self.dir, f"{x}_{y}.lotheader"), "w").close()

    def test_its_own_installed_copy_is_not_another_map(self):
        mods = os.path.join(self.dir, "mods")
        mine = os.path.join(mods, "town", "common", "media", "maps", "town")
        other = os.path.join(mods, "village", "common", "media", "maps", "village")
        for folder in (mine, other):
            os.makedirs(folder)
            open(os.path.join(folder, "0_0.lotheader"), "w").close()
        found = [(mine, "installed", "town"), (other, "installed", "village")]
        with mock.patch.object(P, "_map_folders", return_value=found):
            self.assertEqual([m["name"] for m in P.world_maps()], ["town", "village"])
            self.assertEqual([m["name"] for m in P.world_maps(os.path.join(mods, "town"))],
                             ["village"])

    def test_a_row_of_cells_is_one_run(self):
        self.assertEqual(P._runs([(3, 0), (4, 0), (5, 0)]), [[0, 3, 5]])

    def test_a_gap_in_a_row_is_two_runs(self):
        self.assertEqual(P._runs([(3, 0), (4, 0), (9, 0)]), [[0, 3, 4], [0, 9, 9]])

    def test_every_row_is_its_own_runs_in_order(self):
        self.assertEqual(P._runs([(1, 2), (0, 1), (1, 1)]),
                         [[1, 0, 1], [2, 1, 1]])

    def test_a_map_folder_is_read_as_its_real_shape(self):
        self.cells([(10, 4), (11, 4), (10, 5), (40, 40)])
        found = P._map_folder(self.dir, "installed", "town")
        self.assertEqual((found["x"], found["y"]), (10, 4))
        self.assertEqual((found["w"], found["h"]), (31, 37))
        self.assertEqual(found["cells"], 4)
        self.assertEqual(found["runs"], [[4, 10, 11], [5, 10, 10], [40, 40, 40]])

    def test_a_folder_with_no_cells_in_it_is_not_a_map(self):
        open(os.path.join(self.dir, "map.info"), "w").close()
        self.assertIsNone(P._map_folder(self.dir, "vanilla", "Brandenburg, KY"))

    def test_a_folder_that_is_not_there_is_not_a_map(self):
        self.assertEqual(P._cells_of(os.path.join(self.dir, "nowhere")), [])
        self.assertIsNone(P._map_folder(os.path.join(self.dir, "nowhere"),
                                        "vanilla", "nothing"))

    def test_the_window_is_given_the_grid_both_sides_are_measured_in(self):
        # The picture is drawn in tiles because the two grids do not divide
        # into each other: maps are placed on 300s and compiled into 256s.
        self.assertEqual(P.COMPILED_CELL, 256)
        self.assertEqual(CELL_SIZE, 300)


class ThePictureOfAMap(unittest.TestCase):
    """The game ships a picture of each of its maps as a pyramid of tiles.
    Putting one on the world is only worth anything if it lands exactly where
    the map really is, so the bounds are read rather than guessed."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def pyramid(self, bounds="bounds=0 0 19968 16128", levels=(0, 1, 2),
                tiles=((0, 0), (1, 0))):
        import zipfile

        from PIL import Image
        path = os.path.join(self.dir, P.PYRAMID)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("pyramid.txt", f"VERSION=1\n{bounds}\nimageSize=1 1\n")
            for level in levels:
                for x, y in tiles:
                    shot = os.path.join(self.dir, "tile.png")
                    Image.new("RGB", (256, 256), (10 + level, 20, 30)).save(shot)
                    zf.write(shot, f"{level}/tile{x}x{y}.png")
        return path

    def test_the_bounds_are_read_from_the_pyramid_itself(self):
        self.assertEqual(P._pyramid_bounds("VERSION=1\nbounds=0 0 19968 16128\n"),
                         (0, 0, 19968, 16128))
        self.assertEqual(P._pyramid_bounds("bounds=512 256 1024 768"),
                         (512, 256, 1024, 768))

    def test_a_pyramid_that_says_nothing_about_bounds_is_not_used(self):
        for bad in ("", "VERSION=1", "bounds=1 2 3", "bounds=a b c d"):
            with self.subTest(bad=bad):
                self.assertIsNone(P._pyramid_bounds(bad))

    def test_the_smallest_level_is_the_one_assembled(self):
        # Every level is the whole map; the highest number is the smallest
        # picture of it, which is all a window the size of a postcard needs.
        self.pyramid(levels=(0, 1, 2))
        where = P.build_picture(self.dir, os.path.join(self.dir, "out", "m.png"))
        self.assertEqual((where["x"], where["y"], where["w"], where["h"]),
                         (0, 0, 19968, 16128))
        # Level 2 is a quarter of the tiles across: 19968 / 4 = 4992.
        self.assertEqual(where["px"], [19968 // 4, 16128 // 4])
        self.assertTrue(os.path.exists(where["file"]))

    def test_a_map_with_no_pyramid_has_no_picture(self):
        self.assertIsNone(P.build_picture(self.dir, os.path.join(self.dir, "x.png")))

    def test_a_broken_pyramid_is_no_picture_rather_than_a_crash(self):
        with open(os.path.join(self.dir, P.PYRAMID), "w") as f:
            f.write("not a zip")
        self.assertIsNone(P.build_picture(self.dir, os.path.join(self.dir, "x.png")))

    def test_a_pyramid_of_nothing_is_no_picture(self):
        self.pyramid(bounds="bounds=0 0 0 0")
        self.assertIsNone(P.build_picture(self.dir,
                                          os.path.join(self.dir, "x.png")))

    def test_a_name_that_could_escape_the_cache_cannot(self):
        for bad in ("../../etc/passwd", "Muldraugh, KY", "a/b"):
            with self.subTest(bad=bad):
                safe = P.safe_file(bad)
                self.assertNotIn("/", safe)
                self.assertNotIn("\\", safe)
                self.assertNotIn("..", safe)

    def test_the_window_is_only_told_about_pictures_it_can_have(self):
        # Without a cache to build them in there are no pictures, and the
        # world is drawn as the shape of its cells.
        maps = [{"name": "Muldraugh, KY", "picture": True}]
        self.assertEqual(P._with_pictures(maps, None)[0]["picture"], False)


if __name__ == "__main__":
    unittest.main()
