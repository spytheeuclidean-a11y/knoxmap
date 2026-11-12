"""Awnings and signboards over a shop's glass, from the game's own furniture.

The shop front itself is found by tbx._storefront_runs, which needs a whole
solved building to exercise; these pin the dressing that goes on it.
"""
import random
import unittest
from unittest import mock

from knoxbuild import catalog as C
from knoxbuild import tbx


class Storey:
    def __init__(self, width=10, height=10, doors=()):
        self.grid = [[0] * width for _ in range(height)]
        self.shop_front = [(x, 5, "N") for x in range(2, 8)]
        self.doors = list(doors)


class ShopfrontDressing(unittest.TestCase):
    def dress(self, doors=()):
        storey = Storey(doors=doors)
        with mock.patch.object(tbx, "_storefront_runs",
                               return_value=[("N", 5, 2, 6)]):
            return tbx.shopfront_dressing(storey, random.Random(1))

    def test_the_awning_covers_the_glass_and_the_sign_hangs_above_it(self):
        sign, awnings = self.dress()
        self.assertEqual(sorted(awnings), [(x, 5) for x in range(2, 8)])
        self.assertEqual(sorted(sign), [(3, 5), (4, 5), (5, 5), (6, 5)])

    def test_the_awning_skips_the_door(self):
        _sign, awnings = self.dress(doors=[(4, 5, "N")])
        self.assertNotIn((4, 5), awnings)
        self.assertIn((5, 5), awnings)

    def test_the_tiles_are_the_ones_the_tools_publish(self):
        sign, awnings = self.dress()
        awning_tiles = {name for design in C.AWNINGS for name in design.values()}
        self.assertTrue(set(awnings.values()) <= awning_tiles)
        self.assertTrue(set(sign.values()) <=
                        {t for strip in C.GAME_SIGNS["N"] for t in strip})
        # A signboard is four tiles wide and reads west to east on a north
        # wall, so the strip stands on consecutive squares.
        strip = [sign[(3, 5)], sign[(4, 5)], sign[(5, 5)], sign[(6, 5)]]
        self.assertIn(strip, C.GAME_SIGNS["N"])

    def test_a_run_too_short_for_a_signboard_gets_only_awnings(self):
        storey = Storey()
        with mock.patch.object(tbx, "_storefront_runs",
                               return_value=[("N", 5, 2, 3)]):
            sign, awnings = tbx.shopfront_dressing(storey, random.Random(1))
        self.assertEqual(sign, {})
        self.assertEqual(len(awnings), 3)

    def test_a_wall_facing_away_from_the_street_is_left_bare(self):
        storey = Storey()
        # Inside ground on the run's outside: the wall faces into the block.
        storey.grid[5][2] = 1
        with mock.patch.object(tbx, "_storefront_runs",
                               return_value=[("N", 5, 2, 6)]):
            self.assertEqual(tbx.shopfront_dressing(storey, random.Random(1)),
                             ({}, {}))

    def test_every_awning_design_has_both_facings(self):
        for design in C.AWNINGS:
            self.assertEqual(set(design), {"W", "N"})
            self.assertTrue(all(name.startswith("walls_decoration_01_")
                                for name in design.values()))


class BuiltShops(unittest.TestCase):
    def test_a_built_shop_carries_an_awning_and_a_sign(self):
        from knoxbuild import layout

        building = layout.build_building(
            18, 14, levels=2, kind="shop",
            uses=[("grocery", "grocerystorage")], street="S", seed=11)
        self.assertTrue(building.storeys[0].shop_front)
        document = tbx.render_tbx(building, "test-shop")
        awnings = {name for design in C.AWNINGS for name in design.values()}
        signs = {tile for strip in C.GAME_SIGNS["N"] for tile in strip}
        self.assertTrue(any(f'tile="{name}"' in document for name in awnings))
        self.assertTrue(any(f'tile="{name}"' in document for name in signs))
        # The awnings are over the glass, and the signboard one floor up.
        self.assertGreaterEqual(document.count('<tiles layer="WallFurniture">'), 2)

    def test_a_single_storey_shop_keeps_its_signboard_off_the_roof(self):
        from knoxbuild import layout

        building = layout.build_building(
            18, 14, levels=1, kind="shop",
            uses=[("grocery", "grocerystorage")], street="S", seed=11)
        document = tbx.render_tbx(building, "test-shop")
        awnings = {name for design in C.AWNINGS for name in design.values()}
        signs = {tile for strip in C.GAME_SIGNS["N"] for tile in strip}
        self.assertTrue(any(f'tile="{name}"' in document for name in awnings))
        self.assertFalse(any(f'tile="{name}"' in document for name in signs))


if __name__ == "__main__":
    unittest.main()
