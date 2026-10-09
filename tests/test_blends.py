import unittest

import numpy as np

from knoxbuild.blends import blend_layers, parse_blends
from knoxbuild.rules import parse_rules
from knoxbuild.terrain import Palette

RULES = """
alias
{
    name = grass
    tiles = [
        g_0
        g_1
    ]
}
"""


def blend(layer, tile, d, exclude=""):
    return f"""
blend
{{
    layer = {layer}
    mainTile = grass
    blendTile = {tile}
    dir = {d}
    exclude = {exclude}
}}
"""


ALL = "".join([
    blend("0_FloorOverlay", "ov_n", "n"), blend("0_FloorOverlay2", "ov_w", "w"),
    blend("0_FloorOverlay3", "ov_e", "e"), blend("0_FloorOverlay4", "ov_s", "s"),
    blend("0_FloorOverlay", "ov_nw", "nw"), blend("0_FloorOverlay2", "ov_ne", "ne"),
    blend("0_FloorOverlay3", "ov_sw", "sw"), blend("0_FloorOverlay4", "ov_se", "se"),
])


def run(picture, text=ALL, seam=None, x0=0, y0=0):
    """picture: rows of 'G' grass, 'R' road, '.' nothing. Returns {(x, y): set of overlay names}."""
    rules = parse_rules(RULES)
    pal = Palette()
    h, w = len(picture), len(picture[0])
    floor = np.zeros((h, w), np.int64)
    for y, row in enumerate(picture):
        for x, c in enumerate(row):
            if c != ".":
                floor[y, x] = pal.of("g_0" if c == "G" else "road")
    layers = blend_layers(floor, rules, parse_blends(text), pal, seed=1, x0=x0, y0=y0, seam=seam)
    out = {}
    for arr in layers.values():
        for y, x in zip(*np.nonzero(arr)):
            out.setdefault((int(x), int(y)), set()).add(pal.names[arr[y, x]])
    return out


class BlendTests(unittest.TestCase):
    def test_parse(self):
        b = parse_blends(ALL)
        self.assertEqual(len(b), 8)
        self.assertEqual((b[4].dir, b[4].tile, b[4].layer), ("nw", "ov_nw", "0_FloorOverlay"))

    def test_cardinal_neighbour(self):
        got = run(["...", "GR.", "..."])
        self.assertEqual(got, {(1, 1): {"ov_w"}})

    def test_two_opposite_neighbours(self):
        self.assertEqual(run(["GRG"]), {(1, 0): {"ov_w", "ov_e"}})

    def test_corner_replaces_the_two_cardinals(self):
        got = run(["GG.",
                   "GR.",
                   "..."])
        self.assertEqual(got[(1, 1)], {"ov_nw"})

    def test_a_lone_diagonal_gives_nothing(self):
        self.assertEqual(run(["G..", ".R.", "..."]).get((1, 1)), None)

    def test_main_ground_and_empty_squares_get_nothing(self):
        got = run(["GGG", ".G.", "..."])
        self.assertEqual(got, {})

    def test_excluded_ground_gets_nothing(self):
        text = blend("0_FloorOverlay", "ov_w", "w", exclude="grass")
        self.assertEqual(run(["GG"], text=text), {})
        text2 = blend("0_FloorOverlay", "ov_w", "w", exclude="g_1")
        self.assertEqual(run(["GR"], text=text2), {(1, 0): {"ov_w"}})

    def test_later_rule_wins_a_shared_layer(self):
        text = blend("0_FloorOverlay", "ov_first", "w") + blend("0_FloorOverlay", "ov_last", "w")
        self.assertEqual(run(["GR"], text=text), {(1, 0): {"ov_last"}})

    def test_seams(self):
        pic = ["GR"]
        self.assertEqual(run(pic, x0=299), {(1, 0): {"ov_w"}})
        self.assertEqual(run(pic, x0=299, seam=300), {})        # 299 | 300 is a seam
        self.assertEqual(run(pic, x0=10, seam=300), {(1, 0): {"ov_w"}})

    def test_a_cut_out_window_blends_the_same_inside(self):
        # the picks follow the position, and a margin of one square gives the same neighbours
        pic = ["GGRGG", "GGRRG", "GRRGG"]
        text = blend("0_FloorOverlay", "ov_w", "w") + blend("0_FloorOverlay2", "ov_e", "e")
        whole = run(pic, text=text)
        part = run([row[1:] for row in pic], text=text, x0=1)
        for (x, y), kinds in part.items():
            if x > 0:                      # column 0 of the cut-out has lost its west neighbour
                self.assertEqual(whole.get((x + 1, y)), kinds)


if __name__ == "__main__":
    unittest.main()
