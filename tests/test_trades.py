"""Trades laid out as the trade is, and homes furnished for who lives there.

A bar used to be three shelves and a painting, a church two chairs and a
table, a laundromat a house's washer, a gym crates. The pieces come from the
game's own tiles (tools/game_pieces.py)."""
import random
import unittest
from collections import Counter

from knoxbuild import catalog as C
from knoxbuild import interiors as I
from knoxbuild import layout as L


def trade_room(kind, use, seed, w=18, h=13):
    b = L.build_building(w, h, kind="shop", seed=seed, levels=1, street="S", uses=[(use, "storage")])
    s = b.storeys[0]
    idx = next((i for i, r in enumerate(s.rooms, 1) if r.kind == use), None)
    roles = Counter(f[0] for f in s.furniture
                    if idx and 0 <= f[2] < s.height and 0 <= f[1] < s.width and s.grid[f[2]][f[1]] == idx)
    return s, idx, roles


class Pieces(unittest.TestCase):
    def test_game_pieces_face_the_way_the_game_says(self):
        # The catalog key is the wall a piece stands against: one against a
        # west wall faces east.
        self.assertEqual(C.FURNITURE["coin_washer"]["W"]["0,0"], "appliances_laundry_01_005")
        self.assertEqual(set(C.FURNITURE["pew"]["N"]), {"0,0", "1,0", "2,0"})
        self.assertEqual(set(C.FURNITURE["treadmill"]), {"E", "S"})


class Trades(unittest.TestCase):
    def test_a_bar_has_its_counter_and_stools(self):
        seen = Counter()
        for seed in range(6):
            seen += trade_room("shop", "bar", seed)[2]
        self.assertGreater(seen["bar_counter"], 20)
        self.assertGreater(seen["bar_stool"], 10)

    def test_a_laundromat_has_washers_and_dryers(self):
        seen = Counter()
        for seed in range(6):
            seen += trade_room("shop", "laundry", seed)[2]
        self.assertGreater(seen["coin_washer"], 10)
        self.assertGreater(seen["coin_dryer"], 10)

    def test_a_gym_has_machines(self):
        seen = Counter()
        for seed in range(6):
            seen += trade_room("shop", "gym", seed)[2]
        self.assertGreater(seen["treadmill"] + seen["weight_machine"] + seen["weight_machine_alt"], 12)

    def test_salon_chairs_face_mirrors(self):
        at_mirror = chairs = 0
        for seed in range(6):
            s, idx, roles = trade_room("shop", "aesthetic", seed)
            mirrors = {(x, y) for r, x, y, o in s.furniture if r == "mirror"}
            for r, x, y, o in s.furniture:
                if r == "salon_chair" and s.grid[y][x] == idx:
                    chairs += 1
                    at_mirror += any((x + dx, y + dy) in mirrors for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        self.assertGreater(chairs, 6)
        self.assertGreater(at_mirror / chairs, 0.5)

    def test_a_church_has_pews_facing_an_altar(self):
        pews = altars = 0
        for seed in range(6):
            b = L.build_building(18 + seed, 26, kind="church", seed=seed, levels=1)
            for s in b.storeys:
                for r, x, y, o in s.furniture:
                    if s.grid[y][x] and s.rooms[s.grid[y][x] - 1].kind == "church":
                        pews += r == "pew"
                        altars += r == "altar"
        self.assertGreater(pews, 20)
        self.assertGreater(altars, 2)


class Households(unittest.TestCase):
    def test_household_kinds_follow_the_home(self):
        class P:
            kind = "house"
            profile = None
        kinds = Counter(I.household(random.Random(i), P)["kind"] for i in range(400))
        self.assertGreater(kinds["family"], kinds["retired"])
        self.assertGreater(kinds["retired"], 30)

    def test_children_and_retirees_change_their_rooms(self):
        room = L.Room(0, 0, 3, 3, kind="kidsbedroom", unit=1)
        base = ["bed", "dresser", "painting", "plant"]
        teen = I.for_household(base, room, {"kind": "family", "teen": True, "siblings": False},
                               {}, random.Random(1))
        self.assertIn("desk", teen)
        self.assertTrue(any(r.startswith("poster_") for r in teen))
        kids = I.for_household(base, room, {"kind": "family", "teen": False, "siblings": True},
                               {}, random.Random(1))
        self.assertIn("bunk_bed", kids)
        living = L.Room(0, 0, 5, 5, kind="livingroom", unit=1)
        old = I.for_household(["sofa", "tv"], living, {"kind": "retired", "teen": False,
                                                       "siblings": False}, {}, random.Random(1))
        self.assertIn("armchair", old)


if __name__ == "__main__":
    unittest.main()
