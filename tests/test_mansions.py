"""A large house is a mansion: richer floors and more dressing than a small one."""
import unittest

from knoxbuild import catalog as C
from knoxbuild import layout as L
from knoxbuild import tbx


class MansionHouses(unittest.TestCase):
    def test_a_big_house_is_a_mansion_and_a_small_one_is_not(self):
        self.assertFalse(L.build_plan(10, 9, seed=7, kind='house',
                                      level=0, levels=1).grand)
        self.assertTrue(L.build_plan(16, 17, seed=7, kind='house',
                                     level=0, levels=1).grand)
        # Two storeys of 132: no floor of it is large, the house is.
        self.assertTrue(L.build_plan(12, 11, seed=7, kind='house',
                                     level=0, levels=2).grand)
        # A block of flats is not somebody's mansion.
        self.assertFalse(L.build_plan(20, 20, seed=7, kind='apartment',
                                      level=0, levels=3).grand)

    def test_a_mansion_is_furnished_past_the_ordinary_wishlist(self):
        grand = L.build_plan(16, 17, seed=7, kind='house', level=0, levels=1)
        line = L.MANSION_FLOOR_TILES
        L.MANSION_FLOOR_TILES = 10 ** 6          # the same house, not a mansion
        try:
            plain = L.build_plan(16, 17, seed=7, kind='house', level=0, levels=1)
        finally:
            L.MANSION_FLOOR_TILES = line
        self.assertFalse(plain.grand)
        extra = {role for roles in L.MANSION_EXTRA.values() for role in roles}
        dressed = {role for role, *_ in grand.furniture} & extra
        self.assertTrue(dressed)
        self.assertFalse({role for role, *_ in plain.furniture} & extra,
                         "a small house keeps its own wishlist")

    def test_mansion_floors_are_the_rich_ones(self):
        self.assertEqual(tbx.floor_options('livingroom', {}, mansion=True),
                         L.MANSION_FLOORS['livingroom'])
        self.assertNotEqual(tbx.floor_options('livingroom', {}, mansion=False),
                            L.MANSION_FLOORS['livingroom'])
        # A room a mansion does not dress keeps the house's own floor.
        self.assertTrue(tbx.floor_options('closet', {}, mansion=True))

    def test_a_mansion_gets_a_piano_and_a_chandelier(self):
        # recreational_01 8-9 and lighting_indoor_03_0-1: the two pieces that
        # make a big house read as a parlour rather than a bigger lounge. The
        # piano is a two-tile piece that blocks the floor, so it goes in the
        # dining room, where a room has the floor to spare; a living room's
        # gets a chandelier and a rug and keeps its free floor in one piece.
        self.assertEqual(set(C.FURNITURE["piano"]), set("WNES"))
        self.assertEqual(len(C.FURNITURE["piano"]["N"]), 2)
        self.assertEqual(len(C.FURNITURE["chandelier"]["W"]), 2)
        self.assertEqual(C.FURNITURE_LAYERS["chandelier"], "FloorFurniture")
        p = L.build_plan(16, 17, seed=7, kind='house', level=0, levels=1)
        kinds = {i: r.kind for i, r in enumerate(p.rooms, start=1)}
        rooms = {(kinds[p.grid[y][x]] if p.grid[y][x] else None)
                 for role, x, y, _o in p.furniture if role == "piano"}
        self.assertIn("dining", rooms)
        self.assertIn("chandelier", {role for role, *_ in p.furniture})
        for role, x, y, orient in p.furniture:
            if role in ("piano", "chandelier"):
                cells = L._cells_for(role, x, y, orient)
                self.assertEqual(len(cells), 2, (role, x, y, orient))
                self.assertTrue(all(L._room_at(p, cx, cy) for cx, cy in cells))

    def test_every_mansion_role_and_floor_exists(self):
        missing = {role for roles in L.MANSION_EXTRA.values() for role in roles
                   if role not in C.FURNITURE}
        self.assertFalse(missing, f"no such furniture role: {sorted(missing)}")
        wrong = {name for names in L.MANSION_FLOORS.values() for name in names
                 if name not in C.EXTRA_FLOORS}
        self.assertFalse(wrong, f"no such floor: {sorted(wrong)}")


if __name__ == '__main__':
    unittest.main()
