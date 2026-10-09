import struct
import unittest

import numpy as np

from knoxbuild.kcell import SIDE, cell_source
from knoxbuild.rules import parse_rules
from knoxbuild.terrain import Palette, ground_layers, stack_order

RULES = """version = 1

alias
{
    name = grass
    tiles = [
        g_0
        g_1
        g_2
        g_3
    ]
}

rule
{
label = Grass
    bitmap = 0
    color = 10 20 30
    tiles = grass
    layer = 0_Floor
}

rule
{
label = Trees
    bitmap = 1
    color = 255 0 0
    tiles = [
        tree_a
        tree_b
        grass
    ]
    layer = 0_Vegetation
    condition = 10 20 30
}
"""


def pictures(h=40, w=50):
    land = np.zeros((h, w, 3), np.uint8)
    land[:] = (10, 20, 30)
    land[:, :5] = (1, 1, 1)               # a colour no rule knows
    veg = np.zeros((h, w, 3), np.uint8)
    veg[10:20, 10:20] = (255, 0, 0)
    return land, veg


class RulesTests(unittest.TestCase):
    def test_parse(self):
        rs = parse_rules(RULES)
        self.assertEqual(rs.aliases["grass"], ["g_0", "g_1", "g_2", "g_3"])
        self.assertEqual([r.layer for r in rs.rules], ["0_Floor", "0_Vegetation"])
        self.assertEqual(rs.rules[1].condition, (10, 20, 30))
        self.assertEqual(rs.rules[1].entries, ["tree_a", "tree_b", "grass"])

    def test_real_rules_file_parses_if_present(self):
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "vendor", "PZMappingTools", "config", "Rules.txt")
        if os.path.exists(p):
            from knoxbuild.rules import load_rules
            rs = load_rules(p)
            self.assertGreater(len(rs.rules), 100)
            self.assertGreater(len(rs.aliases), 50)


class TerrainTests(unittest.TestCase):
    def setUp(self):
        self.rs = parse_rules(RULES)
        self.land, self.veg = pictures()

    def run_layers(self, seed=1, land=None, veg=None, x0=0, y0=0):
        pal = Palette()
        layers = ground_layers(self.land if land is None else land, self.veg if veg is None else veg,
                               self.rs, pal, seed, x0, y0)
        return {k: np.array(pal.names, dtype=object)[v] for k, v in layers.items()}

    def test_tiles_come_from_the_rules_and_only_where_the_colour_is(self):
        out = self.run_layers()
        floor, vegetation = out["0_Floor"], out["0_Vegetation"]
        self.assertTrue(all(t == "" for t in floor[:, :5].ravel()))
        self.assertTrue(set(floor[:, 5:].ravel()) <= {"g_0", "g_1", "g_2", "g_3"})
        self.assertTrue(all(t == "" for t in vegetation[:10].ravel()))
        self.assertTrue(set(vegetation[10:20, 10:20].ravel()) <= {"tree_a", "tree_b", "g_0", "g_1", "g_2", "g_3"})
        # an alias entry is one entry in three, so a third of the picks, split four ways
        share = np.mean(np.isin(vegetation[10:20, 10:20], ["g_0", "g_1", "g_2", "g_3"]))
        self.assertTrue(0.15 < share < 0.5, share)

    def test_same_seed_same_tiles_and_another_seed_other_tiles(self):
        a, b, c = self.run_layers(1), self.run_layers(1), self.run_layers(2)
        self.assertTrue((a["0_Floor"] == b["0_Floor"]).all())
        self.assertFalse((a["0_Floor"] == c["0_Floor"]).all())

    def test_a_cut_out_window_gets_the_tiles_the_whole_picture_got(self):
        whole = self.run_layers()
        part = self.run_layers(land=self.land[8:30, 12:40], veg=self.veg[8:30, 12:40], x0=12, y0=8)
        self.assertTrue((whole["0_Floor"][8:30, 12:40] == part["0_Floor"]).all())
        self.assertTrue((whole["0_Vegetation"][8:30, 12:40] == part["0_Vegetation"]).all())

    def test_stack_order(self):
        self.assertEqual(stack_order({"0_Vegetation", "0_Floor", "0_Zed", "0_Curbs"}),
                         ["0_Floor", "0_Curbs", "0_Vegetation", "0_Zed"])


class CellSourceTests(unittest.TestCase):
    def words(self, data, names):
        """The square records of a one-level source, skipping the header."""
        o = 4 + 5 * 4 + 4
        for n in names:
            o += 2 + len(n.encode())
        o += 4 + 4 + 1                    # no rooms, no buildings, no zombie bytes
        return np.frombuffer(data[o:], dtype="<u4")

    def test_header_and_every_square_is_covered(self):
        a = np.zeros((SIDE, SIDE), np.int64)
        a[0, :3] = [1, 2, 1]
        b = np.zeros((SIDE, SIDE), np.int64)
        b[0, 1] = 2
        data = cell_source(83, 2, ["t_a", "t_b"], [[a, b]])
        self.assertEqual(data[:4], b"KCEL")
        self.assertEqual(struct.unpack_from("<5I", data, 4), (1, 83, 2, 0, 1))
        w = self.words(data, ["t_a", "t_b"])
        # square (0,0): 2 values + room, tile 0 ; (1,0): tiles 1 and 1 ; (2,0): tile 0 ; then empties
        self.assertEqual(list(w[:3]), [2, 0xFFFFFFFF, 0])
        self.assertEqual(list(w[3:7]), [3, 0xFFFFFFFF, 1, 1])
        self.assertEqual(list(w[7:10]), [2, 0xFFFFFFFF, 0])
        self.assertEqual(list(w[10:12]), [0xFFFFFFFF, SIDE * SIDE - 3])
        self.assertEqual(len(w), 12)

    def test_empty_level_is_one_run(self):
        data = cell_source(0, 0, [], [[np.zeros((SIDE, SIDE), np.int64)]])
        w = self.words(data, [])
        self.assertEqual(list(w), [0xFFFFFFFF, SIDE * SIDE])


if __name__ == "__main__":
    unittest.main()
