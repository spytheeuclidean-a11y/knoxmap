"""The kerb colours are the rules' colours, and the diagonal tiles are real."""
import unittest

from generator import pz_colors as C
from worlded.patch_rules_roads import RULES

DIAG_COLOURS = {
    "NW 0": C.KERB_DNW_0, "NW 1": C.KERB_DNW_1,
    "NE 0": C.KERB_DNE_0, "NE 1": C.KERB_DNE_1,
    "SW 0": C.KERB_DSW_0, "SW 1": C.KERB_DSW_1,
    "SE 0": C.KERB_DSE_0, "SE 1": C.KERB_DSE_1,
}


class DiagonalKerbs(unittest.TestCase):
    def test_every_diagonal_colour_has_a_rule(self):
        by_colour = {colour: (label, tile) for label, colour, tile, _layer in RULES}
        for name, colour in DIAG_COLOURS.items():
            self.assertIn(colour, by_colour, f"no rule lays a tile on Kerb diag {name}")
            label, tile = by_colour[colour]
            self.assertEqual(label, f"Kerb diag {name}")
            self.assertTrue(tile.startswith("street_curbs_01_diag_"), tile)

    def test_the_two_pieces_a_direction_are_its_pair(self):
        by_label = {label: tile for label, _c, tile, _l in RULES}
        for direction in ("NW", "NE", "SW", "SE"):
            first = by_label[f"Kerb diag {direction} 0"]
            second = by_label[f"Kerb diag {direction} 1"]
            self.assertNotEqual(first, second, f"{direction} lays one piece twice")

    def test_the_tiles_the_rules_name_exist_in_the_game(self):
        try:
            from tools.preview_diag_kerbs import install_dir
            from tools.pzpk import read_pack
        except Exception:                       # noqa: BLE001 - tools are optional
            self.skipTest("the pack reader is not importable here")
        try:
            install = install_dir()
            tiles, _images = read_pack(install / "media/texturepacks/Tiles2x.floor.pack")
        except (SystemExit, OSError, ValueError):
            self.skipTest("the game with its 2x packs is not installed here")
        names = {tile.name for tile in tiles}
        for entry in RULES:
            tile = entry[2]
            if isinstance(tile, str) and tile.startswith("street_curbs_01_diag_"):
                self.assertIn(tile, names,
                              f"{tile} is not a tile the game can draw")


if __name__ == "__main__":
    unittest.main()
