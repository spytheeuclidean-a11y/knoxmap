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
        # Two storeys of 132 is a house with an upstairs, not a mansion. The
        # rule is the ground floor it covers, not the house's total floor:
        # counting both storeys made half a town grand.
        self.assertFalse(L.build_plan(12, 11, seed=7, kind='house',
                                      level=0, levels=2).grand)
        self.assertTrue(L.build_plan(17, 16, seed=7, kind='house',
                                     level=0, levels=2).grand, "a big house still is one")
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
        self.assertGreater(len(grand.furniture), len(plain.furniture),
                           "the same house, dressed and not")
        extra = {role for roles in L.MANSION_EXTRA.values() for role in roles}
        self.assertTrue(extra & {role for role, *_ in grand.furniture})

    def test_mansion_floors_are_the_rich_ones(self):
        self.assertEqual(tbx.floor_options('livingroom', {}, mansion=True),
                         L.MANSION_FLOORS['livingroom'])
        self.assertNotEqual(tbx.floor_options('livingroom', {}, mansion=False),
                            L.MANSION_FLOORS['livingroom'])
        # A room a mansion does not dress keeps the house's own floor.
        self.assertTrue(tbx.floor_options('closet', {}, mansion=True))

    def test_a_mansion_gets_a_piano(self):
        # recreational_01 8-9: the piece that makes a big living room read as a
        # parlour rather than a bigger lounge.
        self.assertEqual(set(C.FURNITURE["piano"]), set("WNES"))
        self.assertEqual(len(C.FURNITURE["piano"]["N"]), 2)
        p = L.build_plan(16, 17, seed=7, kind='house', level=0, levels=1)
        roles = {role for role, *_ in p.furniture}
        self.assertIn("piano", roles)
        for role, x, y, orient in p.furniture:
            if role == "piano":
                cells = L._cells_for(role, x, y, orient)
                self.assertEqual(len(cells), 2, (role, x, y, orient))
                self.assertTrue(all(L._room_at(p, cx, cy) for cx, cy in cells))

    def test_no_chandeliers_anywhere(self):
        # Taken out of the catalogue: hung from the ceiling they never sat where
        # the room did, and a mansion is dressed from the floor up instead.
        self.assertNotIn("chandelier", C.FURNITURE)
        self.assertNotIn("chandelier", C.FURNITURE_LAYERS)
        for size in ((16, 17), (20, 18), (14, 14)):
            built = L.build_building(*size, levels=2, seed=7)
            hung = [f for s in built.storeys for f in s.furniture
                    if f[0] == "chandelier"]
            self.assertFalse(hung, size)

    def test_a_mansion_opens_the_stair_hall(self):
        # Two squares of the upper floor left out over the hall below, railed:
        # a landing over a hall two storeys high. Carved before furnishing, so
        # nothing is standing on a square that is about to become a hole.
        built = L.build_building(16, 17, levels=2, seed=7)
        self.assertTrue(built.grand)
        upper = built.storeys[1]
        self.assertTrue(upper.void, "the upstairs hall is open to the floor below")
        self.assertTrue(upper.railing, "and it has a rail round it")
        hall = next(r for r in built.storeys[0].rooms
                    if r.kind == "hall" and not r.is_core and r.area > 6)
        for x, y in upper.void:
            with self.subTest(tile=(x, y)):
                self.assertEqual(upper.grid[y][x], 0, "belongs to no room")
                self.assertTrue(hall.x0 <= x <= hall.x1 and hall.y0 <= y <= hall.y1,
                                "the hole is over the hall below")
                stood = [f for f in upper.furniture
                         if (x, y) in L._cells_for(f[0], f[1], f[2], f[3])]
                self.assertFalse(stood, stood)

    def test_a_house_is_not_open_to_below(self):
        built = L.build_building(10, 9, levels=2, seed=3)
        self.assertFalse(built.grand)
        for storey in built.storeys:
            self.assertFalse(storey.void)

    def test_a_mansion_hangs_a_gallery(self):
        # A house hangs one print a room, if that. A mansion hangs several: the
        # cap is what stops a big room's floor area turning into wallpaper, so a
        # mansion raises the cap instead of adding pictures to the wishlist
        # (they were counted inside the room's piece budget and came to nothing).
        self.assertEqual(L.WALL_ART_CAP, 1)
        self.assertGreaterEqual(L.MANSION_ART_CAP, 3)

        def art(plan):
            return [(role, x, y, o) for role, x, y, o in plan.furniture
                    if role.startswith("erika_art") or role in ("painting", "mirror")]

        hung = rooms = 0
        for size, seed in (((16, 17), 1), ((18, 16), 7), ((20, 18), 3)):
            plan = L.build_plan(*size, seed=seed, kind='house', level=0, levels=2)
            self.assertTrue(plan.grand, (size, seed))
            rooms += len(plan.rooms)
            hung += len(art(plan))
            for role, x, y, orient in art(plan):
                cells = L._cells_for(role, x, y, orient)
                self.assertIn(len(cells), (1, 2), "a picture hangs on a wall")
        self.assertGreaterEqual(hung / rooms, 1.2, "pictures in every room")

        small = L.build_plan(10, 9, seed=3, kind='house', level=0, levels=1)
        self.assertFalse(small.grand)
        self.assertLessEqual(len(art(small)), 4, "a small house is not a gallery")

    def test_a_picture_hangs_on_bare_wall_and_not_over_a_bookshelf(self):
        # Art is hung before the room's furniture, and on the north wall before
        # the west one. Both are draw order: a floor piece stands off a wall
        # that already carries something, and the north wall is the one the
        # game draws first - a picture anywhere else is drawn over the piece in
        # front of it instead of on the wall behind it.
        seen = {"N": 0, "W": 0}
        for seed in range(6):
            plan = L.build_plan(16, 17, seed=seed, kind='house', level=0, levels=1)
            for role, x, y, orient in plan.furniture:
                if not (role.startswith("erika_art") or role in ("painting", "mirror")):
                    continue
                self.assertIn(orient, ("N", "W"), "a picture hangs on a wall, not a ceiling")
                seen[orient] += 1
        self.assertGreater(seen["N"] + seen["W"], 10, "nothing hung")
        self.assertGreaterEqual(seen["N"], 2 * seen["W"],
                                f"pictures prefer the north wall: {seen}")

    def test_the_study_is_book_lined(self):
        shelves = [r for r in L.MANSION_EXTRA["office"]
                   if r.startswith(("erika_shelves", "bookshelf"))]
        self.assertGreaterEqual(len(shelves), 3, "a study of a mansion is books")
        for role in shelves:
            with self.subTest(role=role):
                self.assertEqual(C.FURNITURE_LAYERS[role], "Furniture")
                self.assertIn("N", C.FURNITURE[role])

    def test_every_mansion_role_and_floor_exists(self):
        missing = {role for roles in L.MANSION_EXTRA.values() for role in roles
                   if role not in C.FURNITURE}
        self.assertFalse(missing, f"no such furniture role: {sorted(missing)}")
        wrong = {name for names in L.MANSION_FLOORS.values() for name in names
                 if name not in C.EXTRA_FLOORS}
        self.assertFalse(wrong, f"no such floor: {sorted(wrong)}")


if __name__ == '__main__':
    unittest.main()
