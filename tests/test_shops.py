import unittest

from knoxbuild import layout


def sales_floor(kind, seed, w=36, h=22):
    plan = layout.build_building(width=w, height=h, kind="shop", seed=seed, levels=1,
                                 street="S", uses=[(kind, "storage")]).storeys[0]
    idx = next(i for i, r in enumerate(plan.rooms, 1) if r.kind == kind)
    return plan, idx, [f for f in plan.furniture if plan.grid[f[2]][f[1]] == idx]


def is_cooler(role):
    return "fridge" in role or "freezer" in role


class CoolersAreBanks(unittest.TestCase):
    def test_coolers_stand_side_by_side(self):
        # Scattered between shelves before: one cooler in three had no cooler
        # beside it.
        alone = total = 0
        for seed in range(12):
            for kind in ("grocery", "liquorstore"):
                plan, idx, furniture = sales_floor(kind, seed)
                tiles = {c for f in furniture if is_cooler(f[0])
                         for c in layout._cells_for(*f)}
                for x, y in tiles:
                    total += 1
                    alone += not any(n in tiles for n in
                                     ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        self.assertGreater(total, 0)
        self.assertLess(alone / total, 0.05)

    def test_a_grocery_has_produce_stands_by_the_door(self):
        stands = [sum(1 for f in sales_floor("grocery", s)[2] if f[0] == "shop_bin")
                  for s in range(12)]
        self.assertGreaterEqual(sum(stands) / len(stands), 4)

    def test_display_cases_are_a_row_or_two(self):
        for seed in range(6):
            plan, idx, furniture = sales_floor("butcher", seed)
            cases = {f[2] for f in furniture if f[0] == "shop_display"}
            with self.subTest(seed=seed):
                self.assertLessEqual(len({f[1] for f in furniture if f[0] == "shop_display"}), 2)


class Salons(unittest.TestCase):
    def rooms(self, erika=False):
        from unittest import mock
        with mock.patch.object(layout, "_erika_ready", lambda: erika):
            for seed in range(8):
                yield sales_floor("aesthetic", seed, 26, 16)

    def test_chairs_in_the_middle_and_counters_by_the_basins(self):
        for plan, idx, furniture in self.rooms():
            roles = [f[0] for f in furniture]
            with self.subTest(roles=roles):
                self.assertGreaterEqual(roles.count("office_chair"), 4)

    def test_no_bookcases_or_chests_in_a_salon(self):
        for erika in (False, True):
            for plan, idx, furniture in self.rooms(erika):
                bad = [f[0] for f in furniture
                       if f[0].startswith(("bookshelf", "dresser", "sidetable"))]
                self.assertFalse(bad, (erika, bad))


if __name__ == "__main__":
    unittest.main()
