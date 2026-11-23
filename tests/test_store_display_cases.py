import unittest

from knoxbuild import catalog, interiors, layout
from tests.test_shops import sales_floor


def tiles_for(role):
    return {tile for orient in catalog.FURNITURE[role].values() for tile in orient.values()}


class StoreDisplayCases(unittest.TestCase):
    def test_general_display_cases_are_not_butcher_cases(self):
        butcher_tiles = {f"location_shop_generic_01_{n:03d}" for n in range(80, 86)}
        self.assertFalse(tiles_for("shop_display") & butcher_tiles)
        self.assertEqual(tiles_for("shop_display_butcher"), butcher_tiles)
        self.assertEqual(tiles_for("shop_display_bakery"),
                         {f"location_shop_generic_01_{n:03d}" for n in range(32, 36)})
        self.assertTrue(all(tile.startswith("location_shop_generic_01_")
                            for tile in tiles_for("shop_display")))

    def test_only_butchers_use_meat_display_cases(self):
        butcher_tiles = {f"location_shop_generic_01_{n:03d}" for n in range(80, 86)}
        for kind in ("departmentstore", "grocery", "clothingstore", "jewelrystore",
                     "gunstore", "bakery"):
            _, _, furniture = sales_floor(kind, 2)
            found = {tile for role, *_ in furniture for tile in tiles_for(role)}
            self.assertFalse(found & butcher_tiles, kind)
        _, _, furniture = sales_floor("butcher", 2)
        self.assertTrue(any(tiles_for(role) & butcher_tiles for role, *_ in furniture))
        _, _, furniture = sales_floor("bakery", 2)
        self.assertTrue(any(role == "shop_display_bakery" for role, *_ in furniture))

    def test_other_store_fitting_plans_do_not_request_butcher_cases(self):
        for kind, spec in interiors.STORES.items():
            if kind == "butcher":
                continue
            roles = [value for value in spec.values() if isinstance(value, str)]
            roles += [role for value in spec.values() if isinstance(value, list) for role in value]
            self.assertNotIn("shop_display_butcher", roles, kind)

    def test_mall_department_store_has_no_butcher_case(self):
        plan = layout.build_building(79, 85, kind="mall", commercial=True, seed=4).storeys[0]
        anchors = {i for i, room in enumerate(plan.rooms, 1) if room.kind == "departmentstore"}
        self.assertTrue(anchors)
        butcher_tiles = {f"location_shop_generic_01_{n:03d}" for n in range(80, 86)}
        for role, x, y, _ in plan.furniture:
            if plan.grid[y][x] in anchors:
                self.assertFalse(tiles_for(role) & butcher_tiles, (role, x, y))

    def test_gunstore_has_elevated_retail_weight(self):
        import random
        self.assertGreaterEqual(interiors.STORE_WEIGHTS["gunstore"], 3)
        rng = random.Random(7)
        picks = [interiors.store_kind(rng) for _ in range(300)]
        self.assertGreaterEqual(picks.count("gunstore"), 8)

    def test_coolers_are_limited_by_room_and_building_size(self):
        for kind in ("conveniencestore", "grocery", "liquorstore", "gasstore"):
            for seed in (1, 2, 3):
                for w, h in ((36, 22), (20, 14), (12, 9)):
                    plan, idx, furniture = sales_floor(kind, seed, w, h)
                    tiles = sum(len(catalog.FURNITURE[r][o]) for r, _x, _y, o in furniture
                                if interiors.is_cooler(r))
                    room = sum(row.count(idx) for row in plan.grid)
                    building = sum(1 for row in plan.grid for v in row if v)
                    budget = max(interiors.MIN_COOLERS,
                                 min(room // interiors.COOLER_PER_ROOM_TILES,
                                     interiors.COOLER_BASE + building // interiors.COOLER_PER_BUILDING_TILES))
                    # A piece two tiles long may run one past the budget.
                    self.assertLessEqual(tiles, budget + 1, (kind, seed, w, h))
                    self.assertLess(tiles, room * 0.15, (kind, seed, w, h))

    def test_jewelry_cases_stand_in_rows_not_down_the_walls(self):
        for seed in (1, 2, 3):
            plan, idx, furniture = sales_floor("jewelrystore", seed)
            h, w = len(plan.grid), len(plan.grid[0])

            def off_the_wall(x, y):
                return all(0 <= y + j < h and 0 <= x + i < w and plan.grid[y + j][x + i] == idx
                           for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2))

            cases = [(x, y) for role, x, y, _o in furniture if role == "shop_display"]
            self.assertGreater(sum(off_the_wall(*c) for c in cases), len(cases) * 2 // 3, seed)
            rows = {y for x, y in cases if off_the_wall(x, y)}
            self.assertGreaterEqual(len(rows), 2, seed)

    def test_jewelry_and_electronics_store_interiors(self):
        _, _, jewelry_furn = sales_floor("jewelrystore", 3)
        j_roles = {role for role, *_ in jewelry_furn}
        self.assertIn("shop_display", j_roles)
        self.assertIn("shop_counter", j_roles)
        self.assertIn("register", j_roles)
        self.assertNotIn("shop_aisle", j_roles)
        self.assertTrue(j_roles & {"chair", "armchair", "mirror", "plant"})

        _, _, elec_furn = sales_floor("electronicsstore", 4)
        e_roles = {role for role, *_ in elec_furn}
        self.assertIn("shop_counter", e_roles)
        self.assertIn("register", e_roles)
        self.assertTrue(e_roles & {"tv", "radio"})
        self.assertTrue(e_roles & {"washer", "dishwasher", "shop_fridge_white"})

        _, _, gun_furn = sales_floor("gunstore", 5)
        g_roles = {role for role, *_ in gun_furn}
        self.assertIn("gun_locker", g_roles)
        self.assertIn("shop_display", g_roles)
        self.assertIn("register", g_roles)


if __name__ == "__main__":
    unittest.main()
