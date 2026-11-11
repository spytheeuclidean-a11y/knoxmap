import unittest
from collections import Counter
from knoxbuild import layout


class BusinessCharacter(unittest.TestCase):
    def test_furniture_group_obeys_walkway_callback(self):
        room = layout.Room(0, 0, 9, 9, kind="office")
        plan = layout.Plan(10, 10, rooms=[room], grid=[[1] * 10 for _ in range(10)])
        group = [("office_chair", 0, 0, "N")]
        self.assertEqual(layout._place_group(plan, 1, room, group, 1, set(), set(),
                                             lambda cells: False), 0)
        self.assertEqual(layout._place_group(plan, 1, room, group, 1, set(), set(),
                                             lambda cells: True), 1)

    def test_school_canteen_has_a_kitchen(self):
        for seed in range(4):
            plan = layout.build_building(32, 28, kind="school", commercial=True,
                                         seed=seed).storeys[0]
            kinds = {r.kind for r in plan.rooms}
            self.assertIn("diningroom", kinds)
            self.assertIn("kitchen", kinds)
            self.assertIn("classroom", kinds)
            adj = layout._neighbours(plan)
            self.assertTrue(any(room.kind == "kitchen" and
                                any(plan.rooms[j - 1].kind == "diningroom" for j in adj[i])
                                for i, room in enumerate(plan.rooms, 1)))

    def test_fire_station_is_not_mostly_storage(self):
        for seed in range(4):
            plan = layout.build_building(32, 28, kind="fire", commercial=True,
                                         seed=seed).storeys[0]
            kinds = Counter(r.kind for r in plan.rooms if not r.is_core and r.kind != "hall")
            self.assertIn("firegarage", kinds)
            self.assertIn("bedroom", kinds)
            self.assertLessEqual(kinds["firestorage"] * 2, sum(kinds.values()))

    def test_industrial_buildings_have_work_and_staff_rooms(self):
        for seed in range(3):
            plan = layout.build_building(40, 32, kind="industrial", commercial=True,
                                         seed=seed).storeys[0]
            kinds = {r.kind for r in plan.rooms}
            self.assertTrue({"warehouse", "mechanic", "breakroom", "lockerroom"} <= kinds)
            for kind in ("mechanic", "breakroom", "lockerroom"):
                self.assertTrue(any(plan.grid[y][x] == i and role != "light"
                                    for i, r in enumerate(plan.rooms, 1) if r.kind == kind
                                    for role, x, y, _ in plan.furniture))

    def test_barn_and_shed_are_not_broken_into_a_grid_of_small_rooms(self):
        for kind in ("barn", "shed"):
            for seed in range(4):
                plan = layout.build_building(32, 28, kind=kind, commercial=True,
                                             seed=seed).storeys[0]
                self.assertLessEqual(len(plan.rooms), 6, (kind, seed))

    def test_small_castle_has_a_great_hall(self):
        plan = layout.build_building(20, 16, kind="castle", commercial=True,
                                     seed=0).storeys[0]
        self.assertIn("hall", {r.kind for r in plan.rooms})

    def test_small_stadium_has_a_changing_room(self):
        plan = layout.build_building(20, 16, kind="stadium", commercial=True,
                                     seed=0).storeys[0]
        self.assertIn("lockerroom", {r.kind for r in plan.rooms})


if __name__ == "__main__":
    unittest.main()
