"""The big trees, and the trees round a park.

Every tree KnoxMap placed was one tile of a species sheet at an index Build 42
has no tile definition for - a picture with no `tree` property behind it, so
scenery rather than a tree - and the jumbo sheets, which are what the game
fills its own woods with, were never used at all. Reported from a generated
map: "big trees seem to almost never generate, leading to very disappointing
results. in areas such as parks more big trees should probably generate,
especially around the edges".
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import vegetation as V

ROOT = Path(__file__).resolve().parent.parent
PATCHER = ROOT / "worlded" / "patch_rules_b42_trees.py"

RULES = """alias
{
    name = darkgrass
    tiles = [
        blends_natural_01_16
    ]
}
rule
{
label = Trees
    bitmap = 1
    color = 255 0 0
    tiles = [
        vegetation_trees_01_8
        vegetation_trees_01_9
        vegetation_trees_01_10
        vegetation_trees_01_11
    ]
    layer = 0_Vegetation
}
rule
{
    label = Sparse Trees + Grass
    bitmap = 1
    color = 64 0 0
    tiles = [
        vegetation_trees_01_8
        darkgrass
        vegetation_trees_01_10
    ]
    layer = 0_Vegetation
}
rule
{
    label = Fir Trees + Dark grass
    bitmap = 1
    color = 64 0 0
    tiles = [
        vegetation_trees_01_8
        darkgrass
    ]
    layer = 0_Vegetation
    condition = 90 100 35
}
"""


def tools_dir(path: Path) -> Path:
    """A map-tools folder with just enough in it to be patched."""
    (path / "config").mkdir(parents=True, exist_ok=True)
    (path / "Tiles" / "2x").mkdir(parents=True, exist_ok=True)
    (path / "config" / "Rules.txt").write_text(RULES, encoding="utf-8")
    (path / "config" / "Tilesets.txt").write_text("", encoding="utf-8")
    # The patcher refuses to name a sheet that is not on disk; only the name
    # is read, never the picture.
    import worlded.patch_rules_b42_trees as patcher
    sheets = set(patcher.DECIDUOUS) | set(patcher.EVERGREEN) | {patcher.FLOWER_SHEET}
    for _label, _colour, tiles in patcher.TREE_RULES:
        sheets |= {t.rsplit("_", 1)[0] for t in tiles}
    for sheet in sheets:
        (path / "Tiles" / "2x" / f"{sheet}.png").write_bytes(b"")
    return path


def patch(path: Path) -> str:
    out = subprocess.run([sys.executable, str(PATCHER), str(path)],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    return (path / "config" / "Rules.txt").read_text(encoding="utf-8")


class TheRulesPlaceTreesTheGameKnows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tools = tools_dir(Path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def entries(self, text: str) -> list[str]:
        import re
        return re.findall(r"\b(e_\w+_1_\d+)\b", text)

    def test_no_tree_lands_on_a_picture_with_no_definition_behind_it(self):
        # Of the 24 pictures on a species sheet the game defines the first
        # eight, four sizes in two seasons, and it is the definition that
        # carries `tree = 1..4`. The old rules asked for 8 to 11.
        for tile in self.entries(patch(self.tools)):
            sheet, index = tile.rsplit("_", 1)
            if "JUMBO" in sheet:
                continue
            with self.subTest(tile=tile):
                self.assertLess(int(index), 4, f"{tile} is not a tree the game defines")

    def test_a_wood_gets_more_than_one_size_of_tree(self):
        sizes = {int(t.rsplit("_", 1)[1]) for t in self.entries(patch(self.tools))
                 if "JUMBO" not in t}
        self.assertGreater(len(sizes), 1, f"every tree the same size ({sizes})")

    def test_the_fir_rules_get_firs(self):
        text = patch(self.tools)
        fir = text.split("label = Fir Trees", 1)[1].split("}", 1)[0]
        import worlded.patch_rules_b42_trees as patcher
        self.assertTrue(any(sheet in fir for sheet in patcher.EVERGREEN), fir)

    def test_every_colour_the_renderer_paints_has_a_rule(self):
        text = patch(self.tools)
        for colour in (C.TREE_SMALL, C.TREE_BIG, C.TREE_HUGE, C.TREE_GIANT):
            with self.subTest(colour=colour):
                self.assertIn("color = {} {} {}".format(*colour), text)

    def test_the_small_trees_are_the_small_sizes(self):
        text = patch(self.tools)
        small = text.split("label = KnoxMap tree Small tree", 1)[1].split("]", 1)[0]
        import worlded.patch_rules_b42_trees as patcher
        indices = {int(t.rsplit("_", 1)[1]) for t in small.split()
                   if t.startswith("e_")}
        self.assertEqual(indices, {patcher.SIZE_INDEX[1], patcher.SIZE_INDEX[2]})

    def test_running_it_again_changes_nothing(self):
        once = patch(self.tools)
        self.assertEqual(patch(self.tools), once)

    def test_and_it_mends_what_an_older_version_wrote(self):
        # The first version substituted index for index, so an install set up
        # then has species sheets at 8 to 11: scenery, not trees.
        (self.tools / "config" / "Rules.txt").write_text(
            RULES.replace("vegetation_trees_01_8", "e_redmaple_1_8")
                 .replace("vegetation_trees_01_11", "e_dogwood_1_11"), encoding="utf-8")
        text = patch(self.tools)
        self.assertNotIn("e_redmaple_1_8", text)
        self.assertNotIn("e_dogwood_1_11", text)


def ground(size=(60, 60), colour=C.DARK_GRASS):
    return Image.new("RGB", size, colour)


def planted(size=(60, 60), colour=C.TREES):
    return Image.new("RGB", size, colour)


def big_trees(veg: Image.Image) -> dict:
    """{(x, y): colour} of every big tree on a vegetation bitmap."""
    px = veg.load()
    w, h = veg.size
    return {(x, y): px[x, y] for y in range(h) for x in range(w)
            if px[x, y] in C.BIG_TREE_ROOM}


class Projector:
    """Stands in for the renderer's: a degree is a tile."""

    meters_per_tile = 1.0

    @staticmethod
    def to_px(lat, lon):
        return lon, lat


def square(tags, x0, y0, x1, y1):
    return OSMFeature(1, "way", tags, [(y0, x0), (y0, x1), (y1, x1),
                                       (y1, x0), (y0, x0)])


class BigTreesStandApart(unittest.TestCase):
    def grow(self, veg=None, land=None, **kw):
        veg = veg or planted()
        land = land or ground(veg.size)
        with mock.patch.object(V, "tree_rules_ready", return_value=True):
            V._plant_big_trees(veg, land, [], [], [], Projector(), **kw)
        return veg

    def test_a_block_of_wood_grows_some_big_ones(self):
        self.assertTrue(big_trees(self.grow()))

    def test_none_of_them_stands_in_another_one_s_square(self):
        veg = self.grow()
        taken: set = set()
        for (x, y), colour in big_trees(veg).items():
            side = C.BIG_TREE_ROOM[colour]
            reach = side // 2 if side % 2 else 0
            square = {(fx, fy)
                      for fy in range(y - reach, y - reach + side)
                      for fx in range(x - reach, x - reach + side)}
            with self.subTest(at=(x, y)):
                self.assertFalse(square & taken, f"{colour} at {x},{y} overlaps")
            taken |= square

    def test_the_rest_of_the_square_is_cleared_for_it(self):
        veg = self.grow()
        px = veg.load()
        for (x, y), colour in big_trees(veg).items():
            side = C.BIG_TREE_ROOM[colour]
            reach = side // 2 if side % 2 else 0
            for fy in range(y - reach, y - reach + side):
                for fx in range(x - reach, x - reach + side):
                    if (fx, fy) != (x, y):
                        with self.subTest(at=(fx, fy)):
                            self.assertEqual(px[fx, fy], C.VEG_NOTHING)

    def test_none_of_them_hangs_off_the_edge_of_the_map(self):
        veg = self.grow()
        w, h = veg.size
        for (x, y), colour in big_trees(veg).items():
            side = C.BIG_TREE_ROOM[colour]
            reach = side // 2 if side % 2 else 0
            self.assertTrue(0 <= x - reach and x - reach + side <= w
                            and 0 <= y - reach and y - reach + side <= h)

    def test_a_hedge_is_not_cleared_to_make_room(self):
        veg = planted()
        for y in range(veg.size[1]):
            veg.putpixel((30, y), C.BUSHES)
        grown = self.grow(veg=veg)
        px = grown.load()
        kept = sum(1 for y in range(grown.size[1]) if px[30, y] == C.BUSHES)
        self.assertEqual(kept, grown.size[1], "the hedge was cut through")

    def test_and_none_of_them_stands_in_the_water(self):
        land = ground()
        for y in range(30, 60):
            for x in range(60):
                land.putpixel((x, y), C.WATER)
        grown = self.grow(land=land)
        wet = [(x, y) for (x, y) in big_trees(grown) if y >= 29]
        self.assertFalse(wet, f"big trees in the river: {wet[:4]}")

    def test_turning_the_trees_off_leaves_the_map_alone(self):
        veg = planted()
        before = list(veg.get_flattened_data() if hasattr(veg, "get_flattened_data")
                      else veg.getdata())
        V._plant_big_trees(veg, ground(), [], [], [], Projector(), density=0)
        self.assertEqual(list(veg.get_flattened_data()
                              if hasattr(veg, "get_flattened_data") else veg.getdata()),
                         before)

    def test_as_does_an_install_whose_rules_have_no_big_trees_in_them(self):
        veg = planted()
        with mock.patch.object(V, "tree_rules_ready", return_value=False):
            V._plant_big_trees(veg, ground(), [], [], [], Projector())
        self.assertFalse(big_trees(veg))

    def test_a_garden_gets_a_tree_but_never_one_that_swallows_the_house(self):
        # A jumbo XL leans over three squares and an XXL over five: a house
        # behind one cannot be seen at all, so a yard gets the small jumbo.
        house = square({"building": "house"}, 28, 28, 32, 32)
        veg = planted()
        with mock.patch.object(V, "tree_rules_ready", return_value=True):
            V._plant_big_trees(veg, ground(), [], [], [house], Projector())
        reach = V.GARDEN_REACH_TILES
        yard = {at: colour for at, colour in big_trees(veg).items()
                if max(abs(at[0] - 30), abs(at[1] - 30)) <= reach}
        self.assertTrue(yard, "nothing was planted in the yard")
        self.assertEqual({c for c in yard.values()} - {C.TREE_BIG}, set(),
                         f"a yard tree that swallows the house: {yard}")


class ParksHaveTreesRoundTheEdge(unittest.TestCase):
    def park(self, size=(120, 120), rules=True):
        veg = Image.new("RGB", size, C.VEG_NOTHING)
        land = ground(size, C.MEDIUM_GRASS)
        feats = [square({"leisure": "park"}, 5, 5, size[0] - 5, size[1] - 5)]
        with mock.patch.object(V, "tree_rules_ready", return_value=rules):
            V._paint_parks(veg, land, feats, Projector())
        return veg, land

    def colours(self, veg) -> set:
        px = veg.load()
        w, h = veg.size
        return {px[x, y] for y in range(h) for x in range(w)}

    def test_not_every_tree_in_a_park_is_the_same_height(self):
        # Which size a tree comes out is the rule's to say, and the rule a
        # park tree falls under calls for a grown one.
        self.assertIn(C.TREE_SMALL, self.colours(self.park()[0]))

    def test_and_an_install_without_the_rules_plants_plain_trees(self):
        colours = self.colours(self.park(rules=False)[0])
        self.assertNotIn(C.TREE_SMALL, colours)
        self.assertIn(C.TREES, colours)

    def density(self, veg, where) -> float:
        px = veg.load()
        inside = [(x, y) for x, y in where]
        grown = sum(1 for x, y in inside if px[x, y] != C.VEG_NOTHING)
        return grown / max(1, len(inside))

    def test_the_belt_round_the_edge_is_thicker_than_the_middle(self):
        veg, _land = self.park()
        deep = int(V.PARK_EDGE_M)
        belt = [(x, y) for y in range(6, 114) for x in range(6, 114)
                if min(x - 5, y - 5, 114 - x, 114 - y) <= deep]
        middle = [(x, y) for y in range(6, 114) for x in range(6, 114)
                  if min(x - 5, y - 5, 114 - x, 114 - y) > deep]
        self.assertGreater(self.density(veg, belt),
                           2 * self.density(veg, middle))

    def test_the_middle_is_not_left_bare_either(self):
        veg, _land = self.park()
        middle = [(x, y) for y in range(40, 80) for x in range(40, 80)]
        self.assertGreater(self.density(veg, middle), 0)

    def test_a_path_through_a_park_keeps_its_width(self):
        veg = Image.new("RGB", (120, 120), C.VEG_NOTHING)
        land = ground((120, 120), C.MEDIUM_GRASS)
        for x in range(120):
            land.putpixel((x, 60), C.PALE_CONCRETE)
        V._paint_parks(veg, land, [square({"leisure": "park"}, 5, 5, 115, 115)],
                       Projector())
        px = veg.load()
        on_the_path = [(x, y) for x in range(10, 110) for y in (59, 60, 61)
                       if px[x, y] != C.VEG_NOTHING]
        self.assertFalse(on_the_path, f"planted on the path: {on_the_path[:4]}")

    def test_nothing_grows_outside_the_park(self):
        veg, _land = self.park()
        px = veg.load()
        outside = [(x, y) for x in range(120) for y in range(120)
                   if (x < 4 or y < 4 or x > 116 or y > 116)
                   and px[x, y] != C.VEG_NOTHING]
        self.assertFalse(outside, f"planted outside: {outside[:4]}")


class PlantingBlocks(unittest.TestCase):
    """_block_picks: one place per block, inside the mask, once each."""

    def picks(self, mask, step, chance=1.0, seed=3):
        rng = np.random.default_rng(seed)
        return list(V._block_picks(mask, step, rng, chance))

    def test_every_pick_is_a_tile_of_the_mask(self):
        mask = np.zeros((40, 40), dtype=bool)
        mask[::3, ::5] = True
        for x, y in self.picks(mask, 6):
            self.assertTrue(mask[y, x], f"picked {x},{y}, which is not in the mask")

    def test_one_per_block_at_most(self):
        mask = np.ones((40, 40), dtype=bool)
        picks = self.picks(mask, 8)
        blocks = {(x // 8, y // 8) for x, y in picks}
        self.assertEqual(len(blocks), len(picks))

    def test_nothing_comes_of_an_empty_mask(self):
        self.assertEqual(self.picks(np.zeros((20, 20), dtype=bool), 4), [])

    def test_or_of_a_mask_smaller_than_one_block(self):
        self.assertEqual(self.picks(np.ones((3, 3), dtype=bool), 8), [])


if __name__ == "__main__":
    unittest.main()
