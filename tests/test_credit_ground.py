"""The credit spelled in the ground (knoxbuild/credit_ground.py)."""
import unittest

import numpy as np

from generator import pz_colors as C
from knoxbuild import credit_ground as cg


class Lettering(unittest.TestCase):
    def test_every_letter_of_the_credit_has_a_glyph(self):
        for text, _scale in cg.LINES:
            for ch in text:
                self.assertTrue(ch == " " or ch in cg._FONT, ch)

    def test_a_line_is_as_wide_as_its_letters(self):
        line = cg.render_line("KNOX", 1)
        self.assertEqual(line.shape, (cg.GLYPH_H, 4 * cg.GLYPH_W + 3))
        self.assertEqual(cg.render_line("KNOX", 2).shape, (10, 30))

    def test_the_letters_are_there(self):
        letters = cg.render()
        self.assertGreater(letters.sum(), 100)
        # the first line is KNOXMAP at twice the size: its top row has ink
        self.assertTrue(letters[0].any())


class Patch(unittest.TestCase):
    def test_the_nearest_clear_patch_to_the_spawn_wins(self):
        free = np.ones((120, 200), dtype=bool)
        free[:, 80:100] = False                      # a road
        x, y = cg.find_patch(free, (17, 56), (150, 60))
        self.assertGreaterEqual(x - cg.MARGIN, 100)  # the east side, where the spawn is
        self.assertLess(abs(x + 28 - 150), 30)

    def test_no_room_no_credit(self):
        self.assertIsNone(cg.find_patch(np.ones((10, 10), dtype=bool), (17, 56), (5, 5)))
        free = np.ones((60, 100), dtype=bool)
        free[::8, :] = False                         # a grille of walls
        self.assertIsNone(cg.find_patch(free, (17, 56), (50, 30)))

    def test_it_is_painted_where_the_free_tiles_are_and_nowhere_else(self):
        ground = np.zeros((80, 120, 3), dtype=np.uint8)
        ground[:, :] = C.MEDIUM_GRASS
        free = np.ones((80, 120), dtype=bool)
        free[:, :40] = False
        before = ground.copy()
        rows = [{"kind": "house", "tile_x": 90, "tile_y": 30, "width": 6, "height": 6}]
        at = cg.paint(ground, None, free, rows)
        self.assertIsNotNone(at)
        inked = np.all(ground != before, axis=2)
        self.assertTrue(inked.any())
        self.assertFalse((inked & ~free).any())
        self.assertTrue(np.all(ground[inked] == np.array(C.PALE_CONCRETE)))

    def test_it_is_the_same_every_time(self):
        def run():
            ground = np.zeros((80, 120, 3), dtype=np.uint8)
            return cg.paint(ground, None, np.ones((80, 120), dtype=bool),
                            [{"kind": "house", "tile_x": 60, "tile_y": 40, "width": 6,
                              "height": 6}]), ground.tobytes()
        self.assertEqual(run(), run())

    def test_the_first_spawn_house_is_the_one_nearest_the_middle_of_the_homes(self):
        rows = [{"kind": "house", "tile_x": x, "tile_y": 10, "width": 4, "height": 4}
                for x in (0, 50, 100)] + [{"kind": "shop", "tile_x": 500, "tile_y": 0,
                                           "width": 4, "height": 4}]
        self.assertEqual(cg.spawn_house(rows), (52, 12))


if __name__ == "__main__":
    unittest.main()
