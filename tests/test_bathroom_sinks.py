import unittest

from knoxbuild import layout


class BathroomSinkSupport(unittest.TestCase):
    def make_plan(self, room_kind, role):
        room = layout.Room(0, 0, 2, 2, kind=room_kind)
        plan = layout.Plan(3, 3, rooms=[room], grid=[[1] * 3 for _ in range(3)])
        plan.furniture.append((role, 1, 1, "N"))
        return plan, room

    def test_pedestal_public_basin_does_not_get_counter_support(self):
        plan, room = self.make_plan("bathroom", "sink_public")

        layout._stand_on_something(plan, 1, room, {})

        self.assertEqual(plan.furniture, [("sink_public", 1, 1, "N")])

    def test_kitchen_sink_keeps_counter_support(self):
        plan, room = self.make_plan("kitchen", "kitchen_sink")

        layout._stand_on_something(plan, 1, room, {})

        self.assertEqual([role for role, *_ in plan.furniture],
                         ["counter", "kitchen_sink"])


class BathroomSize(unittest.TestCase):
    def test_a_big_bathroom_becomes_a_bathroom_and_a_store(self):
        room = layout.Room(0, 0, 15, 7, kind="bathroom")
        plan = layout.Plan(16, 8, rooms=[room], grid=[[1] * 16 for _ in range(8)])
        layout._trim_bathroom(plan, 0)
        self.assertEqual([r.kind for r in plan.rooms], ["bathroom", "storage"])
        self.assertLessEqual(plan.rooms[0].area, layout.BATHROOM_MAX_AREA)
        self.assertEqual(sum(row.count(1) for row in plan.grid), plan.rooms[0].area)

    def test_no_public_building_has_a_bathroom_hall(self):
        for kind in ("church", "library", "school", "fire"):
            for seed in range(8):
                b = layout.build_building(19 + seed, 15 + seed, levels=2, seed=seed,
                                          kind=kind, commercial=True)
                for s in b.storeys:
                    for i, r in enumerate(s.rooms, 1):
                        if r.kind == "bathroom":
                            self.assertLessEqual(sum(row.count(i) for row in s.grid), 40,
                                                 (kind, seed))


if __name__ == "__main__":
    unittest.main()
