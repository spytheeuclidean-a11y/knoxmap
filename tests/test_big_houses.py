"""Big house floors cut into rooms, and no room reached through a bathroom.

A closet the cut made room-sized failed the whole floor, so two in three big
house floors went to the plain splitter; such a closet is now the storage room
or study it looks like. A flat bedroom whose only other walls were the outside
or the corridor was entered through the bathroom; the two now swap.
"""
import random
import unittest

from knoxbuild import layout as L


class BigHouses(unittest.TestCase):
    def test_most_big_floors_are_cut_by_kind(self):
        seen = {"floors": 0, "cut": 0}
        orig = L._house_by_kind

        def spy(plan, level, levels, rng):
            got = orig(plan, level, levels, rng)
            seen["floors"] += 1
            seen["cut"] += got is not None
            return got

        L._house_by_kind = spy
        try:
            rng = random.Random(1)
            for i in range(24):
                L.build_building(rng.randint(20, 30), rng.randint(20, 28),
                                 levels=rng.choice((1, 2)), seed=i, kind=None)
        finally:
            L._house_by_kind = orig
        self.assertGreater(seen["floors"], 20)
        # 36% before; 77% over 119 floors after.
        self.assertGreater(seen["cut"] / seen["floors"], 0.6)


class ThroughBathrooms(unittest.TestCase):
    def test_flat_rooms_are_not_entered_through_the_bathroom(self):
        rooms = through = 0
        rng = random.Random(7)
        for i in range(30):
            b = L.build_building(rng.randint(14, 34), rng.randint(14, 30),
                                 levels=rng.choice((2, 3, 4)), seed=i, kind="apartment")
            for s in b.storeys:
                links = {}
                for x, y, d in s.doors:
                    a = L._room_at(s, x - 1, y) if d == "W" else L._room_at(s, x, y - 1)
                    c = L._room_at(s, x, y)
                    if a and c and a != c:
                        links.setdefault(a, set()).add(c)
                        links.setdefault(c, set()).add(a)
                baths = {j for j, r in enumerate(s.rooms, 1) if r.kind == "bathroom"}
                for j, r in enumerate(s.rooms, 1):
                    if j in baths or r.is_shaft:
                        continue
                    rooms += 1
                    through += bool(links.get(j)) and links[j] <= baths
        self.assertGreater(rooms, 500)
        # Flats only, the worst case: 1.70% without the swap, 0.64% with it.
        self.assertLess(through / rooms, 0.01)

    def test_a_swap_keeps_one_bathroom_and_its_door(self):
        # A bedroom reached only through the bathroom, which opens on a hall.
        hall = L.Room(0, 0, 2, 5, kind="hall", unit=1)
        bath = L.Room(3, 0, 6, 5, kind="bathroom", unit=1)
        bed = L.Room(7, 0, 9, 5, kind="bedroom", unit=1)
        plan = L.Plan(10, 6, rooms=[hall, bath, bed],
                      grid=[[1] * 3 + [2] * 4 + [3] * 3 for _ in range(6)],
                      doors=[(3, 2, "W"), (7, 2, "W")])
        self.assertEqual(L._swap_through_bathrooms(plan), 1)
        self.assertEqual([r.kind for r in plan.rooms], ["hall", "bedroom", "bathroom"])


if __name__ == "__main__":
    unittest.main()
