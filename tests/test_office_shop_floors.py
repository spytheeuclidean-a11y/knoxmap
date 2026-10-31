"""Offices are fitted out across the floor; clothes racks stand on walls only."""
import unittest

from knoxbuild import layout
from knoxbuild.uses import use_of


def touches_wall(plan, cell) -> bool:
    here = layout._room_at(plan, *cell)
    return any(layout._room_at(plan, cell[0] + dx, cell[1] + dy) != here
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def office_rooms(seeds=range(30), size=(36, 28)):
    for seed in seeds:
        plan = layout.build_building(*size, kind="offices", street="S", seed=seed).storeys[0]
        for idx, room in enumerate(plan.rooms, 1):
            if room.kind == "office" and min(room.x1 - room.x0, room.y1 - room.y0) + 1 >= 7:
                yield plan, idx


def cells_of(plan, idx, prefix):
    return [c for role, x, y, o in plan.furniture if role.startswith(prefix)
            for c in layout._cells_for(role, x, y, o) if layout._room_at(plan, *c) == idx]


class Offices(unittest.TestCase):
    def test_desks_stand_out_in_the_floor(self):
        seen = 0
        for plan, idx in office_rooms():
            desks = cells_of(plan, idx, "desk")
            if not desks:
                continue
            seen += 1
            self.assertTrue(any(not touches_wall(plan, c) for c in desks),
                            "every desk in a roomy office is against a wall")
        self.assertGreater(seen, 5)

    def test_cabinets_and_plants_are_among_the_desks(self):
        floor = 0
        for plan, idx in office_rooms():
            for prefix in ("filing_cabinet", "plant"):
                floor += sum(not touches_wall(plan, c) for c in cells_of(plan, idx, prefix))
        self.assertGreater(floor, 5)


class ClothesShops(unittest.TestCase):
    def test_racks_only_against_walls(self):
        racks = 0
        for shop in ("clothes", "department_store", "shoes", "sports"):
            for seed in range(15):
                plan = layout.build_building(30, 22, kind="shop", uses=[use_of({"shop": shop})],
                                             street="S", seed=seed).storeys[0]
                for role, x, y, o in plan.furniture:
                    if role.startswith("clothes_rack"):
                        for cell in layout._cells_for(role, x, y, o):
                            racks += 1
                            self.assertTrue(touches_wall(plan, cell), f"{shop} {seed}: {role} mid-floor")
        self.assertGreater(racks, 0)


if __name__ == "__main__":
    unittest.main()
